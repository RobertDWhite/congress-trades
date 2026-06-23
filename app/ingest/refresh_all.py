"""Consolidated daily refresh: run every ingest step in dependency order as one sweep.

Each `ingest.*` module also runs on its own k8s CronJob for near-real-time freshness;
this chains them into a single ordered pass so the 8am (America/New_York) CronJob can
guarantee a fully refreshed dataset to start the day.

A step that raises is logged and the sweep continues — one failing source must not abort
the rest. The process exits non-zero if any step failed so the Job is marked failed and
shows up in cron history/alerts.
"""
import importlib
import sys
import time
import traceback

# Module name -> note, in dependency order. Mirrors the per-source CronJobs in
# whitehouse-rke2 apps/data/congress-trades (50-66), chained into one pass:
# raw trades -> normalization -> member enrichment -> market data -> external
# context -> derived analytics -> AI -> QA.
STEPS = [
    "house",           # House PTR disclosures (raw trades)
    "senate",          # Senate PTR disclosures (raw trades)
    "president",        # Presidential OGE 278-T disclosures (raw trades)
    "lambda_feed",     # safety-net / cross-check feed
    "ticker_aliases",  # normalize null-ticker trades from fresh data
    "enrich",          # member party / state / district
    "networth",        # annual FD net-worth estimates
    "sectors",         # SEC sector tagging
    "prices",          # daily price bars (powers returns / backtest)
    "quotes",          # latest quotes
    "gov_events",      # SEC 8-K events
    "legislative",     # Congress.gov context
    "sentiment",       # StockTwits sentiment
    "signals",         # signal scoring + alerts (needs trades)
    "returns",         # follower returns vs SPY (needs prices)
    "backtest",        # follow-strategy backtests (needs prices)
    "ai_summarize",    # AI summaries (needs the above)
    "reconcile",       # feed-quality QA (last)
]


def run():
    failures = []
    for name in STEPS:
        started = time.monotonic()
        print(f"refresh_all: ===> {name} start", flush=True)
        try:
            importlib.import_module(f"ingest.{name}").run()
            print(f"refresh_all: <=== {name} ok ({time.monotonic() - started:.1f}s)", flush=True)
        except Exception:  # noqa: BLE001 — one failing source must not abort the sweep
            failures.append(name)
            print(f"refresh_all: !!! {name} FAILED ({time.monotonic() - started:.1f}s)", flush=True)
            traceback.print_exc()
    if failures:
        print(f"refresh_all: completed with {len(failures)} failure(s): {', '.join(failures)}", flush=True)
        sys.exit(1)
    print(f"refresh_all: all {len(STEPS)} steps ok", flush=True)


if __name__ == "__main__":
    run()
