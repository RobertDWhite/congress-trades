"""Federal awards from USASpending.gov (free, no key) joined to tracked tickers by recipient name.

For each tracked company we pull its largest recent federal contracts/grants and store them, so the
dossier can show "member bought a federal contractor" context. Timing/context only, not causation.
"""
import datetime as dt
import time

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import load_config
from app.db import SessionLocal, init_db
from app.models import GovContract, TickerMeta

from . import common

SEARCH_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
AWARD_URL = "https://www.usaspending.gov/award/{}"
# A=BPA-call, B=purchase-order, C=delivery-order, D=definitive contract; grants 02-05
AWARD_TYPES = ["A", "B", "C", "D", "02", "03", "04", "05"]
FIELDS = ["Award ID", "Recipient Name", "Award Amount", "Awarding Agency", "Action Date",
          "Description", "Award Type", "generated_internal_id"]


def _award_type(label):
    low = (label or "").lower()
    if "grant" in low:
        return "grant"
    if "loan" in low:
        return "loan"
    return "contract"


def search_awards(sess, company, start_date, limit=10):
    """Return parsed award dicts for a recipient. Pure-ish (takes a session); used by run()."""
    body = {
        "filters": {
            "recipient_search_text": [company],
            "award_type_codes": AWARD_TYPES,
            "time_period": [{"start_date": start_date, "end_date": dt.date.today().isoformat()}],
        },
        "fields": FIELDS,
        "page": 1,
        "limit": limit,
        "sort": "Award Amount",
        "order": "desc",
    }
    r = sess.post(SEARCH_URL, json=body, timeout=40)
    if r.status_code != 200:
        return []
    out = []
    for row in r.json().get("results", []) or []:
        gid = row.get("generated_internal_id") or row.get("Award ID")
        if not gid:
            continue
        action = row.get("Action Date")
        try:
            action_date = dt.date.fromisoformat(action[:10]) if action else None
        except (ValueError, TypeError):
            action_date = None
        agency = row.get("Awarding Agency")
        out.append({
            "award_id": str(gid)[:64],
            "recipient_name": (row.get("Recipient Name") or company)[:256],
            "awarding_agency": (agency if isinstance(agency, str) else (agency or {}).get("name") if isinstance(agency, dict) else None),
            "award_type": _award_type(row.get("Award Type")),
            "award_amount": float(row.get("Award Amount")) if row.get("Award Amount") is not None else None,
            "action_date": action_date,
            "description": (row.get("Description") or "")[:1000] or None,
            "url": AWARD_URL.format(gid),
        })
    return out


def run():
    cfg = load_config()
    init_db()
    cc = cfg.get("contracts", {})
    if not cc.get("enabled", True):
        return
    cap = int(cc.get("max_companies_per_run", 60))
    lookback_days = int(cc.get("lookback_days", 1095))
    start_date = (dt.date.today() - dt.timedelta(days=lookback_days)).isoformat()
    sess = common.make_session(cfg)
    db = SessionLocal()
    n = 0
    try:
        # tracked tickers that have a resolvable company name
        targets = db.execute(
            select(TickerMeta.ticker, TickerMeta.company).where(TickerMeta.company.isnot(None))
        ).all()
        for ticker, company in targets[:cap]:
            try:
                awards = search_awards(sess, company, start_date)
            except Exception as e:  # noqa: BLE001
                print(f"contracts: {ticker} ({company}) failed: {e}")
                time.sleep(0.5)
                continue
            for a in awards:
                db.execute(
                    pg_insert(GovContract)
                    .values(ticker=ticker, fetched_at=dt.datetime.now(dt.timezone.utc), **a)
                    .on_conflict_do_update(
                        index_elements=["award_id"],
                        set_={"ticker": ticker, "award_amount": a["award_amount"], "action_date": a["action_date"],
                              "fetched_at": dt.datetime.now(dt.timezone.utc)},
                    )
                )
                n += 1
            if n % 50 == 0:
                db.commit()
            time.sleep(0.3)  # be polite to USASpending
        db.commit()
        common.record_run(db, "contracts", rows_upserted=n, success=True)
        print(f"contracts: stored {n} federal awards")
    except Exception as e:  # noqa: BLE001
        common.record_run(db, "contracts", success=False, note=str(e))
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
