from ingest import normalize as nz
from ingest import president as pres

# Representative OGE Form 278-T text (pdftotext -layout output), reproducing the OCR noise
# seen in real filings: $->s/S and bullet separators in amounts, a dropped date slash
# ("8/112025"), garbled "purchase" spellings, bond maturity dates inside the description,
# the form's repeated name line, and a description wrapped across two lines.
SAMPLE = """OGE Form 278-T (Updated February 2024)
#              Description                                          Type Date            Notification          Amount
Filer's Name
Donald J Trump
                KANSAS CITY MO WTR REV SER A B/E 3.25 % Due Dec 1, 2034        ourchaso    9/3/2025     No     $1,001 - $15,000
                BLACK BELT ENERGY GAS DIST AL GAS REV PJ 4.00 % Due Oct 1, 2052   ourchaso    8/28/2025    Yes    $250,001 • $500,000
                KENTUCKY KY PUB ENERGY AUTH 4.00 % Due Dec 1, 2050    nurchasc   8/112025     No     $50,001 • $100,000
                INTEL CORP 3.75% DUE 08/05/27          ourchase    8/29/2025    Yes    s1,000,001 - S5,000,000
                APPLE INC COM             sold        7/15/2025    No     $15,001 - $50,000
                BROWARD CNTY FL 2.384% AIR TRAN DUE 10/01/26
                XTRO TAXBL            ourchaso    8/29/2025    Yes    $1,000,001 - $5,000,000"""


def _rows():
    return pres.parse_278t(SAMPLE, filer_name="Donald J. Trump")


def test_parses_all_transaction_rows_skips_headers_and_name():
    rows = _rows()
    assert len(rows) == 6  # 6 transactions; form headers and the name line are skipped
    assert all("trump" not in r["asset_name"].lower() for r in rows)


def test_amount_brackets_tolerate_ocr_dollars_and_bullets():
    rows = _rows()
    assert (rows[0]["amount_min"], rows[0]["amount_max"]) == (1001, 15000)
    assert (rows[1]["amount_min"], rows[1]["amount_max"]) == (250001, 500000)  # bullet sep
    assert (rows[3]["amount_min"], rows[3]["amount_max"]) == (1000001, 5000000)  # s/S dollars


def test_transaction_date_anchors_on_filing_period_not_maturity():
    rows = _rows()
    # the 08/05/27 maturity in the description must not be taken as the transaction date
    assert rows[3]["transaction_date"] == "2025-08-29"
    # a dropped date slash ("8/112025") is healed
    assert rows[2]["transaction_date"] == "2025-08-11"


def test_transaction_type_classification():
    rows = _rows()
    assert [r["transaction_type"] for r in rows[:4]] == ["purchase"] * 4
    assert rows[4]["transaction_type"] == "sale"


def test_description_preserved_and_wrapped_lines_joined():
    rows = _rows()
    assert "3.75" in rows[3]["asset_name"]  # coupon decimal not corrupted by date healing
    assert "BROWARD" in rows[5]["asset_name"] and "XTRO" in rows[5]["asset_name"]


def test_asset_type_bond_vs_equity():
    rows = _rows()
    assert rows[0]["asset_type"] == "bond"          # "% Due Dec 1, 2034"
    assert rows[3]["asset_type"] == "bond"          # "3.75% DUE 08/05/27" (glued DUE)
    assert rows[4]["asset_type"] is None            # APPLE INC COM (equity)


def test_merged_rows_dropped_but_instrument_words_kept():
    # Two transactions glued onto one line (type + date remnant inside the description)
    # must be dropped; munis whose NAMES contain SALE/PURCH must not be.
    merged = ("                KENDALL KANE & WILL 5% DUE 02/01/35 ourehase 10/9/2025 No"
              " S1 ooo 001- Ss ooo ooo NORTH TEX TWY AUTH   purchase   10/7/2025   No   $500,001 - $1,000,000")
    legit = ("                GEORGIA MUN ASSN INC INSTALL SALE PG CTF PARTN RFDG REV B/E 5.00 %"
             "   ourchase   10/1/2025   No   $100,001 - $250,000\n"
             "                MAINE ST HSG AUTH MTG PURCH SERB REV 8/E 2.10 % Due Nov 15, 2026"
             "   ourchase   10/1/2025   No   $100,001 - $250,000")
    assert pres.parse_278t(merged) == []
    kept = pres.parse_278t(legit)
    assert len(kept) == 2 and all(r["transaction_type"] == "purchase" for r in kept)


def test_name_date_handles_wh_and_oge_filenames():
    cases = {
        "https://x/Donald-J-Trump-08.12.2025-278T(3).pdf": "2025-08-12",
        "https://x/Donald%20J.%20Trump%209.3.25%20278-T.pdf": "2025-09-03",
        "https://x/President-Donald-J.-Trump-Periodic-Transaction-Report-1.14.2026-.pdf": "2026-01-14",
        # stray leading digit group: "0.6.25.26" is 06/25/2026
        "https://x/President-Donald-J.-Trump-Periodic-Transaction-Report-0.6.25.26-1.pdf": "2026-06-25",
        "https://x/President-Donald-J.-Trump-Periodic-Transaction-Report-05.08.26-2.pdf": "2026-05-08",
    }
    for url, want in cases.items():
        d = pres._name_date(url)
        assert d is not None and d.isoformat() == want, (url, d)


def test_discovery_regex_extracts_ptr_links():
    html = (
        '<a href="https://www.whitehouse.gov/wp-content/uploads/2026/05/'
        'President-Donald-J.-Trump-Periodic-Transaction-Report-05.08.26-1.pdf">r1</a>'
        '<a href="/wp-content/uploads/2025/08/Donald-J-Trump-278T.pdf">r2</a>'
        '<a href="/wp-content/uploads/2026/01/Some-Other-Official-Ethics-Waiver.pdf">no</a>'
    )
    urls = [m.group(1) for m in pres._DISCOVER_PDF.finditer(html)]
    assert len(urls) == 2
    assert urls[0].endswith("05.08.26-1.pdf") and urls[1].endswith("278T.pdf")


class _FakeResp:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class _FakeSession:
    def __init__(self, text):
        self._text = text

    def get(self, url, timeout=None):
        return _FakeResp(self._text)


def test_discovery_filters_to_filer_only():
    # The WH disclosures page lists PTRs for ALL staff; only the configured filer's
    # filings may be ingested (everything is attributed to that member).
    html = (
        '<a href="/a/President-Donald-J.-Trump-Periodic-Transaction-Report-05.08.26-1.pdf">t</a>'
        '<a href="/a/Zinberg-Joel-Periodic-Transaction-Report-03.13.26.pdf">z</a>'
        '<a href="/a/Wiles-Susie-Periodic-Transaction-Report-06.13.25.pdf">w</a>'
        '<a href="/a/President-Donald-J.-Trump-Periodic-Transaction-Report-4.20.26.pdf">t2</a>'
    )
    urls = pres.discover_filings(_FakeSession(html), {"discover_url": "https://x/"})
    assert len(urls) == 2
    assert all("Trump" in u for u in urls)
    # sorted oldest-first by filename date
    assert urls[0].endswith("4.20.26.pdf") and urls[1].endswith("05.08.26-1.pdf")


def test_dedup_key_disambiguates_null_ticker_by_asset_name():
    # The President's bond purchases share date/amount/type with no ticker; the asset name
    # must keep them as distinct trades instead of collapsing onto one dedup_key.
    a = nz.dedup_key("executive", "donald trump", "2025-08-28", None, 1000001, 5000000,
                     "purchase", asset_name="BLACK BELT ENERGY")
    b = nz.dedup_key("executive", "donald trump", "2025-08-28", None, 1000001, 5000000,
                     "purchase", asset_name="INTEL CORP")
    assert a != b


def test_dedup_key_ignores_asset_name_when_ticker_present():
    # Back-compat: ticker-bearing trades (all congressional history) are keyed exactly as
    # before, regardless of asset name.
    base = nz.dedup_key("house", "jane doe", "2026-01-02", "NVDA", 1000, 15000, "purchase")
    with_a = nz.dedup_key("house", "jane doe", "2026-01-02", "NVDA", 1000, 15000,
                          "purchase", asset_name="X")
    with_b = nz.dedup_key("house", "jane doe", "2026-01-02", "NVDA", 1000, 15000,
                          "purchase", asset_name="Y")
    assert base == with_a == with_b
