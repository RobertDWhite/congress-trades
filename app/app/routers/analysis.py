import datetime as dt
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..enrich import enrich_rows
from ..analysis_scoring import amount_mid, conflict_score, signal_types, unusual_score
from ..models import GovEvent, LegislativeEvent, Member, TickerBar, TickerMeta, Trade, TradeSignal
from ..serialize import member_dict

router = APIRouter()


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


def _sec_event_dict(e):
    return {
        "id": e.id,
        "source": e.source,
        "form": e.form,
        "title": e.title,
        "url": e.url,
        "filed_at": e.filed_at.isoformat() if e.filed_at else None,
    }


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
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=context_days)
    policy_stmt = (
        select(LegislativeEvent, Member)
        .join(Member, Member.id == LegislativeEvent.member_id, isouter=True)
        .where(LegislativeEvent.occurred_at >= since)
    )
    if trade.member_id:
        policy_stmt = policy_stmt.where(LegislativeEvent.member_id == trade.member_id)
    elif trade.ticker:
        meta = db.get(TickerMeta, trade.ticker)
        if meta and meta.sector:
            policy_stmt = policy_stmt.where(LegislativeEvent.sector == meta.sector)
    policy_rows = db.execute(policy_stmt.order_by(LegislativeEvent.occurred_at.desc().nullslast()).limit(25)).all()
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
    return {
        "trade": item,
        "member": member_dict(member) if member else None,
        "policy_context": [_event_dict(e, m) for e, m in policy_rows],
        "sec_events": [_sec_event_dict(e) for e in sec_rows],
        "price_bars": bars,
        "conflict_score": conflict_score(trade, member, signals, policy_rows, sec_rows),
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
