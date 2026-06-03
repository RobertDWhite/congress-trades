import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from .. import conflict
from ..analysis_scoring import signal_types, unusual_score
from ..db import get_db
from ..enrich import enrich_rows
from ..models import (
    EtfHolding,
    GovEvent,
    LegislativeEvent,
    Member,
    TickerBar,
    TickerFundamentals,
    TickerMeta,
    Trade,
    TradeSignal,
)
from ..serialize import member_dict
from .overlays import contracts_for, lobbying_for

router = APIRouter()

# disclosed-volume proxy: sum of per-trade amount-range midpoints
_MIDPOINT = (func.coalesce(Trade.amount_min, 0) + func.coalesce(Trade.amount_max, Trade.amount_min, 0)) / 2.0

# trade.source -> public-facing provenance label for the credibility layer
SOURCE_LABELS = {
    "house_primary": {"label": "House Clerk", "kind": "primary"},
    "senate_primary": {"label": "Senate eFD", "kind": "primary"},
    "lambda": {"label": "Comparison feed", "kind": "comparison"},
}


def _signals_for(db, trade_ids):
    if not trade_ids:
        return {}
    out = {}
    rows = db.execute(
        select(TradeSignal.trade_id, TradeSignal.signal_type, TradeSignal.score, TradeSignal.detail)
        .where(TradeSignal.trade_id.in_(trade_ids))
    ).all()
    for tid, stype, score, detail in rows:
        out.setdefault(tid, []).append({"type": stype, "score": score, "detail": detail or {}})
    return out


def _event_dict(e, member=None):
    return {
        "id": e.id,
        "event_type": e.event_type,
        "title": e.title,
        "url": e.url,
        "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
        "member_id": e.member_id,
        "member": member.full_name if member else None,
        "party": member.party if member else None,
        "sector": e.sector,
        "committee": e.committee,
    }


def _vote_dict(e, member, trade):
    d = _event_dict(e, member)
    ref = trade.transaction_date or trade.disclosure_date
    d["days_from_trade"] = abs((e.occurred_at.date() - ref).days) if (e.occurred_at and ref) else None
    return d


def _sec_event_dict(e):
    return {
        "id": e.id,
        "source": e.source,
        "form": e.form,
        "title": e.title,
        "url": e.url,
        "filed_at": e.filed_at.isoformat() if e.filed_at else None,
    }


def _provenance(trade, has_policy, has_sec):
    """Source/provenance badges for the public credibility layer."""
    src = SOURCE_LABELS.get(trade.source, {"label": trade.source or "unknown", "kind": "other"})
    badges = [{
        "key": "disclosure",
        "label": src["label"],
        "kind": src["kind"],
        "detail": "Primary congressional disclosure" if src["kind"] == "primary" else "Aggregated comparison feed",
        "primary": trade.source in ("house_primary", "senate_primary"),
    }]
    if has_policy:
        badges.append({"key": "congress_gov", "label": "Congress.gov", "kind": "context",
                       "detail": "Bills, votes & committee activity"})
    if has_sec:
        badges.append({"key": "sec_edgar", "label": "SEC EDGAR", "kind": "context",
                       "detail": "Form 4 / 8-K filings & company facts"})
    return badges


def _nearest_on_or_after(bars, iso_date):
    for b in bars:
        if b["date"] >= iso_date:
            return b["close"]
    return None


def _nearest_before(bars, iso_date):
    prev = None
    for b in bars:
        if b["date"] <= iso_date:
            prev = b["close"]
        else:
            break
    return prev


def _pct(now, then):
    if now is None or then in (None, 0):
        return None
    return now / then - 1


def _price_movement(bars, trade, live_price):
    """Price action around the trade: vs the prices on the transaction / disclosure dates,
    plus recent momentum. Uses the live quote when available, else the latest daily close."""
    if not bars:
        return None
    latest = bars[-1]
    latest_close = latest["close"]
    ref = live_price if live_price else latest_close
    tx_iso = trade.transaction_date.isoformat() if trade.transaction_date else None
    disc_iso = trade.disclosure_date.isoformat() if trade.disclosure_date else None
    tx_price = _nearest_on_or_after(bars, tx_iso) if tx_iso else None
    disc_price = _nearest_on_or_after(bars, disc_iso) if disc_iso else None

    def window(days):
        target = (dt.date.fromisoformat(latest["date"]) - dt.timedelta(days=days)).isoformat()
        return _pct(latest_close, _nearest_before(bars, target))

    return {
        "as_of": latest["date"],
        "latest_close": latest_close,
        "tx_price": tx_price,
        "disclosure_price": disc_price,
        "since_transaction_pct": _pct(ref, tx_price),
        "since_disclosure_pct": _pct(ref, disc_price),
        "change_30d": window(30),
        "change_90d": window(90),
    }


def _member_summary(db, member_id):
    lag = Trade.disclosure_date - Trade.transaction_date
    row = db.execute(
        select(
            func.count(Trade.id),
            func.sum(case((Trade.transaction_type == "purchase", 1), else_=0)),
            func.sum(case((Trade.transaction_type == "sale", 1), else_=0)),
            func.avg(lag),
            func.avg(case((lag >= 45, 1.0), else_=0.0)),
            func.coalesce(func.sum(_MIDPOINT), 0),
            func.percentile_cont(0.5).within_group(func.coalesce(Trade.amount_min, 0)),
        ).where(Trade.member_id == member_id)
    ).one()
    return {
        "total_trades": int(row[0] or 0),
        "buys": int(row[1] or 0),
        "sells": int(row[2] or 0),
        "avg_lag_days": float(row[3]) if row[3] is not None else None,
        "pct_late": float(row[4]) if row[4] is not None else None,
        "est_volume": float(row[5] or 0),
        "median_amount": float(row[6]) if row[6] is not None else None,
    }


def _fundamentals_dict(f):
    if not f:
        return None
    return {
        "company": f.company,
        "cik": f.cik,
        "fy": f.fy,
        "fy_end": f.fy_end.isoformat() if f.fy_end else None,
        "revenue": float(f.revenue) if f.revenue is not None else None,
        "net_income": float(f.net_income) if f.net_income is not None else None,
        "assets": float(f.assets) if f.assets is not None else None,
        "eps_diluted": float(f.eps_diluted) if f.eps_diluted is not None else None,
        "shares_out": float(f.shares_out) if f.shares_out is not None else None,
        "revenue_yoy": float(f.revenue_yoy) if f.revenue_yoy is not None else None,
        "q_end": f.q_end.isoformat() if f.q_end else None,
        "q_revenue": float(f.q_revenue) if f.q_revenue is not None else None,
        "latest_form": f.latest_form,
        "source_url": f.source_url,
        "updated_at": f.updated_at.isoformat() if f.updated_at else None,
    }


def _why_notable(components, item, ticker_history, price_movement):
    """Plain-English bullets: the contributing score components, plus a few trade-level facts."""
    bullets = [c["detail"] for c in components if c["points"] > 0]
    ticker = item.get("ticker")
    if any(s.get("type") == "options" for s in (item.get("signals") or [])):
        bullets.append("Disclosed as an options / derivative position.")
    if ticker and not ticker_history:
        bullets.append(f"First disclosed trade in {ticker} by this member.")
    exc = item.get("excess_pct")
    if ticker and exc is not None and abs(exc) >= 0.05:
        verb = "outperformed" if exc > 0 else "underperformed"
        bullets.append(f"Since it could first be acted on, {ticker} {verb} the S&P 500 by {abs(exc) * 100:.0f}%.")
    elif ticker and price_movement and price_movement.get("since_disclosure_pct") is not None and abs(price_movement["since_disclosure_pct"]) >= 0.1:
        m = price_movement["since_disclosure_pct"]
        bullets.append(f"{ticker} is {'up' if m > 0 else 'down'} {abs(m) * 100:.0f}% since disclosure.")
    return bullets[:7]


@router.get("/analysis/trade-dossier/{trade_id}")
def trade_dossier(
    trade_id: int,
    db: Session = Depends(get_db),
    context_days: int = Query(120, le=730),
    price_days: int = Query(180, le=1825),
):
    row = db.execute(
        select(Trade, Member)
        .join(Member, Member.id == Trade.member_id, isouter=True)
        .where(Trade.id == trade_id)
    ).one_or_none()
    if not row:
        raise HTTPException(404, "trade not found")
    trade, member = row
    item = enrich_rows(db, [row])[0]
    signals = _signals_for(db, [trade.id]).get(trade.id, [])

    ticker_sector = None
    fundamentals = None
    if trade.ticker:
        meta = db.get(TickerMeta, trade.ticker)
        ticker_sector = meta.sector if meta else None
        fundamentals = db.get(TickerFundamentals, trade.ticker)

    # fundamentals + derived valuation (market cap, P/E) from the latest price
    fund_dict = _fundamentals_dict(fundamentals)
    if fund_dict:
        px = item.get("live_price") or item.get("price")
        if px and fund_dict.get("shares_out"):
            fund_dict["market_cap"] = px * fund_dict["shares_out"]
        if px and fund_dict.get("eps_diluted") and fund_dict["eps_diluted"] > 0:
            fund_dict["pe_ratio"] = round(px / fund_dict["eps_diluted"], 1)

    # nearby Congress.gov activity: member-scoped when known, else sector-scoped
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=context_days)
    policy_stmt = (
        select(LegislativeEvent, Member)
        .join(Member, Member.id == LegislativeEvent.member_id, isouter=True)
        .where(LegislativeEvent.occurred_at >= since)
    )
    if trade.member_id:
        policy_stmt = policy_stmt.where(LegislativeEvent.member_id == trade.member_id)
    elif ticker_sector:
        policy_stmt = policy_stmt.where(LegislativeEvent.sector == ticker_sector)
    policy_rows = db.execute(policy_stmt.order_by(LegislativeEvent.occurred_at.desc().nullslast()).limit(40)).all()

    sec_rows = []
    if trade.ticker:
        sec_rows = db.scalars(
            select(GovEvent)
            .where(GovEvent.ticker == trade.ticker)
            .order_by(GovEvent.filed_at.desc().nullslast())
            .limit(25)
        ).all()

    bars = []
    if trade.ticker:
        since_date = dt.date.today() - dt.timedelta(days=price_days)
        bars = [
            {"date": d.isoformat(), "close": float(c)}
            for d, c in db.execute(
                select(TickerBar.bar_date, TickerBar.close)
                .where(and_(TickerBar.ticker == trade.ticker, TickerBar.bar_date >= since_date))
                .order_by(TickerBar.bar_date)
            ).all()
        ]

    member_summary = None
    member_median = None
    ticker_history = []
    if trade.member_id:
        member_summary = _member_summary(db, trade.member_id)
        member_median = member_summary.get("median_amount")
        if trade.ticker:
            hist = db.scalars(
                select(Trade)
                .where(and_(Trade.member_id == trade.member_id, Trade.ticker == trade.ticker, Trade.id != trade.id))
                .order_by(Trade.transaction_date.desc().nullslast(), Trade.id.desc())
                .limit(20)
            ).all()
            ticker_history = enrich_rows(db, [(t, member) for t in hist])

    facts = conflict.gather_facts(
        trade, member,
        ticker_sector=ticker_sector,
        signals=signals,
        policy_rows=policy_rows,
        sec_rows=sec_rows,
        member_median=member_median,
        fundamentals=fund_dict,
    )
    score = conflict.score_components(facts)
    price_movement = _price_movement(bars, trade, item.get("live_price"))

    votes = [_vote_dict(e, m, trade) for e, m in policy_rows if (e.event_type or "") == "member_house_vote"]
    other_policy = [_event_dict(e, m) for e, m in policy_rows if (e.event_type or "") != "member_house_vote"]

    committee_ties = {
        "committees": (member.committees if member else None) or [],
        "committee_sectors": (member.committee_sectors if member else None) or [],
        "ticker_sector": ticker_sector,
        "overlap": bool(ticker_sector and member and ticker_sector in (member.committee_sectors or [])),
    }

    # free public-data overlays
    contracts = lobbying_records = []
    etf_membership = []
    if trade.ticker:
        contracts = contracts_for(db, trade.ticker, limit=8)
        lobbying_records = lobbying_for(db, trade.ticker, limit=8)
        etf_membership = [
            {"etf": h.etf, "weight": float(h.weight) if h.weight is not None else None}
            for h in db.scalars(select(EtfHolding).where(EtfHolding.ticker == trade.ticker)).all()
        ]

    why = _why_notable(score["components"], item, ticker_history, price_movement)
    company = (fundamentals.company if fundamentals else None) or trade.ticker
    if contracts:
        total_award = sum(c["amount"] or 0 for c in contracts)
        if total_award > 0:
            why.append(f"{company} is a federal contractor (~{conflict._money(total_award)} in tracked awards).")
    if lobbying_records:
        why.append(f"{company} lobbies Congress ({len(lobbying_records)} recent disclosure filing(s)).")
    if etf_membership:
        why.append("Held by " + ", ".join(sorted({h['etf'] for h in etf_membership})) + " (a congress-tracking ETF).")
    why = why[:8]

    provenance = _provenance(trade, bool(votes or other_policy), bool(sec_rows or fundamentals))
    if contracts:
        provenance.append({"key": "usaspending", "label": "USASpending", "kind": "context", "detail": "Federal award data"})
    if lobbying_records:
        provenance.append({"key": "lda", "label": "Senate LDA", "kind": "context", "detail": "Lobbying disclosures"})

    return {
        "trade": item,
        "member": {**member_dict(member), **(member_summary or {})} if member else None,
        "member_ticker_history": ticker_history,
        "committee_ties": committee_ties,
        "vote_context": votes,
        "policy_context": other_policy,
        "sec_events": [_sec_event_dict(e) for e in sec_rows],
        "fundamentals": fund_dict,
        "federal_contracts": contracts,
        "lobbying": lobbying_records,
        "etf_membership": etf_membership,
        "price_bars": bars,
        "price_movement": price_movement,
        "conflict_score": score,
        "why_notable": why,
        "provenance": provenance,
        "disclaimer": "Context only; not investment advice and not evidence of causality or misconduct.",
    }


@router.get("/analysis/unusual-activity")
def unusual_activity(
    db: Session = Depends(get_db),
    days: int = Query(90, le=3650),
    ticker: str | None = None,
    party: str | None = None,
    chamber: str | None = None,
    limit: int = Query(50, le=200),
):
    since = dt.date.today() - dt.timedelta(days=days)
    stmt = select(Trade, Member).join(Member, Member.id == Trade.member_id, isouter=True).where(Trade.disclosure_date >= since)
    if ticker:
        stmt = stmt.where(Trade.ticker == ticker.upper())
    if party:
        stmt = stmt.where(Member.party == party)
    if chamber:
        stmt = stmt.where(Trade.chamber == chamber)
    rows = db.execute(stmt.order_by(Trade.disclosure_date.desc().nullslast(), Trade.id.desc()).limit(300)).all()
    signals = _signals_for(db, [t.id for t, _ in rows])
    history_cache = {}
    enriched_by_id = {r["id"]: r for r in enrich_rows(db, rows)}
    ranked = []
    for trade, member in rows:
        history = []
        if trade.member_id:
            if trade.member_id not in history_cache:
                history_cache[trade.member_id] = db.scalars(
                    select(Trade).where(Trade.member_id == trade.member_id).order_by(Trade.transaction_date.desc().nullslast()).limit(200)
                ).all()
            history = history_cache[trade.member_id]
        unusual = unusual_score(trade, signals.get(trade.id, []), history)
        if unusual["score"] <= 0:
            continue
        ranked.append({
            "unusual_score": unusual["score"],
            "reasons": unusual["reasons"],
            "trade": enriched_by_id.get(trade.id),
        })
    ranked.sort(key=lambda x: x["unusual_score"], reverse=True)
    return {
        "window_days": days,
        "items": ranked[:limit],
        "disclaimer": "Unusual means worth researching; it does not imply misconduct or investment merit.",
    }


@router.get("/analysis/alert-candidates")
def alert_candidates(
    db: Session = Depends(get_db),
    days: int = Query(90, le=3650),
    ticker: str | None = None,
    member_id: int | None = None,
    min_conviction: int = Query(50, le=100),
    limit: int = Query(50, le=200),
):
    since = dt.date.today() - dt.timedelta(days=days)
    stmt = select(Trade, Member).join(Member, Member.id == Trade.member_id, isouter=True).where(Trade.disclosure_date >= since)
    if ticker:
        stmt = stmt.where(Trade.ticker == ticker.upper())
    if member_id:
        stmt = stmt.where(Trade.member_id == member_id)
    rows = db.execute(stmt.order_by(Trade.disclosure_date.desc().nullslast(), Trade.id.desc()).limit(300)).all()
    signals = _signals_for(db, [t.id for t, _ in rows])
    enriched_by_id = {r["id"]: r for r in enrich_rows(db, rows)}
    out = []
    for trade, _ in rows:
        sigs = signals.get(trade.id, [])
        types = signal_types(sigs)
        reasons = []
        conviction = next((s for s in sigs if s.get("type") == "conviction"), None)
        if conviction and int(conviction.get("score") or 0) >= min_conviction:
            reasons.append(f"conviction {conviction.get('score')}")
        for stype in ("late_disclosure", "corp_event", "legislative_context", "conflict", "cluster_buy", "cluster_sell"):
            if stype in types:
                reasons.append(stype.replace("_", " "))
        if ticker and trade.ticker == ticker.upper():
            reasons.append(f"watched ticker {ticker.upper()}")
        if member_id and trade.member_id == member_id:
            reasons.append(f"watched member {member_id}")
        if reasons:
            out.append({"reasons": reasons, "trade": enriched_by_id.get(trade.id)})
    return {"window_days": days, "items": out[:limit]}


@router.get("/analysis/prescience")
def prescience(
    db: Session = Depends(get_db),
    days: int = Query(1095, le=3650),
    min_trades: int = Query(8, ge=3),
    limit: int = Query(40, le=200),
):
    """Members whose purchases were most often shortly followed by an SEC 8-K AND beat the market.
    Timing only — NOT evidence of trading on nonpublic information; disclosed trades are legal."""
    since = dt.date.today() - dt.timedelta(days=days)
    corp_ids = select(TradeSignal.trade_id).where(TradeSignal.signal_type == "corp_event")
    excess = Trade.return_pct - Trade.bench_return_pct
    total = func.count(Trade.id)
    corp = func.sum(case((Trade.id.in_(corp_ids), 1), else_=0))
    well = func.sum(case((and_(Trade.id.in_(corp_ids), excess > 0), 1), else_=0))
    rows = db.execute(
        select(Member, total, corp, well, func.avg(excess))
        .join(Trade, Trade.member_id == Member.id)
        .where(and_(Trade.transaction_type == "purchase", Trade.disclosure_date >= since))
        .group_by(Member.id)
        .having(and_(total >= min_trades, well > 0))
        .order_by(well.desc(), corp.desc())
        .limit(limit)
    ).all()
    return {
        "window_days": days,
        "note": "Share of a member's purchases shortly followed by an SEC 8-K that also beat the S&P 500. "
                "Timing/coincidence only — disclosed trades are legal and this is NOT evidence of wrongdoing.",
        "items": [
            {
                **member_dict(m, int(t or 0)),
                "corp_event_buys": int(c or 0),
                "well_timed": int(w or 0),
                "prescience_rate": (float(w or 0) / float(t)) if t else 0.0,
                "avg_excess_pct": float(a) if a is not None else None,
            }
            for m, t, c, w, a in rows
        ],
    }
