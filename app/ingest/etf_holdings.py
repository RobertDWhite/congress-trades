"""Holdings of the congress-tracking ETFs (NANC = Democratic book, KRUZ = Republican book) from
the issuer's daily holdings CSV. Enables an overlap view: how our smart-money basket compares to
what the public 'congress ETFs' actually hold. Holdings CSV URLs are config-driven (they change).
"""
import csv
import datetime as dt
import io

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import load_config
from app.db import SessionLocal, init_db
from app.models import EtfHolding

from . import common

# Default issuer holdings CSVs (Unusual Whales / Subversive). Overridable via config.etf_holdings.urls.
DEFAULT_URLS = {
    "NANC": "https://etfs.unusualwhales.com/holdings/NANC.csv",
    "KRUZ": "https://etfs.unusualwhales.com/holdings/KRUZ.csv",
}


def _num(s):
    if s is None:
        return None
    s = str(s).strip().replace("%", "").replace("$", "").replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_holdings_csv(text):
    """Pure: holdings CSV text -> [{ticker, company, weight, shares}]. Tolerant of column naming."""
    out = []
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        low = {(k or "").strip().lower(): v for k, v in row.items()}
        ticker = (low.get("ticker") or low.get("symbol") or low.get("stockticker") or "").strip().upper()
        if not ticker or len(ticker) > 12:
            continue
        weight = _num(low.get("weight") or low.get("weighting") or low.get("% of net assets") or low.get("weight (%)"))
        if weight is not None and weight > 1.5:  # percentage -> fraction
            weight = weight / 100.0
        out.append({
            "ticker": ticker,
            "company": (low.get("name") or low.get("security name") or low.get("company") or "").strip()[:256] or None,
            "weight": weight,
            "shares": _num(low.get("shares") or low.get("quantity") or low.get("shares held")),
        })
    return out


def run():
    cfg = load_config()
    init_db()
    ec = cfg.get("etf_holdings", {})
    if not ec.get("enabled", True):
        return
    urls = ec.get("urls") or DEFAULT_URLS
    sess = common.make_session(cfg)
    db = SessionLocal()
    n = 0
    now = dt.datetime.now(dt.timezone.utc)
    today = dt.date.today()
    try:
        for etf, url in urls.items():
            try:
                r = sess.get(url, timeout=40)
                if r.status_code != 200:
                    print(f"etf_holdings: {etf} HTTP {r.status_code}")
                    continue
                holdings = parse_holdings_csv(r.text)
            except Exception as e:  # noqa: BLE001
                print(f"etf_holdings: {etf} failed: {e}")
                continue
            for h in holdings:
                db.execute(
                    pg_insert(EtfHolding)
                    .values(etf=etf, as_of=today, updated_at=now, **h)
                    .on_conflict_do_update(
                        index_elements=["etf", "ticker"],
                        set_={"company": h["company"], "weight": h["weight"], "shares": h["shares"],
                              "as_of": today, "updated_at": now},
                    )
                )
                n += 1
            db.commit()
            print(f"etf_holdings: {etf} stored {len(holdings)} holdings")
        common.record_run(db, "etf_holdings", rows_upserted=n, success=True)
    except Exception as e:  # noqa: BLE001
        common.record_run(db, "etf_holdings", success=False, note=str(e))
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
