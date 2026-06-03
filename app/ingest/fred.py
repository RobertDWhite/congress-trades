"""FRED macro context (free API key) — latest value + prior for a handful of series the UI shows
next to trading activity: Fed funds rate, CPI, unemployment, 10y/2y Treasury yields.
Set FRED_API_KEY; the job no-ops cleanly without it.
"""
import datetime as dt
import os

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import load_config
from app.db import SessionLocal, init_db
from app.models import MacroSeries

from . import common

OBS_URL = "https://api.stlouisfed.org/fred/series/observations"
SERIES_URL = "https://api.stlouisfed.org/fred/series"

DEFAULT_SERIES = {
    "FEDFUNDS": "Fed Funds Rate",
    "CPIAUCSL": "CPI (All Urban)",
    "UNRATE": "Unemployment Rate",
    "DGS10": "10-Year Treasury Yield",
    "DGS2": "2-Year Treasury Yield",
}


def run():
    cfg = load_config()
    init_db()
    fc = cfg.get("fred", {})
    key = os.environ.get("FRED_API_KEY") or fc.get("api_key")
    if not fc.get("enabled", True) or not key:
        print("fred: no FRED_API_KEY configured; skipping")
        return
    series = fc.get("series") or DEFAULT_SERIES
    sess = common.make_session(cfg)
    db = SessionLocal()
    n = 0
    try:
        for sid, title in series.items():
            try:
                r = sess.get(OBS_URL, params={
                    "series_id": sid, "api_key": key, "file_type": "json",
                    "sort_order": "desc", "limit": 2,
                }, timeout=30)
                if r.status_code != 200:
                    print(f"fred: {sid} HTTP {r.status_code}")
                    continue
                obs = [o for o in r.json().get("observations", []) if o.get("value") not in (".", None, "")]
                if not obs:
                    continue
                latest = obs[0]
                prev = obs[1] if len(obs) > 1 else {}
                units = None
                try:
                    sr = sess.get(SERIES_URL, params={"series_id": sid, "api_key": key, "file_type": "json"}, timeout=20)
                    if sr.status_code == 200:
                        meta = (sr.json().get("seriess") or [{}])[0]
                        units = meta.get("units_short") or meta.get("units")
                except Exception:  # noqa: BLE001
                    pass
                as_of = None
                try:
                    as_of = dt.date.fromisoformat(latest["date"])
                except (ValueError, KeyError):
                    pass
                db.execute(
                    pg_insert(MacroSeries)
                    .values(series_id=sid, title=title, value=float(latest["value"]),
                            prev_value=float(prev["value"]) if prev.get("value") else None,
                            units=units, as_of=as_of, updated_at=dt.datetime.now(dt.timezone.utc))
                    .on_conflict_do_update(
                        index_elements=["series_id"],
                        set_={"title": title, "value": float(latest["value"]),
                              "prev_value": float(prev["value"]) if prev.get("value") else None,
                              "units": units, "as_of": as_of, "updated_at": dt.datetime.now(dt.timezone.utc)},
                    )
                )
                n += 1
            except Exception as e:  # noqa: BLE001
                print(f"fred: {sid} failed: {e}")
        db.commit()
        common.record_run(db, "fred", rows_upserted=n, success=True)
        print(f"fred: stored {n} macro series")
    except Exception as e:  # noqa: BLE001
        common.record_run(db, "fred", success=False, note=str(e))
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
