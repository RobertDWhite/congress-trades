import bisect
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Member, StrategyRun, TickerBar, TickerMeta, Trade, TradeSignal

router = APIRouter()

_MID = (func.coalesce(Trade.amount_min, 0) + func.coalesce(Trade.amount_max, Trade.amount_min, 0)) / 2.0
_START = dt.date(2023, 1, 1)


class BacktestParams(BaseModel):
    cohort: str = "all"            # all | democrat | republican | member | committee
    member_ids: list[int] | None = None
    committee: str | None = None
    ignore_late: bool = False      # drop trades disclosed >=45 days late
    min_conviction: int = 0        # only trades with conviction >= N
    clusters_only: bool = False    # only cluster-buy trades
    weighting: str = "equal"       # equal | notional


def _close_on(rec, d):
    """Last close on/before d (forward-fill)."""
    dates, closes = rec
    i = bisect.bisect_right(dates, d) - 1
    return closes[i] if i >= 0 else None

DISCLAIMER = (
    "Backtest of publicly-disclosed congressional buys. Each position enters at the first close "
    "ON OR AFTER the public disclosure date (which lags the actual trade up to 45 days), price-return "
    "only (no dividends/fees/slippage), $1 per disclosed buy held to today, benchmarked vs SPY. "
    "Hypothetical, in-sample, single market regime. Not advice; past performance is not predictive."
)


def _row(s, full=False):
    d = {
        "strategy_key": s.strategy_key,
        "label": s.label,
        "total_return": float(s.total_return) if s.total_return is not None else None,
        "cagr": float(s.cagr) if s.cagr is not None else None,
        "max_drawdown": float(s.max_drawdown) if s.max_drawdown is not None else None,
        "excess_vs_spy": float(s.excess_vs_spy) if s.excess_vs_spy is not None else None,
        "n_positions": s.n_positions,
        "generated_at": s.generated_at.isoformat() if s.generated_at else None,
    }
    if full:
        d["equity_curve"] = s.equity_curve or []
        d["holdings"] = s.holdings or []
    return d


@router.get("/strategies")
def list_strategies(db: Session = Depends(get_db)):
    rows = db.scalars(select(StrategyRun).order_by(StrategyRun.excess_vs_spy.desc().nullslast())).all()
    return {"disclaimer": DISCLAIMER, "items": [_row(s) for s in rows]}


@router.post("/strategies/custom")
def custom_backtest(body: BacktestParams, db: Session = Depends(get_db)):
    """On-the-fly 'follow strategy' backtest: pick a cohort + filters + weighting, benchmark vs SPY.
    Same honest construction as the cached presets — entry at first close on/after disclosure."""
    conds = [Trade.transaction_type == "purchase", Trade.ticker.isnot(None), Trade.disclosure_date.isnot(None)]
    if body.cohort in ("democrat", "republican"):
        party = "Democrat" if body.cohort == "democrat" else "Republican"
        conds.append(Trade.member_id.in_(select(Member.id).where(Member.party == party)))
    elif body.cohort == "member" and body.member_ids:
        conds.append(Trade.member_id.in_(body.member_ids[:50]))
    elif body.cohort == "committee" and body.committee:
        ms = db.scalars(select(Member).where(Member.committees.isnot(None))).all()
        ids = [m.id for m in ms if any(body.committee.lower() in (c or "").lower() for c in (m.committees or []))]
        conds.append(Trade.member_id.in_(ids or [-1]))
    if body.ignore_late:
        conds.append((Trade.disclosure_date - Trade.transaction_date) < 45)
    if body.min_conviction > 0:
        conds.append(Trade.id.in_(select(TradeSignal.trade_id).where(
            and_(TradeSignal.signal_type == "conviction", TradeSignal.score >= body.min_conviction))))
    if body.clusters_only:
        conds.append(Trade.id.in_(select(TradeSignal.trade_id).where(TradeSignal.signal_type == "cluster_buy")))

    rows = db.execute(
        select(Trade.ticker, Trade.disclosure_date, Trade.entry_price, _MID).where(and_(*conds)).limit(8000)
    ).all()
    tickers = {r[0] for r in rows} | {"SPY"}
    bars = {}
    for tk, d, c in db.execute(
        select(TickerBar.ticker, TickerBar.bar_date, TickerBar.close)
        .where(TickerBar.ticker.in_(tickers)).order_by(TickerBar.ticker, TickerBar.bar_date)
    ):
        b = bars.setdefault(tk, ([], []))
        b[0].append(d)
        b[1].append(float(c))

    positions = []
    for tk, dd, ep, mid in rows:
        rec = bars.get(tk)
        price = float(ep) if ep is not None else (_close_on(rec, dd) if rec else None)
        if price and price > 0 and rec:
            positions.append((tk, dd, price, float(mid or 1)))

    spy = bars.get("SPY")
    today = dt.date.today()
    curve, metrics = [], {}
    if positions and spy:
        start = max(min(p[1] for p in positions), _START)
        grid, d = [], start
        while d <= today:
            grid.append(d)
            d += dt.timedelta(days=7)
        for d in grid:
            num = wsum = snum = 0.0
            for tk, entry, ep, mid in positions:
                if entry > d:
                    continue
                w = 1.0 if body.weighting == "equal" else mid
                px = _close_on(bars[tk], d)
                if not px:
                    continue
                num += w * (px / ep)
                wsum += w
                spx, spe = _close_on(spy, d), _close_on(spy, entry)
                if spx and spe:
                    snum += w * (spx / spe)
            if wsum:
                curve.append([d.isoformat(), round(num / wsum, 4), round(snum / wsum, 4)])
        if curve:
            vals = [c[1] for c in curve]
            peak = vals[0]
            mdd = 0.0
            for v in vals:
                peak = max(peak, v)
                mdd = min(mdd, v / peak - 1)
            last = curve[-1]
            yrs = max((dt.date.fromisoformat(last[0]) - dt.date.fromisoformat(curve[0][0])).days / 365.25, 0.1)
            metrics = {
                "total_return": last[1] - 1,
                "cagr": last[1] ** (1 / yrs) - 1 if last[1] > 0 else None,
                "max_drawdown": mdd,
                "excess_vs_spy": last[1] - last[2],
                "n_positions": len(positions),
            }
    return {"disclaimer": DISCLAIMER, "params": body.model_dump(), "equity_curve": curve, **metrics}


@router.get("/strategies/{key}")
def get_strategy(key: str, db: Session = Depends(get_db)):
    s = db.get(StrategyRun, key)
    if not s:
        raise HTTPException(404, "unknown strategy")
    out = {"disclaimer": DISCLAIMER, **_row(s, full=True)}
    # decorate holdings with sector/company
    tks = [h["ticker"] for h in (s.holdings or [])]
    meta = {m.ticker: m for m in db.scalars(select(TickerMeta).where(TickerMeta.ticker.in_(tks))).all()} if tks else {}
    for h in out["holdings"]:
        m = meta.get(h["ticker"])
        h["sector"] = m.sector if m else None
        h["company"] = m.company if m else None
    return out
