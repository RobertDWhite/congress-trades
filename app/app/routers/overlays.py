"""Free public-data overlays: federal contracts (USASpending), lobbying (Senate LDA),
congress-ETF holdings (NANC/KRUZ), FRED macro context, and GDELT news context."""
import datetime as dt

import requests
from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import EtfHolding, GovContract, LobbyingRecord, MacroSeries, TickerMeta, Trade

router = APIRouter()

_MID = (func.coalesce(Trade.amount_min, 0) + func.coalesce(Trade.amount_max, Trade.amount_min, 0)) / 2.0


def contracts_for(db, ticker, limit=15):
    rows = db.scalars(
        select(GovContract).where(GovContract.ticker == ticker.upper())
        .order_by(GovContract.award_amount.desc().nullslast()).limit(limit)
    ).all()
    return [{
        "award_id": c.award_id, "recipient": c.recipient_name, "agency": c.awarding_agency,
        "type": c.award_type, "amount": float(c.award_amount) if c.award_amount is not None else None,
        "action_date": c.action_date.isoformat() if c.action_date else None,
        "description": c.description, "url": c.url,
    } for c in rows]


def lobbying_for(db, ticker, limit=15):
    rows = db.scalars(
        select(LobbyingRecord).where(LobbyingRecord.ticker == ticker.upper())
        .order_by(LobbyingRecord.year.desc().nullslast(), LobbyingRecord.amount.desc().nullslast()).limit(limit)
    ).all()
    return [{
        "client": r.client_name, "registrant": r.registrant_name,
        "amount": float(r.amount) if r.amount is not None else None,
        "year": r.year, "period": r.period, "issues": r.issues or [], "url": r.url,
    } for r in rows]


@router.get("/overlays/contracts/{ticker}")
def contracts(ticker: str, db: Session = Depends(get_db), limit: int = Query(15, le=50)):
    items = contracts_for(db, ticker, limit)
    total = db.scalar(select(func.coalesce(func.sum(GovContract.award_amount), 0)).where(GovContract.ticker == ticker.upper()))
    return {"ticker": ticker.upper(), "total_awarded": float(total or 0), "items": items,
            "source": "USASpending.gov", "disclaimer": "Federal awards are public; proximity to a trade is context, not causation."}


@router.get("/overlays/lobbying/{ticker}")
def lobbying(ticker: str, db: Session = Depends(get_db), limit: int = Query(15, le=50)):
    return {"ticker": ticker.upper(), "items": lobbying_for(db, ticker, limit), "source": "Senate LDA"}


@router.get("/overlays/etf")
def etf_overlap(db: Session = Depends(get_db), days: int = Query(90, le=365), limit: int = Query(50, le=200)):
    """Congress-ETF holdings (NANC/KRUZ) cross-referenced with our recent net-accumulation basket."""
    since = dt.date.today() - dt.timedelta(days=days)
    net = func.sum(case((Trade.transaction_type == "purchase", _MID), (Trade.transaction_type == "sale", -_MID), else_=0))
    accumulation = dict(
        db.execute(
            select(Trade.ticker, net)
            .where(and_(Trade.ticker.isnot(None), Trade.disclosure_date >= since))
            .group_by(Trade.ticker).having(net > 0)
        ).all()
    )
    rows = db.scalars(select(EtfHolding).order_by(EtfHolding.weight.desc().nullslast()).limit(limit * 2)).all()
    by_etf = {}
    for h in rows:
        by_etf.setdefault(h.etf, []).append({
            "ticker": h.ticker, "company": h.company,
            "weight": float(h.weight) if h.weight is not None else None,
            "in_recent_accumulation": h.ticker in accumulation,
            "net_notional": float(accumulation.get(h.ticker) or 0) if h.ticker in accumulation else None,
        })
    for etf in by_etf:
        by_etf[etf] = by_etf[etf][:limit]
    return {"window_days": days, "etfs": by_etf,
            "note": "NANC tracks Democratic-member disclosures, KRUZ Republican. Overlap with our own accumulation basket is shown."}


@router.get("/overlays/etf/{ticker}")
def etf_for_ticker(ticker: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(EtfHolding).where(EtfHolding.ticker == ticker.upper())).all()
    return {"ticker": ticker.upper(), "etfs": [
        {"etf": h.etf, "weight": float(h.weight) if h.weight is not None else None,
         "shares": float(h.shares) if h.shares is not None else None,
         "as_of": h.as_of.isoformat() if h.as_of else None}
        for h in rows
    ]}


@router.get("/macro")
def macro(db: Session = Depends(get_db)):
    rows = db.scalars(select(MacroSeries).order_by(MacroSeries.series_id)).all()
    return {"items": [
        {"series_id": s.series_id, "title": s.title,
         "value": float(s.value) if s.value is not None else None,
         "prev_value": float(s.prev_value) if s.prev_value is not None else None,
         "change": (float(s.value) - float(s.prev_value)) if (s.value is not None and s.prev_value is not None) else None,
         "units": s.units, "as_of": s.as_of.isoformat() if s.as_of else None}
        for s in rows
    ], "source": "FRED (St. Louis Fed)"}


@router.get("/overlays/news/{ticker}")
def news_context(ticker: str, db: Session = Depends(get_db), limit: int = Query(8, le=20)):
    """Contextual news for a traded company via GDELT (free, no key). Clearly labeled as context."""
    meta = db.get(TickerMeta, ticker.upper())
    query = (meta.company if meta and meta.company else ticker.upper())
    out = []
    try:
        r = requests.get(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={"query": f'"{query}"', "mode": "ArtList", "maxrecords": limit, "format": "json", "sort": "DateDesc"},
            headers={"User-Agent": "congress-trades/1.0"}, timeout=12,
        )
        if r.status_code == 200:
            for a in (r.json().get("articles") or [])[:limit]:
                out.append({"title": a.get("title"), "url": a.get("url"), "source": a.get("domain"),
                            "seen": a.get("seendate")})
    except Exception:  # noqa: BLE001
        pass
    return {"ticker": ticker.upper(), "query": query, "items": out,
            "source": "GDELT", "disclaimer": "Contextual news, not affiliated with or endorsed by the member."}
