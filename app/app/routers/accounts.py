"""Lightweight, token-based accounts: cloud-sync a prefs blob (watchlist, saved filters, digest
email). No password — the opaque token IS the credential, stored client-side in localStorage."""
import datetime as dt
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import UserAccount

router = APIRouter()


class PrefsIn(BaseModel):
    prefs: dict
    handle: str | None = None


def _serialize(a):
    return {
        "token": a.token, "handle": a.handle, "prefs": a.prefs or {},
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "updated_at": a.updated_at.isoformat() if a.updated_at else None,
    }


@router.post("/accounts")
def create_account(db: Session = Depends(get_db)):
    token = secrets.token_urlsafe(24)
    a = UserAccount(token=token, prefs={}, created_at=dt.datetime.now(dt.timezone.utc))
    db.add(a)
    db.commit()
    return _serialize(a)


@router.get("/accounts/{token}")
def get_account(token: str, db: Session = Depends(get_db)):
    a = db.scalar(select(UserAccount).where(UserAccount.token == token))
    if not a:
        raise HTTPException(404, "account not found")
    return _serialize(a)


@router.put("/accounts/{token}")
def update_account(token: str, body: PrefsIn, db: Session = Depends(get_db)):
    a = db.scalar(select(UserAccount).where(UserAccount.token == token))
    if not a:
        raise HTTPException(404, "account not found")
    a.prefs = body.prefs
    if body.handle is not None:
        a.handle = body.handle[:64]
    a.updated_at = dt.datetime.now(dt.timezone.utc)
    db.commit()
    return _serialize(a)
