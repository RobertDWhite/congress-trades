"""User-configurable alert rules: CRUD + a live preview of which recent trades a rule would match.
Delivery to channels happens in the alerts_dispatch cron job."""
import datetime as dt
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, delete, select
from sqlalchemy.orm import Session

from ..alerts_engine import RULE_TYPES, rule_matches
from ..db import get_db
from ..enrich import enrich_rows
from ..models import AlertRule, Member, TickerMeta, Trade, TradeSignal

router = APIRouter()
READONLY = os.environ.get("PUBLIC_READONLY", "").lower() in ("1", "true", "yes")


def _guard():
    if READONLY:
        raise HTTPException(403, "read-only mode")


class AlertRuleIn(BaseModel):
    name: str
    rule_type: str
    params: dict | None = None
    channels: list | None = None
    enabled: bool = True
    account_token: str | None = None


def _serialize(r):
    return {
        "id": r.id, "name": r.name, "rule_type": r.rule_type, "params": r.params or {},
        "channels": r.channels or [], "enabled": r.enabled,
        "last_fired_at": r.last_fired_at.isoformat() if r.last_fired_at else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("/alerts")
def list_rules(db: Session = Depends(get_db), account_token: str | None = None):
    stmt = select(AlertRule).order_by(AlertRule.created_at.desc())
    if account_token:
        stmt = stmt.where(AlertRule.account_token == account_token)
    return {"rule_types": list(RULE_TYPES), "items": [_serialize(r) for r in db.scalars(stmt).all()]}


@router.post("/alerts")
def create_rule(body: AlertRuleIn, db: Session = Depends(get_db)):
    _guard()
    if body.rule_type not in RULE_TYPES:
        raise HTTPException(400, f"rule_type must be one of {RULE_TYPES}")
    r = AlertRule(
        name=body.name[:128], rule_type=body.rule_type, params=body.params or {},
        channels=body.channels or [], enabled=body.enabled, account_token=body.account_token,
    )
    db.add(r)
    db.commit()
    return _serialize(r)


@router.patch("/alerts/{rule_id}")
def update_rule(rule_id: int, body: AlertRuleIn, db: Session = Depends(get_db)):
    _guard()
    r = db.get(AlertRule, rule_id)
    if not r:
        raise HTTPException(404, "rule not found")
    r.name = body.name[:128]
    r.rule_type = body.rule_type
    r.params = body.params or {}
    r.channels = body.channels or []
    r.enabled = body.enabled
    db.commit()
    return _serialize(r)


@router.delete("/alerts/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    _guard()
    db.execute(delete(AlertRule).where(AlertRule.id == rule_id))
    db.commit()
    return {"status": "removed"}


@router.get("/alerts/preview")
def preview(
    db: Session = Depends(get_db),
    rule_type: str = Query(...),
    days: int = Query(90, le=730),
    member_id: int | None = None,
    ticker: str | None = None,
    sector: str | None = None,
    min_amount: int | None = None,
    min_lag: int | None = None,
    limit: int = Query(50, le=200),
):
    """Show which recent trades a candidate rule would have matched (no rule is saved)."""
    if rule_type not in RULE_TYPES:
        raise HTTPException(400, f"rule_type must be one of {RULE_TYPES}")
    params = {k: v for k, v in
              {"member_id": member_id, "ticker": ticker, "sector": sector, "min_amount": min_amount, "min_lag": min_lag}.items()
              if v is not None}
    since = dt.date.today() - dt.timedelta(days=days)
    rows = db.execute(
        select(Trade, Member).join(Member, Member.id == Trade.member_id, isouter=True)
        .where(Trade.disclosure_date >= since)
        .order_by(Trade.disclosure_date.desc().nullslast(), Trade.id.desc())
        .limit(400)
    ).all()
    ids = [t.id for t, _ in rows]
    sig_by_trade = {}
    if ids:
        for tid, stype in db.execute(
            select(TradeSignal.trade_id, TradeSignal.signal_type).where(TradeSignal.trade_id.in_(ids))
        ).all():
            sig_by_trade.setdefault(tid, set()).add(stype)
    tks = {t.ticker for t, _ in rows if t.ticker}
    sector_by_ticker = dict(
        db.execute(select(TickerMeta.ticker, TickerMeta.sector).where(TickerMeta.ticker.in_(tks))).all()
    ) if tks else {}

    matched_rows, reasons = [], {}
    for t, m in rows:
        lag = (t.disclosure_date - t.transaction_date).days if (t.disclosure_date and t.transaction_date) else None
        ctx = {
            "member_id": t.member_id, "ticker": t.ticker, "sector": sector_by_ticker.get(t.ticker),
            "amount_min": t.amount_min, "amount_max": t.amount_max, "lag_days": lag,
            "option_type": t.option_type, "signal_types": sig_by_trade.get(t.id, set()),
        }
        ok, reason = rule_matches(rule_type, params, ctx)
        if ok:
            matched_rows.append((t, m))
            reasons[t.id] = reason
        if len(matched_rows) >= limit:
            break
    enriched = enrich_rows(db, matched_rows)
    for e in enriched:
        e["alert_reason"] = reasons.get(e["id"])
    return {"rule_type": rule_type, "params": params, "match_count": len(enriched), "items": enriched}
