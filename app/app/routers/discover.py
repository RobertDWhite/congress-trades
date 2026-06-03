"""Discovery surfaces that mine data already in the DB but had no home:
options activity (with moneyness), brand-new positions, sector rotation over time,
and owner/spouse breakdowns. All views of lagged, already-disclosed data — informational only."""
import datetime as dt

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, case, exists, func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..enrich import enrich_rows
from ..models import Member, TickerMeta, TickerPrice, TickerQuote, Trade

router = APIRouter()

_MID = (func.coalesce(Trade.amount_min, 0) + func.coalesce(Trade.amount_max, Trade.amount_min, 0)) / 2.0


@router.get("/discover/options")
def options_activity(
    db: Session = Depends(get_db),
    days: int = Query(180, le=730),
    member_id: int | None = None,
    limit: int = Query(100, le=300),
):
    """Disclosed options/derivative trades with moneyness (strike vs latest price)."""
    since = dt.date.today() - dt.timedelta(days=days)
    conds = [Trade.option_type.isnot(None), Trade.disclosure_date >= since]
    if member_id:
        conds.append(Trade.member_id == member_id)
    rows = db.execute(
        select(Trade, Member)
        .join(Member, Member.id == Trade.member_id, isouter=True)
        .where(and_(*conds))
        .order_by(Trade.disclosure_date.desc().nullslast(), Trade.id.desc())
        .limit(limit)
    ).all()
    enriched = {r["id"]: r for r in enrich_rows(db, rows)}

    # latest price per ticker for moneyness
    tks = {t.ticker for t, _ in rows if t.ticker}
    price = {}
    if tks:
        for tk, c in db.execute(select(TickerPrice.ticker, TickerPrice.close).where(TickerPrice.ticker.in_(tks))).all():
            price[tk] = float(c) if c is not None else None
        for tk, last in db.execute(select(TickerQuote.ticker, TickerQuote.last).where(TickerQuote.ticker.in_(tks))).all():
            if last is not None:
                price[tk] = float(last)

    calls = puts = 0
    items = []
    for t, _m in rows:
        otype = (t.option_type or "").lower()
        if otype == "call":
            calls += 1
        elif otype == "put":
            puts += 1
        strike = float(t.option_strike) if t.option_strike is not None else None
        px = price.get(t.ticker)
        moneyness = None
        if strike and px:
            if otype == "call":
                moneyness = "ITM" if px > strike else "OTM"
            elif otype == "put":
                moneyness = "ITM" if px < strike else "OTM"
        item = enriched.get(t.id, {})
        items.append({
            **item,
            "option_type": otype or None,
            "strike": strike,
            "expiration": t.option_expiration.isoformat() if t.option_expiration else None,
            "underlying_price": px,
            "moneyness": moneyness,
        })

    # most active members in options
    by_member = db.execute(
        select(Member.id, Member.full_name, Member.party, func.count())
        .join(Trade, Trade.member_id == Member.id)
        .where(and_(Trade.option_type.isnot(None), Trade.disclosure_date >= since))
        .group_by(Member.id)
        .order_by(func.count().desc())
        .limit(12)
    ).all()
    return {
        "window_days": days,
        "calls": calls,
        "puts": puts,
        "top_members": [{"member_id": mid, "member": nm, "party": p, "count": int(c or 0)} for mid, nm, p, c in by_member],
        "items": items,
        "disclaimer": "Disclosed options positions are leveraged directional bets; informational only, not advice.",
    }


@router.get("/discover/new-positions")
def new_positions(
    db: Session = Depends(get_db),
    days: int = Query(30, le=365),
    party: str | None = None,
    chamber: str | None = None,
    limit: int = Query(100, le=300),
):
    """First-ever disclosed purchase of a ticker by a member (a brand-new position)."""
    since = dt.date.today() - dt.timedelta(days=days)
    T2 = Trade.__table__.alias("t2")
    earlier = exists().where(
        and_(
            T2.c.member_id == Trade.member_id,
            T2.c.ticker == Trade.ticker,
            T2.c.id != Trade.id,
            T2.c.transaction_date < Trade.transaction_date,
        )
    )
    conds = [
        Trade.transaction_type == "purchase",
        Trade.ticker.isnot(None),
        Trade.transaction_date.isnot(None),
        Trade.disclosure_date >= since,
        ~earlier,
    ]
    if party:
        conds.append(Member.party == party)
    if chamber:
        conds.append(Trade.chamber == chamber)
    rows = db.execute(
        select(Trade, Member)
        .join(Member, Member.id == Trade.member_id, isouter=True)
        .where(and_(*conds))
        .order_by(Trade.disclosure_date.desc().nullslast(), _MID.desc())
        .limit(limit)
    ).all()
    return {
        "window_days": days,
        "items": enrich_rows(db, rows),
        "disclaimer": "A member's first disclosed buy of a ticker. Informational only, lagged up to 45 days.",
    }


@router.get("/discover/sector-rotation")
def sector_rotation(db: Session = Depends(get_db), days: int = Query(365, le=1095)):
    """Net buy/sell pressure by sector by month — see Congress rotate between sectors."""
    since = dt.date.today() - dt.timedelta(days=days)
    month = func.to_char(func.date_trunc("month", Trade.disclosure_date), "YYYY-MM")
    net = func.sum(case((Trade.transaction_type == "purchase", _MID), (Trade.transaction_type == "sale", -_MID), else_=0))
    rows = db.execute(
        select(
            month.label("m"),
            func.coalesce(TickerMeta.sector, "Unknown"),
            net,
            func.sum(case((Trade.transaction_type == "purchase", 1), else_=0)),
            func.sum(case((Trade.transaction_type == "sale", 1), else_=0)),
        )
        .join(TickerMeta, TickerMeta.ticker == Trade.ticker, isouter=True)
        .where(and_(Trade.disclosure_date >= since, Trade.ticker.isnot(None)))
        .group_by(month, func.coalesce(TickerMeta.sector, "Unknown"))
        .order_by(month)
    ).all()
    months, sectors, cells = [], set(), {}
    for m, sec, n, b, s in rows:
        if not m:
            continue
        if m not in months:
            months.append(m)
        sectors.add(sec)
        cells[(m, sec)] = {"net": float(n or 0), "buys": int(b or 0), "sells": int(s or 0)}
    sector_list = sorted(sectors)
    matrix = [
        {"sector": sec, "cells": [{"month": m, **cells.get((m, sec), {"net": 0.0, "buys": 0, "sells": 0})} for m in months]}
        for sec in sector_list
    ]
    return {"months": months, "sectors": sector_list, "matrix": matrix}


@router.get("/discover/owners")
def owners(db: Session = Depends(get_db), days: int = Query(365, le=1825), limit: int = Query(80, le=300)):
    """Breakdown by reported owner (self / spouse / dependent / joint) + recent non-self trades."""
    since = dt.date.today() - dt.timedelta(days=days)
    breakdown = [
        {"owner": (o or "unspecified"), "count": int(c or 0), "volume": float(v or 0)}
        for o, c, v in db.execute(
            select(func.coalesce(Trade.owner, "unspecified"), func.count(), func.coalesce(func.sum(_MID), 0))
            .where(Trade.disclosure_date >= since)
            .group_by(Trade.owner)
            .order_by(func.count().desc())
        ).all()
    ]
    # trades explicitly attributed to someone other than the member
    non_self = func.lower(func.coalesce(Trade.owner, ""))
    rows = db.execute(
        select(Trade, Member)
        .join(Member, Member.id == Trade.member_id, isouter=True)
        .where(and_(Trade.disclosure_date >= since, non_self.in_(["spouse", "sp", "dependent", "dc", "joint", "jt", "child"])))
        .order_by(Trade.disclosure_date.desc().nullslast(), _MID.desc())
        .limit(limit)
    ).all()
    return {"window_days": days, "breakdown": breakdown, "non_self_trades": enrich_rows(db, rows)}
