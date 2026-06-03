"""Conflict Score v2 — a transparent, weighted 0-100 'conflict-of-interest context' score.

The number is built additively from seven named components that sum to 100. It is never
multiplied; every component carries its own points/max and a plain-English explanation so the
UI can show exactly how the score was assembled (transparency over a black-box rating).

`score_components()` is pure: it takes a flat dict of already-measured facts, so it can be unit
tested without a database. `gather_facts()` builds that dict from ORM rows the dossier endpoint
already loads (plus one small median query).

Context only: a high score means "worth a closer look", not wrongdoing or investment merit.
"""
import datetime as dt

# component key -> (label, max points). The maxes sum to exactly 100.
COMPONENTS = [
    ("committee_sector_overlap", "Committee / sector overlap", 22),
    ("vote_proximity", "Member vote near trade", 20),
    ("trade_size_vs_history", "Trade size vs member history", 16),
    ("clustered_activity", "Clustered congressional activity", 14),
    ("disclosure_lateness", "Disclosure lateness", 12),
    ("company_event_proximity", "Company event proximity", 10),
    ("fundamentals_context", "SEC fundamentals context", 6),
]

# STOCK Act periodic-transaction disclosure deadline.
STOCK_ACT_DAYS = 45


def _money(n):
    if n is None:
        return "n/a"
    n = float(n)
    a = abs(n)
    if a >= 1e9:
        return f"${n / 1e9:.1f}B"
    if a >= 1e6:
        return f"${n / 1e6:.1f}M"
    if a >= 1e3:
        return f"${n / 1e3:.0f}K"
    return f"${n:.0f}"


def _committee_sector_overlap(f):
    sector = f.get("ticker_sector")
    sectors = f.get("committee_sectors") or []
    if sector and sector in sectors:
        return 22, f"Member's committee assignments oversee the {sector} sector — and this trade is in {sector}."
    if sectors:
        return 0, f"No overlap: member oversees {', '.join(sectors)}, trade sector is {sector or 'unknown'}."
    return 0, "No committee oversight sectors recorded for this member."


def _vote_proximity(f):
    d = f.get("vote_proximity_days")
    title = f.get("vote_title")
    if d is None:
        return 0, "No same-sector floor vote found near the trade."
    note = f" ({title})" if title else ""
    if d <= 7:
        return 20, f"Cast a related-sector floor vote {d} day(s) from the trade{note}."
    if d <= 30:
        return 14, f"Cast a related-sector floor vote {d} days from the trade{note}."
    if d <= 90:
        return 8, f"Cast a related-sector floor vote {d} days from the trade{note}."
    return 3, f"Cast a related-sector floor vote {d} days from the trade{note}."


def _trade_size_vs_history(f):
    amt = float(f.get("amount_min") or 0)
    mid = float(f.get("amount_mid") or amt)
    med = f.get("member_median")
    if med and med > 0:
        ratio = amt / med
        if ratio >= 5:
            return 16, f"Trade is {ratio:.1f}× this member's median disclosed size ({_money(med)})."
        if ratio >= 3:
            return 11, f"Trade is {ratio:.1f}× this member's median disclosed size ({_money(med)})."
        if ratio >= 2:
            return 6, f"Trade is {ratio:.1f}× this member's median disclosed size ({_money(med)})."
        return 0, f"Typical size for this member ({ratio:.1f}× their median)."
    # no history to compare against — fall back to absolute size
    if mid >= 1_000_000:
        return 8, f"{_money(mid)} trade with no prior history to compare."
    if mid >= 250_000:
        return 4, f"{_money(mid)} trade with no prior history to compare."
    return 0, "No member trade history to compare size against."


def _clustered_activity(f):
    n = int(f.get("cluster_members") or 0)
    direction = f.get("cluster_direction") or "traded"
    ticker = f.get("ticker") or "the ticker"
    if n >= 4:
        return 14, f"{n} members {direction} {ticker} in the same window (strong cluster)."
    if n == 3:
        return 10, f"{n} members {direction} {ticker} in the same window."
    if n == 2:
        return 6, f"Another member also {direction} {ticker} in the same window."
    return 0, "No clustered congressional activity in this ticker."


def _disclosure_lateness(f):
    lag = f.get("lag_days")
    if lag is None:
        return 0, "Disclosure timing unknown."
    if lag <= STOCK_ACT_DAYS:
        return 0, f"Disclosed within the {STOCK_ACT_DAYS}-day STOCK Act window ({lag} days)."
    if lag <= 90:
        return 6, f"Disclosed {lag} days after trading — past the {STOCK_ACT_DAYS}-day STOCK Act window."
    if lag <= 180:
        return 9, f"Disclosed {lag} days after trading — well past the {STOCK_ACT_DAYS}-day window."
    return 12, f"Disclosed {lag} days after trading — months past the {STOCK_ACT_DAYS}-day window."


def _company_event_proximity(f):
    d = f.get("sec_event_days")
    form = f.get("sec_event_form")
    if d is None:
        return 0, "No SEC 8-K / Form 4 filed near the trade."
    label = f"SEC {form}" if form else "An SEC filing"
    if d <= 14:
        return 10, f"{label} was filed {d} day(s) from the trade."
    if d <= 30:
        return 6, f"{label} was filed {d} days from the trade."
    return 3, f"{label} was filed {d} days from the trade."


def _fundamentals_context(f):
    fund = f.get("fundamentals")
    if not fund:
        return 0, "No SEC fundamentals on file for this company."
    company = fund.get("company") or f.get("ticker") or "Company"
    rev = _money(fund.get("revenue"))
    ni = _money(fund.get("net_income"))
    form = fund.get("latest_form") or "filing"
    base_detail = f"{company}: revenue {rev}, net income {ni} (latest {form})."
    d = f.get("fundamentals_event_days")
    if d is not None and d <= 14:
        return 6, base_detail + f" Traded {d} day(s) from a reporting period end."
    if d is not None and d <= 45:
        return 4, base_detail + f" Traded {d} days from a reporting period end."
    return 2, base_detail


_SCORERS = {
    "committee_sector_overlap": _committee_sector_overlap,
    "vote_proximity": _vote_proximity,
    "trade_size_vs_history": _trade_size_vs_history,
    "clustered_activity": _clustered_activity,
    "disclosure_lateness": _disclosure_lateness,
    "company_event_proximity": _company_event_proximity,
    "fundamentals_context": _fundamentals_context,
}


def _level(score):
    if score >= 60:
        return "high"
    if score >= 35:
        return "medium"
    if score >= 12:
        return "low"
    return "none"


def score_components(facts):
    """Pure: facts dict -> {version, score, level, components[], summary[], methodology}.

    `facts` keys (all optional, missing => that component scores 0):
      ticker, ticker_sector, committee_sectors, vote_proximity_days, vote_title,
      amount_min, amount_mid, member_median, cluster_members, cluster_direction,
      lag_days, sec_event_days, sec_event_form, fundamentals, fundamentals_event_days.
    """
    components = []
    for key, label, maximum in COMPONENTS:
        points, detail = _SCORERS[key](facts)
        points = max(0, min(maximum, int(points)))
        components.append({"key": key, "label": label, "points": points, "max": maximum, "detail": detail})
    score = min(100, sum(c["points"] for c in components))
    contributing = sorted((c for c in components if c["points"] > 0), key=lambda c: c["points"], reverse=True)
    return {
        "version": 2,
        "score": score,
        "level": _level(score),
        "components": components,
        "summary": [c["label"] for c in contributing],
        # `reasons` kept for backward-compatible UI consumers that show a flat reason line.
        "reasons": [c["detail"] for c in contributing],
        "methodology": (
            "Additive 0-100 across seven weighted, capped components. Each component is shown with "
            "its own points so the score is fully auditable. Context only — not an allegation of "
            "wrongdoing and not investment advice."
        ),
    }


def _abs_days(a, b):
    if a is None or b is None:
        return None
    if isinstance(a, dt.datetime):
        a = a.date()
    if isinstance(b, dt.datetime):
        b = b.date()
    return abs((a - b).days)


def gather_facts(trade, member, *, ticker_sector=None, signals=None, policy_rows=None,
                 sec_rows=None, member_median=None, fundamentals=None):
    """Build the facts dict from data the dossier endpoint already loaded.

    trade/member are ORM rows (duck-typed). policy_rows is a list of (LegislativeEvent, Member),
    sec_rows a list of GovEvent, signals a list of {type, score, detail}. No DB access here.
    """
    signals = signals or []
    sig_by_type = {s.get("type"): (s.get("detail") or {}) for s in signals}

    tx = trade.transaction_date
    lag = None
    if trade.transaction_date and trade.disclosure_date:
        lag = (trade.disclosure_date - trade.transaction_date).days

    amt_min = float(trade.amount_min) if trade.amount_min is not None else 0.0
    amt_max = float(trade.amount_max) if trade.amount_max is not None else amt_min
    amt_mid = amt_min + (amt_max - amt_min) / 2

    # closest same-sector floor vote by this member (member_house_vote), else any member vote
    vote_days, vote_title = None, None
    best_other = None
    for event, _m in (policy_rows or []):
        if (event.event_type or "") != "member_house_vote":
            continue
        d = _abs_days(event.occurred_at, tx) if tx else _abs_days(event.occurred_at, trade.disclosure_date)
        if d is None:
            continue
        sector_match = ticker_sector and event.sector == ticker_sector
        if sector_match:
            if vote_days is None or d < vote_days:
                vote_days, vote_title = d, event.title
        elif best_other is None or d < best_other[0]:
            best_other = (d, event.title)
    if vote_days is None and best_other is not None:
        # a member vote near the trade, sector unconfirmed — count it at arm's length
        vote_days, vote_title = best_other

    # closest SEC corporate event for this ticker
    sec_days, sec_form = None, None
    for ev in (sec_rows or []):
        d = _abs_days(ev.filed_at, tx) if tx else _abs_days(ev.filed_at, trade.disclosure_date)
        if d is None:
            continue
        if sec_days is None or d < sec_days:
            sec_days, sec_form = d, ev.form

    cluster = sig_by_type.get("cluster_buy") or sig_by_type.get("cluster_sell") or {}
    cluster_dir = "bought" if "cluster_buy" in sig_by_type else "sold" if "cluster_sell" in sig_by_type else None

    fundamentals_event_days = None
    if fundamentals and tx:
        cands = [d for d in (_abs_days(fundamentals.get("q_end"), tx),
                             _abs_days(fundamentals.get("fy_end"), tx)) if d is not None]
        if cands:
            fundamentals_event_days = min(cands)

    return {
        "ticker": trade.ticker,
        "ticker_sector": ticker_sector,
        "committee_sectors": (member.committee_sectors if member else None) or [],
        "vote_proximity_days": vote_days,
        "vote_title": vote_title,
        "amount_min": amt_min,
        "amount_mid": amt_mid,
        "member_median": member_median,
        "cluster_members": int(cluster.get("members") or 0),
        "cluster_direction": cluster_dir,
        "lag_days": lag,
        "sec_event_days": sec_days,
        "sec_event_form": sec_form,
        "fundamentals": fundamentals,
        "fundamentals_event_days": fundamentals_event_days,
    }
