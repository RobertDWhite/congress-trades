"""Weekly email digest: renders the shared digest payload (AI overview + hottest tickers +
conflicts + new positions) to HTML and emails it to configured recipients and any account that
opted in via prefs.digest_email. SMTP config-gated; no-ops cleanly without it."""
import os
import smtplib
from email.message import EmailMessage

from sqlalchemy import select

from app.config import load_config
from app.db import SessionLocal, init_db
from app.models import UserAccount
from app.routers.feeds import build_digest

from . import common


def render_html(d):
    rows = "".join(
        f"<li><b>{h['ticker']}</b> — {h['buys']} buys / {h['sells']} sells</li>" for h in d.get("hot_tickers", [])
    )
    conflicts = "".join(
        f"<li>{c['member']} · {c['ticker']} ({c['sector'] or '—'})</li>" for c in d.get("conflicts", [])
    )
    obs = "".join(f"<li>{o.get('text', '')}</li>" for o in d.get("observations", [])[:6])
    summary = (d.get("summary_md") or "No summary available for this window.").replace("\n", "<br>")
    return f"""<html><body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#0d1117">
<h2>Congress Trades — last {d['window_days']} days</h2>
<p>{summary}</p>
<h3>Hottest tickers</h3><ul>{rows or '<li>—</li>'}</ul>
<h3>Notable observations</h3><ul>{obs or '<li>—</li>'}</ul>
<h3>Committee/sector conflicts</h3><ul>{conflicts or '<li>—</li>'}</ul>
<p>{d['new_position_pairs']} new member/ticker positions opened.</p>
<p style="color:#8b949e;font-size:12px">{d['disclaimer']}</p>
</body></html>"""


def _send(sc, to, subject, html):
    host = sc.get("host") or os.environ.get("SMTP_HOST")
    if not host:
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sc.get("from") or os.environ.get("SMTP_FROM", "digest@congress-trades")
    msg["To"] = to
    msg.set_content("Open in an HTML-capable client.")
    msg.add_alternative(html, subtype="html")
    with smtplib.SMTP(host, int(sc.get("port", 587)), timeout=20) as s:
        if sc.get("starttls", True):
            s.starttls()
        user = sc.get("user") or os.environ.get("SMTP_USER")
        pw = sc.get("password") or os.environ.get("SMTP_PASSWORD")
        if user and pw:
            s.login(user, pw)
        s.send_message(msg)
    return True


def run():
    cfg = load_config()
    init_db()
    dc = cfg.get("digest", {})
    if not dc.get("enabled", True):
        return
    sc = cfg.get("smtp", {})
    db = SessionLocal()
    sent = 0
    try:
        payload = build_digest(db, int(dc.get("window_days", 7)))
        html = render_html(payload)
        subject = f"Congress Trades — weekly digest"
        recipients = list(dc.get("recipients", []))
        # accounts that opted into the digest
        for (prefs,) in db.execute(select(UserAccount.prefs).where(UserAccount.prefs.isnot(None))).all():
            email = (prefs or {}).get("digest_email")
            if email:
                recipients.append(email)
        for to in dict.fromkeys(r for r in recipients if r):  # de-dup, preserve order
            try:
                if _send(sc, to, subject, html):
                    sent += 1
            except Exception as e:  # noqa: BLE001
                print(f"digest: send to {to} failed: {e}")
        common.record_run(db, "digest_email", rows_upserted=sent, success=True)
        print(f"digest: sent {sent} emails")
    except Exception as e:  # noqa: BLE001
        common.record_run(db, "digest_email", success=False, note=str(e))
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
