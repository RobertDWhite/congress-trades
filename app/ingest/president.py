"""Presidential STOCK Act trades from OGE Form 278-T periodic transaction reports.

The President is not in Congress, so transactions are disclosed to the U.S. Office of
Government Ethics (extapps2.oge.gov), not the House/Senate eFD systems. Reports are
periodic and broad-range (amounts are $ brackets), not real-time like Congress.

OGE publishes scanned PDFs that carry an Acrobat "Paper Capture" OCR text layer. We
download each filing, extract text with pdftotext (OCR fallback, reusing the House
pipeline), parse the transactions table, and store the rows as a normal Member
("Donald J. Trump", chamber="executive") under the authoritative 'oge_potus' source.

OGE has no per-president index view, so filing URLs are config-driven
(cfg['president']['filings']); a seed list of known public 278-T filings is used when
none are configured. As new periodic reports are published, add their URLs to config."""
import datetime as dt
import hashlib
import re
import time
import urllib.parse

from . import normalize as nz

# App/DB/house/requests imports are deferred into run()/_fetch so this module (and its
# pure parser) imports without a configured DATABASE_URL — keeps parse_278t unit-testable.

# Seed list of known public OGE Form 278-T filings for the current President, overridden by
# cfg['president']['filings'] when present. These extapps2.oge.gov copies carry an Acrobat OCR
# text layer and parse cleanly without local OCR. Newer filings arrive via discovery from the
# White House disclosures page (see DISCOVER_URL); badly-scanned ones yield nothing rather
# than junk thanks to the type/merge gates, and are marked 'paper' once OCR has been tried.
SEED_FILINGS = [
    "https://extapps2.oge.gov/201/Presiden.nsf/PAS+Index/5315A095A2EE1B9185258CEB006E7E36/$FILE/Donald-J-Trump-08.12.2025-278T(3).pdf",
    "https://extapps2.oge.gov/201/Presiden.nsf/PAS+Index/322B8A28DB21CC9285258CFD002C0D0B/$FILE/Donald%20J.%20Trump%209.3.25%20278-T.pdf",
    "https://extapps2.oge.gov/201/Presiden.nsf/PAS+Index/AA799A2729B4D1BE85258D430031A320/$FILE/Donald%20J.%20Trump%2010.17.2025%20278-T.pdf",
    "https://extapps2.oge.gov/201/Presiden.nsf/PAS+Index/18353894FE440B3685258D430031A337/$FILE/Donald%20J.%20Trump%2010.20.2025%20278-T%20(2).pdf",
    "https://extapps2.oge.gov/201/Presiden.nsf/PAS+Index/903A217DC18563EC85258D4A0031B044/$FILE/Donald%20J.%20Trump%2011.14.2025%20278-T.pdf",
]

# --- 278-T transaction-table parser ---------------------------------------------------
# Fixed OGE 278-T amount brackets -> (min, max). Match on a normalized lower bound.
BRACKETS = {
    1001: (1001, 15000), 15001: (15001, 50000), 50001: (50001, 100000),
    100001: (100001, 250000), 250001: (250001, 500000), 500001: (500001, 1000000),
    1000001: (1000001, 5000000), 5000001: (5000001, 25000000),
    25000001: (25000001, 50000000), 50000000: (50000000, None),
}
MINYR, MAXYR = 2023, 2030  # plausible filing-period transaction years

# An amount cell at end of line: two money tokens separated by a dash/bullet. OCR turns
# $->s/S, 0->o/O, l->1, and uses •·– for the hyphen. The number class deliberately excludes
# space (and whitespace runs are bounded) so the pattern stays linear — a space in the class
# would overlap the surrounding \s and backtrack catastrophically on number-heavy lines.
_AMT = re.compile(r"[\$sS]?\s*([\d.,oOlI]{2,})\s*[-–—•·]\s*[\$sS]?\s*([\d.,oOlI]{2,})\s*$")
# Transaction date = month/day/4-digit-year. OCR often drops the second slash
# ("8/11/2025" -> "8/112025"), so also accept a day+year run and split off the year.
_DATE = re.compile(r"\b(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*((?:19|20)\d{2})\b"
                   r"|\b(\d{1,2})\s*/\s*(\d{1,2})((?:19|20)\d{2})\b")
# Filing filenames carry the disclosure date in dotted form ("8.12.25", "1.14.2026"),
# sometimes with a stray digit group ("...Report-0.6.25.26-1.pdf" is 06/25/2026 part 1).
_DOTTED = re.compile(r"(?:\d{1,4}\.)+\d{1,4}")
# Lotus Notes document UNID in the OGE URL, used as a stable per-filing doc_id.
_UNID = re.compile(r"/([0-9A-Fa-f]{16,32})/\$FILE", re.IGNORECASE)

# The White House posts every presidential PTR on its disclosures page — the only public,
# enumerable index of these filings (OGE's Domino views hide the President and its full-text
# search is disabled). Polling it gives auto-discovery: new filings are ingested on the next
# run with no config change. Note these copies are raw scans with no text layer, so parsing
# them relies on the OCR fallback (ocr.enabled) — extapps2.oge.gov copies of the same
# filings carry an Acrobat OCR text layer and parse without it.
DISCOVER_URL = "https://www.whitehouse.gov/disclosures/"
_DISCOVER_PDF = re.compile(
    r'href="([^"]*(?:Periodic-Transaction-Report|278-?T)[^"]*\.pdf)"', re.IGNORECASE)

_SKIP = ("OGE Form", "OGE ƒ", "OGE �arm", "Transactions", "Tranuctlon", "Tranuctlona",
         "Description", "Filo(s", "Fllo(s", "FllofsNamo", "Note", "Summary of Contents",
         "Privacy Act", "If you", "If yo", "Filer", "Received", "Days Ago", "Daya Ago",
         "Over 30", "Ov•r 30", "Comments of", "Digitally signed", "OGE RECEIVED",
         "Signature", "Position")
# The page/column headers repeat on every page and OCR mangles them differently each time
# ("Received Over 30 Days Ago" -> "Recelvod Over DaysAgo"), so literal skips miss some and
# they leak into the next row's description. This catches header/boilerplate fragments
# fuzzily; only applied to non-amount (continuation) lines, so real trades are never lost.
_HEADER_NOISE = re.compile(
    r"(?i)(over\s*\w*\s*(30|days?|ago)|notif|descr|\bamount\b|\bpage\b|\btype\b.*\bdate\b)")
# Some filings use a layout that glues two transactions onto one text line. The giveaway is
# a type word followed by a date remnant (digit/digit) — or a dollar-amount remnant — inside
# the built description. Bare instrument words ("INSTALL SALE PG", "MTG PURCH SER B") don't
# trip it. Such rows mix two assets, so drop them rather than ingest a corrupted row.
_MERGED = re.compile(
    r"(?i)\b(?:(?:purch|ourch|nurch|pureh|oureh)\w*|sale|salo|sold)\b.{0,30}\d/\d"
    r"|\$\d[\d,]{2,}")
# A percent coupon plus a maturity marker ("% ... Due", OCR variants included, possibly glued
# to the maturity date as "DUE02/15/38") means a debt instrument, not equity.
_BOND = re.compile(r"(?i)%.*\bdu[eoa]")


def _classify(w):
    w = w.lower()
    if "urch" in w or "ureh" in w or "uroh" in w or "urcl" in w:
        return "purchase"
    if "sold" in w or "sale" in w or "salo" in w or "salc" in w:
        return "sale"
    if "xchang" in w or "xohang" in w:
        return "exchange"
    return None


def _find_date(before):
    """Return (iso_date|None, split_pos) — the last filing-period m/d/yyyy in `before`.

    The transaction date is the only filing-period m/d/yyyy on a row; bond maturities use
    text months or 2-digit/far-future years, which this skips via the MINYR..MAXYR window."""
    best = (None, None)
    for m in _DATE.finditer(before):
        mo, dy, yr = (m.group(1), m.group(2), m.group(3)) if m.group(3) \
            else (m.group(4), m.group(5), m.group(6))
        mo, dy, yr = int(mo), int(dy), int(yr)
        if 1 <= mo <= 12 and 1 <= dy <= 31 and MINYR <= yr <= MAXYR:
            best = (f"{yr:04d}-{mo:02d}-{dy:02d}", m.start())
    return best


def _money(tok):
    s = tok.replace("o", "0").replace("O", "0").replace("l", "1").replace("I", "1")
    s = re.sub(r"[^\d]", "", s)
    return int(s) if s else None


def _bracket(lo_tok):
    """Snap a parsed lower bound to a known OGE bracket -> (min, max). Returns (None, None)
    when it doesn't match any bracket, which lets the parser drop OCR false positives
    (every real 278-T amount is one of the fixed brackets)."""
    lo = _money(lo_tok)
    if lo is None:
        return (None, None)
    if lo in BRACKETS:
        return BRACKETS[lo]
    best = min(BRACKETS, key=lambda b: abs(b - lo))  # OCR may add/drop a digit
    return BRACKETS[best] if abs(best - lo) <= max(2, best * 0.02) else (None, None)


# A leading OCR fragment of the "Received Over 30 Days Ago" column header that bled into a
# description (it repeats per page and OCR mangles it differently each time).
_LEAK = re.compile(r"(?i)^.{0,45}?(?:days?\s*ago|daysago)\s*")


def parse_278t(text, filer_name=None):
    """Parse pdftotext -layout output of an OGE 278-T into transaction dicts.

    Each row is anchored on its amount bracket (the most OCR-stable cell); the columns run
    [# description] [type] [date] [received-over-30-days]. Amount and date are matched on an
    OCR-healed copy of the line (inter-digit spaces/dots removed, so "$100 001" and "202 5"
    parse and the patterns stay linear); the description and type come from the ORIGINAL line
    so coupon decimals are preserved. The amount must snap to a real OGE bracket, which drops
    OCR false positives. Best-effort: an unrecoverable date is left None (the filing's
    disclosure date still applies). Asset names stay as disclosed (mostly bonds; ticker is
    left to the alias step). `filer_name` (if given) drops the form's repeated name line."""
    filer_norm = nz.norm_name(filer_name) if filer_name else None
    rows, pending = [], []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if any(s in line for s in _SKIP) or (filer_norm and nz.norm_name(line) == filer_norm):
            pending = []
            continue
        healed = re.sub(r"(?<=\d)[ .](?=\d)", "", line)
        m = _AMT.search(healed)
        if not m:
            cont = re.sub(r"^\s*\d+\s*", "", line).strip()
            if cont and not _HEADER_NOISE.search(cont):
                pending.append(cont)
            continue
        lo, hi = _bracket(m.group(1))
        if lo is None:
            pending = []
            continue
        # date anchored on the healed line; the year window skips bond-maturity dates
        tx_date, _ = _find_date(healed)
        # Type + description from the ORIGINAL line. The type column is the rightmost
        # classifiable word; scan only trailing tokens so common muni "SALES TAX" names
        # earlier in the description aren't mistaken for a sale.
        ttype, desc_end = None, len(line)
        for w in reversed(list(re.finditer(r"\S+", line))[-12:]):
            c = _classify(w.group(0))
            if c:
                ttype, desc_end = c, w.start()
                break
        desc = re.sub(r"^\s*\d+\s*", "", " ".join(pending + [line[:desc_end]])).strip()
        desc = _LEAK.sub("", desc, count=1)
        desc = re.sub(r"\s{2,}", " ", desc).strip(" -•·")
        # A real 278-T row always has a Purchase/Sale/Exchange type and a description; when
        # neither survives OCR the row is too garbled to trust, so skip it. Likewise a type
        # word inside the description marks a multi-transaction merge artifact. This keeps
        # badly scanned filings emitting nothing instead of junk rows.
        if not ttype or not desc or _MERGED.search(desc):
            pending = []
            continue
        rows.append({
            "asset_name": desc,
            "asset_type": "bond" if _BOND.search(desc) else None,
            "transaction_type": ttype,
            "transaction_date": tx_date,
            "amount_min": lo,
            "amount_max": hi,
            "amount_range_raw": f"${lo:,} - ${hi:,}" if hi else f"${lo:,}+",
        })
        pending = []
    return rows


# --- ingest ---------------------------------------------------------------------------
def _doc_id(url):
    m = _UNID.search(url)
    if m:
        return m.group(1).upper()
    return hashlib.sha1(url.encode()).hexdigest()[:32]


def _name_date(url):
    """Filing (disclosure) date from the PDF filename's dotted date. Takes the last three
    dotted digit groups, so stray leading digits and part suffixes don't break it."""
    base = urllib.parse.unquote(url).rsplit("/", 1)[-1]
    runs = _DOTTED.findall(base)
    if not runs:
        return None
    parts = runs[-1].split(".")[-3:]
    if len(parts) < 3:
        return None
    mo, dy, yr = (int(x) for x in parts)
    if yr < 100:
        yr += 2000
    try:
        return dt.date(yr, mo, dy)
    except ValueError:
        return None


def _disclosure_date(entry, url):
    d = nz.parse_date(entry.get("disclosure_date")) if isinstance(entry, dict) else None
    return d or _name_date(url)


def discover_filings(sess, pc):
    """Best-effort enumeration of the filer's PTR PDF links from the disclosures page.
    Returns [] on any failure so ingest falls back to the configured/seed list.

    The page lists PTRs for ALL White House staff (Wiles, Zinberg, Kenny, ...), and run()
    attributes every ingested filing to the configured filer — so filtering by the filer's
    name tokens here is a correctness requirement, not cosmetics."""
    url = pc.get("discover_url", DISCOVER_URL)
    toks = [t for t in re.split(r"[^a-z]+", pc.get("filer_name", "Donald J. Trump").lower())
            if len(t) > 2]
    try:
        r = sess.get(url, timeout=60)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001 — discovery is best-effort
        print(f"president: discovery failed ({url}): {e}")
        return []
    seen = set()
    urls = []
    for m in _DISCOVER_PDF.finditer(r.text):
        href = urllib.parse.urljoin(url, m.group(1))
        base = urllib.parse.unquote(href).rsplit("/", 1)[-1].lower()
        if href not in seen and all(t in base for t in toks):
            seen.add(href)
            urls.append(href)
    urls.sort(key=lambda u: _name_date(u) or dt.date.max)  # oldest first, stable ingest order
    return urls


def _fetch(sess, url):
    import requests

    for attempt in range(4):
        try:
            r = sess.get(url, timeout=180)
        except requests.RequestException as e:
            print(f"president: request error {url} (attempt {attempt + 1}): {e}")
            time.sleep(3)
            continue
        if r.status_code == 200 and r.content:
            return r.content
        print(f"president: HTTP {r.status_code} for {url} (attempt {attempt + 1})")
        time.sleep(3)
    return None


def run():
    from app.config import load_config
    from app.db import SessionLocal, init_db
    from app.models import Filing

    from . import common
    from .house import extract_text, ocr_text

    cfg = load_config()
    init_db()
    pc = cfg.get("president") or {}
    filer_name = pc.get("filer_name", "Donald J. Trump")
    party = pc.get("party", "R")
    ocr_enabled = bool(cfg.get("ocr", {}).get("enabled"))
    ocr_dpi = int(cfg.get("ocr", {}).get("dpi", 200))
    sess = common.make_session(cfg)

    filings = list(pc.get("filings") or SEED_FILINGS)
    if pc.get("discover", True):
        known = {_doc_id(e["url"] if isinstance(e, dict) else e) for e in filings}
        extra = [u for u in discover_filings(sess, pc) if _doc_id(u) not in known]
        if extra:
            print(f"president: discovered {len(extra)} filing(s)")
        filings += extra
    if not filings:
        print("president: no filings configured or discovered")
        return

    db = SessionLocal()
    n = 0
    try:
        member = common.get_or_create_member(db, filer_name, chamber="executive", party=party)
        for entry in filings:
            url = entry["url"] if isinstance(entry, dict) else entry
            doc_id = _doc_id(url)
            existing = common.get_filing(db, "oge", doc_id)
            if existing and existing.parse_status in ("parsed", "ocr", "paper"):
                continue

            content = _fetch(sess, url)
            if not content:
                continue
            text = extract_text(content)
            status = "parsed"
            if len(text.strip()) < 30 and ocr_enabled:
                try:
                    text = ocr_text(content, ocr_dpi)
                    status = "ocr"
                except Exception as e:  # noqa: BLE001 — OCR is best-effort
                    print(f"president: OCR failed {doc_id}: {e}")
            disclosure_date = _disclosure_date(entry, url)

            f = existing or Filing(source="oge", doc_id=doc_id)
            f.chamber = "executive"
            f.member_id = member.id if member else None
            f.filing_type = "278-T"
            f.filing_date = disclosure_date
            f.source_url = url
            f.parse_status = status
            f.raw_text = text[:200000] if text else None
            f.fetched_at = dt.datetime.now(dt.timezone.utc)
            if not existing:
                db.add(f)
            db.flush()

            rows = parse_278t(text, filer_name=filer_name)
            if not rows and status == "parsed" and ocr_enabled:
                # An embedded text layer exists but is too garbled to parse (low-quality
                # scans — including everything on the White House page, which has no text
                # layer worth the name); a real OCR pass often reads better.
                try:
                    ocr = ocr_text(content, ocr_dpi)
                    rows = parse_278t(ocr, filer_name=filer_name)
                    if rows:
                        text, status = ocr, "ocr"
                        f.parse_status = status
                        f.raw_text = text[:200000]
                except Exception as e:  # noqa: BLE001 — OCR is best-effort
                    print(f"president: OCR retry failed {doc_id}: {e}")
            if not rows:
                # "paper" (terminal) once OCR has also been tried, else "error" (retried
                # next run — e.g. environments without OCR).
                f.parse_status = "paper" if (ocr_enabled or status == "ocr") else "error"
                print(f"president: no transactions parsed from {url}")
                continue
            for txn in rows:
                common.upsert_trade(
                    db,
                    source="oge_potus",
                    member=member,
                    chamber="executive",
                    filing_id=f.id,
                    transaction_date=nz.parse_date(txn["transaction_date"]),
                    disclosure_date=disclosure_date,
                    owner=None,
                    ticker=None,
                    asset_name=txn["asset_name"],
                    asset_type=txn["asset_type"],
                    transaction_type=txn["transaction_type"],
                    amount_min=txn["amount_min"],
                    amount_max=txn["amount_max"],
                    amount_range_raw=txn["amount_range_raw"],
                )
                n += 1
            db.commit()
            print(f"president: {url} -> {len(rows)} transactions")
        common.record_run(db, "president", rows_upserted=n, success=True)
        print(f"president: upserted {n} transactions")
    finally:
        db.close()


if __name__ == "__main__":
    run()
