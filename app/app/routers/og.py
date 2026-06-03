"""Server-rendered Open Graph share cards (1200×630 PNG) for trades and members — the unit that
gets screenshotted/shared. Pillow is imported lazily so the app still boots if it's absent."""
import datetime as dt
import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Member, TickerMeta, Trade

router = APIRouter()

BG = (13, 17, 23)
PANEL = (22, 27, 34)
TEXT = (230, 237, 243)
MUTED = (139, 148, 158)
ACCENT = (88, 166, 255)
BUY = (63, 185, 80)
SELL = (248, 81, 73)
EXCH = (210, 153, 34)
_MID = (func.coalesce(Trade.amount_min, 0) + func.coalesce(Trade.amount_max, Trade.amount_min, 0)) / 2.0


def _png(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "public, max-age=3600"})


def _draw():
    try:
        from PIL import Image, ImageDraw, ImageFont  # noqa
    except ImportError:
        raise HTTPException(503, "image rendering unavailable (Pillow not installed)")
    img = Image.new("RGB", (1200, 630), BG)
    d = ImageDraw.Draw(img)

    def font(size, bold=False):
        for path in (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
        ):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
        return ImageFont.load_default()

    return img, d, font


def _money(n):
    n = float(n or 0)
    if n >= 1e9:
        return f"${n/1e9:.1f}B"
    if n >= 1e6:
        return f"${n/1e6:.1f}M"
    if n >= 1e3:
        return f"${n/1e3:.0f}K"
    return f"${n:.0f}"


@router.get("/og/trade/{trade_id}.png")
def og_trade(trade_id: int, db: Session = Depends(get_db)):
    row = db.execute(
        select(Trade, Member).join(Member, Member.id == Trade.member_id, isouter=True).where(Trade.id == trade_id)
    ).one_or_none()
    if not row:
        raise HTTPException(404, "trade not found")
    t, m = row
    img, d, font = _draw()
    verb = {"purchase": "BOUGHT", "sale": "SOLD", "exchange": "EXCHANGED"}.get(t.transaction_type, "TRADED")
    color = {"purchase": BUY, "sale": SELL, "exchange": EXCH}.get(t.transaction_type, ACCENT)

    d.text((64, 56), "CONGRESS TRADES", font=font(28, True), fill=ACCENT)
    d.text((64, 150), (m.full_name if m else "Unknown Member"), font=font(64, True), fill=TEXT)
    party = f"{(m.party or '')[:1]}-{m.state}" if (m and m.party and m.state) else ""
    if party:
        d.text((64, 226), party, font=font(30), fill=MUTED)

    d.rounded_rectangle((64, 300, 1136, 470), radius=16, fill=PANEL)
    d.text((96, 330), verb, font=font(40, True), fill=color)
    d.text((96, 392), (t.ticker or t.asset_name or "—")[:28], font=font(54, True), fill=TEXT)
    amt = t.amount_range_raw or _money((float(t.amount_min or 0) + float(t.amount_max or t.amount_min or 0)) / 2)
    d.text((620, 392), amt, font=font(38), fill=MUTED)

    lag = (t.disclosure_date - t.transaction_date).days if (t.disclosure_date and t.transaction_date) else None
    foot = f"Traded {t.transaction_date or '?'} · disclosed {t.disclosure_date or '?'}" + (f" · {lag}d lag" if lag is not None else "")
    d.text((64, 520), foot, font=font(26), fill=MUTED)
    d.text((64, 568), "Publicly disclosed under the STOCK Act · informational only", font=font(22), fill=MUTED)
    return _png(img)


@router.get("/og/member/{member_id}.png")
def og_member(member_id: int, db: Session = Depends(get_db)):
    m = db.get(Member, member_id)
    if not m:
        raise HTTPException(404, "member not found")
    n = db.scalar(select(func.count(Trade.id)).where(Trade.member_id == member_id)) or 0
    vol = float(db.scalar(select(func.coalesce(func.sum(_MID), 0)).where(Trade.member_id == member_id)) or 0)
    img, d, font = _draw()
    d.text((64, 56), "CONGRESS TRADES", font=font(28, True), fill=ACCENT)
    d.text((64, 150), m.full_name, font=font(64, True), fill=TEXT)
    sub = " · ".join(x for x in [m.chamber, m.party, m.state] if x)
    d.text((64, 230), sub, font=font(30), fill=MUTED)
    d.rounded_rectangle((64, 320, 1136, 470), radius=16, fill=PANEL)
    d.text((96, 350), "DISCLOSED TRADES", font=font(24, True), fill=MUTED)
    d.text((96, 388), str(n), font=font(56, True), fill=TEXT)
    d.text((560, 350), "EST. VOLUME", font=font(24, True), fill=MUTED)
    d.text((560, 388), _money(vol), font=font(56, True), fill=TEXT)
    d.text((64, 560), "Publicly disclosed under the STOCK Act · informational only", font=font(22), fill=MUTED)
    return _png(img)
