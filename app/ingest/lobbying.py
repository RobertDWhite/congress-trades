"""Federal lobbying disclosures from the Senate LDA API (free; optional key raises rate limits),
joined to tracked tickers by client name. Shows which traded companies lobby Congress.
"""
import datetime as dt
import os
import time

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import load_config
from app.db import SessionLocal, init_db
from app.models import LobbyingRecord, TickerMeta

from . import common

FILINGS_URL = "https://lda.senate.gov/api/v1/filings/"


def _amount(filing):
    for k in ("income", "expenses"):
        v = filing.get(k)
        if v not in (None, ""):
            try:
                return float(v)
            except (ValueError, TypeError):
                pass
    return None


def parse_filing(filing, ticker):
    """Pure: an LDA filing dict -> a LobbyingRecord value dict (or None)."""
    uuid = filing.get("filing_uuid")
    if not uuid:
        return None
    client = (filing.get("client") or {}).get("name")
    registrant = (filing.get("registrant") or {}).get("name")
    issues = []
    for act in filing.get("lobbying_activities", []) or []:
        code = act.get("general_issue_area_code") or act.get("general_issue_code_display")
        if code:
            issues.append(code)
    return {
        "filing_uuid": str(uuid)[:64],
        "ticker": ticker,
        "client_name": (client or "")[:256] or None,
        "registrant_name": (registrant or "")[:256] or None,
        "amount": _amount(filing),
        "year": filing.get("filing_year"),
        "period": (filing.get("filing_period_display") or filing.get("filing_period") or "")[:32] or None,
        "issues": sorted(set(issues)) or None,
        "url": filing.get("filing_document_url") or filing.get("url"),
    }


def run():
    cfg = load_config()
    init_db()
    lc = cfg.get("lobbying", {})
    if not lc.get("enabled", True):
        return
    cap = int(lc.get("max_companies_per_run", 50))
    years = lc.get("years") or [dt.date.today().year, dt.date.today().year - 1]
    sess = common.make_session(cfg)
    key = os.environ.get("LDA_API_KEY")
    if key:
        sess.headers.update({"Authorization": f"Token {key}"})
    db = SessionLocal()
    n = 0
    try:
        targets = db.execute(
            select(TickerMeta.ticker, TickerMeta.company).where(TickerMeta.company.isnot(None))
        ).all()
        for ticker, company in targets[:cap]:
            for year in years:
                try:
                    r = sess.get(FILINGS_URL, params={"client_name": company, "filing_year": year, "page_size": 10}, timeout=40)
                    if r.status_code != 200:
                        time.sleep(0.8)
                        continue
                    for filing in r.json().get("results", []) or []:
                        rec = parse_filing(filing, ticker)
                        if not rec:
                            continue
                        db.execute(
                            pg_insert(LobbyingRecord)
                            .values(fetched_at=dt.datetime.now(dt.timezone.utc), **rec)
                            .on_conflict_do_update(
                                index_elements=["filing_uuid"],
                                set_={"ticker": ticker, "amount": rec["amount"], "issues": rec["issues"],
                                      "fetched_at": dt.datetime.now(dt.timezone.utc)},
                            )
                        )
                        n += 1
                except Exception as e:  # noqa: BLE001
                    print(f"lobbying: {ticker} {year} failed: {e}")
                time.sleep(0.6)  # LDA anonymous rate limit is strict
            if n % 50 == 0:
                db.commit()
        db.commit()
        common.record_run(db, "lobbying", rows_upserted=n, success=True)
        print(f"lobbying: stored {n} lobbying filings")
    except Exception as e:  # noqa: BLE001
        common.record_run(db, "lobbying", success=False, note=str(e))
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
