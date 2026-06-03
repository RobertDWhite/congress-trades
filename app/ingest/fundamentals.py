"""SEC EDGAR company fundamentals (free/public), joined to tracked tickers via CIK.

Pulls the XBRL `companyfacts` document for each tracked company and stores the latest annual
(10-K) revenue / net income / assets / diluted EPS plus the most recent quarterly (10-Q)
figures into ticker_fundamentals. Powers the dossier's fundamentals card and the conflict
score's 'company fundamentals context' component.

SEC requires a descriptive User-Agent and rate-limits to ~10 req/s. Informational only.
"""
import datetime as dt
import time

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import load_config
from app.db import SessionLocal, init_db
from app.models import TickerFundamentals, TickerMeta

from . import common

COMPANYFACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_UA = "whitehouse-rke2 congress-trades robert@whitematter.tech"

# concept fallbacks, most-specific first (filers tag revenue inconsistently)
_REVENUE = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
]
_NET_INCOME = ["NetIncomeLoss", "ProfitLoss"]
_ASSETS = ["Assets"]
_EPS = ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"]
_SHARES = ["WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageNumberOfSharesOutstandingBasic"]


def _series(facts, concepts, unit="USD"):
    gaap = (facts or {}).get("us-gaap", {})
    for c in concepts:
        node = gaap.get(c)
        if not node:
            continue
        arr = (node.get("units") or {}).get(unit)
        if arr:
            return arr
    return []


def _to_date(s):
    try:
        return dt.date.fromisoformat(s[:10])
    except (TypeError, ValueError):
        return None


def _latest(arr, form=None, fp=None):
    rows = [x for x in arr if x.get("end") and (form is None or x.get("form") == form) and (fp is None or x.get("fp") == fp)]
    rows.sort(key=lambda x: x["end"])
    return rows[-1] if rows else None


def _annual(arr):
    """Latest full-year value; prefer 10-K/FY, fall back to any FY-period entry."""
    return _latest(arr, form="10-K", fp="FY") or _latest(arr, fp="FY")


def _prior_annual(arr, latest_end):
    """The FY value ~1 year before latest_end (for a YoY comparison)."""
    if not latest_end:
        return None
    target = latest_end.year - 1
    fy = [x for x in arr if x.get("fp") == "FY" and _to_date(x.get("end")) and _to_date(x["end"]).year == target]
    fy.sort(key=lambda x: x["end"])
    return fy[-1] if fy else None


def parse_companyfacts(payload):
    """Pure: SEC companyfacts JSON -> flat fundamentals dict (or None if nothing usable)."""
    facts = payload.get("facts") or {}
    rev_series = _series(facts, _REVENUE)
    ni_series = _series(facts, _NET_INCOME)

    rev_a = _annual(rev_series)
    ni_a = _annual(ni_series)
    assets_a = _latest(_series(facts, _ASSETS))
    eps_a = _annual(_series(facts, _EPS, unit="USD/shares"))
    shares_a = _annual(_series(facts, _SHARES, unit="shares"))

    fy_end = _to_date(rev_a["end"]) if rev_a else (_to_date(ni_a["end"]) if ni_a else None)
    revenue = rev_a.get("val") if rev_a else None
    rev_prior_row = _prior_annual(rev_series, fy_end)
    revenue_prior = rev_prior_row.get("val") if rev_prior_row else None
    revenue_yoy = None
    if revenue is not None and revenue_prior:
        try:
            revenue_yoy = (float(revenue) - float(revenue_prior)) / abs(float(revenue_prior))
        except ZeroDivisionError:
            revenue_yoy = None

    q_rev = _latest(rev_series, form="10-Q")
    q_ni = _latest(ni_series, form="10-Q")
    q_end = _to_date(q_rev["end"]) if q_rev else (_to_date(q_ni["end"]) if q_ni else None)

    latest_form = None
    if q_end and (not fy_end or q_end > fy_end):
        latest_form = "10-Q"
    elif fy_end:
        latest_form = "10-K"

    out = {
        "cik": str(payload.get("cik")) if payload.get("cik") is not None else None,
        "company": payload.get("entityName"),
        "fy": rev_a.get("fy") if rev_a else (ni_a.get("fy") if ni_a else None),
        "fy_end": fy_end,
        "revenue": revenue,
        "net_income": ni_a.get("val") if ni_a else None,
        "assets": assets_a.get("val") if assets_a else None,
        "eps_diluted": eps_a.get("val") if eps_a else None,
        "shares_out": shares_a.get("val") if shares_a else None,
        "revenue_prior": revenue_prior,
        "revenue_yoy": revenue_yoy,
        "q_end": q_end,
        "q_revenue": q_rev.get("val") if q_rev else None,
        "q_net_income": q_ni.get("val") if q_ni else None,
        "latest_form": latest_form,
    }
    # nothing worth storing
    if out["revenue"] is None and out["net_income"] is None and out["assets"] is None:
        return None
    return out


def run():
    cfg = load_config()
    init_db()
    fc = cfg.get("fundamentals", {})
    if not fc.get("enabled", True):
        return
    cap = int(fc.get("max_per_run", 60))
    stale_days = int(fc.get("refresh_days", 14))
    sess = common.make_session(cfg)
    sess.headers.update({"User-Agent": SEC_UA, "Accept-Encoding": "gzip, deflate"})
    db = SessionLocal()
    n = 0
    try:
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=stale_days)
        fresh = {
            tk for (tk, up) in db.execute(select(TickerFundamentals.ticker, TickerFundamentals.updated_at)).all()
            if up and up > cutoff
        }
        targets = [
            (tk, str(int(cik)))
            for (tk, cik) in db.execute(select(TickerMeta.ticker, TickerMeta.cik).where(TickerMeta.cik.isnot(None))).all()
            if tk not in fresh
        ][:cap]

        for ticker, cik in targets:
            url = COMPANYFACTS.format(cik=cik.zfill(10))
            try:
                r = sess.get(url, timeout=30)
                if r.status_code != 200:
                    time.sleep(0.15)
                    continue
                parsed = parse_companyfacts(r.json())
            except Exception as e:  # noqa: BLE001
                print(f"fundamentals: {ticker} ({cik}) failed: {e}")
                time.sleep(0.15)
                continue
            if not parsed:
                time.sleep(0.12)
                continue
            db.execute(
                pg_insert(TickerFundamentals)
                .values(
                    ticker=ticker,
                    source_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik.zfill(10)}&type=10-K",
                    updated_at=dt.datetime.now(dt.timezone.utc),
                    **parsed,
                )
                .on_conflict_do_update(
                    index_elements=["ticker"],
                    set_={**parsed, "updated_at": dt.datetime.now(dt.timezone.utc)},
                )
            )
            n += 1
            if n % 25 == 0:
                db.commit()
            time.sleep(0.12)  # stay well under SEC's ~10 req/s
        db.commit()
        common.record_run(db, "fundamentals", rows_upserted=n, success=True)
        print(f"fundamentals: stored {n} company fundamentals")
    except Exception as e:  # noqa: BLE001
        common.record_run(db, "fundamentals", success=False, note=str(e))
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
