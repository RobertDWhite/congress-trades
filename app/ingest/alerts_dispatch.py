"""Evaluate enabled AlertRules against recently-disclosed trades and deliver matches to each
rule's channels (ntfy / webhook / email). De-duplicated via alert_deliveries (rule_id, trade_id).
Idempotent: a rule never fires twice for the same trade."""
import datetime as dt
import smtplib
import os
from email.message import EmailMessage

import requests
from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.alerts_engine import rule_matches
from app.config import load_config
from app.db import SessionLocal, init_db
from app.models import AlertDelivery, AlertRule, Member, TickerMeta, Trade, TradeSignal

from . import common


def _format(trade, member, reason):
    who = member.full_name if member else "Unknown"
    party = f" ({member.party[0]}-{member.state})" if (member and member.party and member.state) else ""
    direction = (trade.transaction_type or "").upper()
    return (
        f"{who}{party} {direction} {trade.ticker or trade.asset_name or '?'} {trade.amount_range_raw or ''}".strip()
        + f"\nWhy: {reason}"
        + f"\nTraded {trade.transaction_date or '?'} · disclosed {trade.disclosure_date or '?'}"
        + "\nInformational only; public disclosures are delayed and not trading advice."
    )


def _deliver(channel, subject, body, cfg):
    ctype = (channel or {}).get("type")
    target = (channel or {}).get("target")
    if ctype == "ntfy":
        base = cfg.get("alerts", {}).get("ntfy_url", "https://ntfy.sh").rstrip("/")
        url = target if (target or "").startswith("http") else f"{base}/{target or 'congress-trades'}"
        requests.post(url, data=body.encode("utf-8"), headers={"Title": subject}, timeout=15)
        return "sent"
    if ctype == "webhook":
        requests.post(target, json={"subject": subject, "body": body}, timeout=15)
        return "sent"
    if ctype in ("discord", "slack"):
        # Discord & Slack incoming webhooks both accept a simple {content|text} JSON body
        payload = {"content": f"**{subject}**\n{body}"} if ctype == "discord" else {"text": f"*{subject}*\n{body}"}
        requests.post(target, json=payload, timeout=15)
        return "sent"
    if ctype == "email":
        sc = cfg.get("smtp", {})
        host = sc.get("host") or os.environ.get("SMTP_HOST")
        if not host or not target:
            return "skipped"
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = sc.get("from") or os.environ.get("SMTP_FROM", "alerts@congress-trades")
        msg["To"] = target
        msg.set_content(body)
        port = int(sc.get("port", 587))
        with smtplib.SMTP(host, port, timeout=20) as s:
            if sc.get("starttls", True):
                s.starttls()
            user = sc.get("user") or os.environ.get("SMTP_USER")
            pw = sc.get("password") or os.environ.get("SMTP_PASSWORD")
            if user and pw:
                s.login(user, pw)
            s.send_message(msg)
        return "sent"
    return "skipped"


def run():
    cfg = load_config()
    init_db()
    db = SessionLocal()
    sent = 0
    try:
        rules = db.scalars(select(AlertRule).where(AlertRule.enabled.is_(True))).all()
        if not rules:
            common.record_run(db, "alerts_dispatch", rows_upserted=0, success=True, note="no enabled rules")
            return
        lookback = int(cfg.get("alerts", {}).get("dispatch_lookback_days", 7))
        since = dt.date.today() - dt.timedelta(days=lookback)
        rows = db.execute(
            select(Trade, Member).join(Member, Member.id == Trade.member_id, isouter=True)
            .where(Trade.disclosure_date >= since)
        ).all()
        ids = [t.id for t, _ in rows]
        sig_by_trade = {}
        for tid, stype in db.execute(select(TradeSignal.trade_id, TradeSignal.signal_type).where(TradeSignal.trade_id.in_(ids))).all() if ids else []:
            sig_by_trade.setdefault(tid, set()).add(stype)
        tks = {t.ticker for t, _ in rows if t.ticker}
        sector_by_ticker = dict(db.execute(select(TickerMeta.ticker, TickerMeta.sector).where(TickerMeta.ticker.in_(tks))).all()) if tks else {}
        already = {
            (rid, tid) for rid, tid in db.execute(select(AlertDelivery.rule_id, AlertDelivery.trade_id)).all()
        }

        for rule in rules:
            fired = False
            for t, m in rows:
                if (rule.id, t.id) in already:
                    continue
                lag = (t.disclosure_date - t.transaction_date).days if (t.disclosure_date and t.transaction_date) else None
                ctx = {
                    "member_id": t.member_id, "ticker": t.ticker, "sector": sector_by_ticker.get(t.ticker),
                    "amount_min": t.amount_min, "amount_max": t.amount_max, "lag_days": lag,
                    "option_type": t.option_type, "signal_types": sig_by_trade.get(t.id, set()),
                }
                ok, reason = rule_matches(rule.rule_type, rule.params or {}, ctx)
                if not ok:
                    continue
                subject = f"[{rule.name}] {t.ticker or 'congress trade'}"
                body = _format(t, m, reason)
                status = "skipped"
                for channel in (rule.channels or [{"type": "ntfy", "target": "congress-trades"}]):
                    try:
                        status = _deliver(channel, subject, body, cfg)
                    except Exception as e:  # noqa: BLE001
                        status = "failed"
                        print(f"alerts: rule {rule.id} channel {channel.get('type')} failed: {e}")
                db.execute(
                    pg_insert(AlertDelivery)
                    .values(rule_id=rule.id, trade_id=t.id, channel=",".join(c.get("type", "") for c in (rule.channels or [])) or "ntfy",
                            status=status, fired_at=dt.datetime.now(dt.timezone.utc))
                    .on_conflict_do_nothing(index_elements=["rule_id", "trade_id"])
                )
                already.add((rule.id, t.id))
                fired = True
                sent += 1
            if fired:
                rule.last_fired_at = dt.datetime.now(dt.timezone.utc)
        db.commit()
        common.record_run(db, "alerts_dispatch", rows_upserted=sent, success=True)
        print(f"alerts: delivered {sent} alerts across {len(rules)} rules")
    except Exception as e:  # noqa: BLE001
        common.record_run(db, "alerts_dispatch", success=False, note=str(e))
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
