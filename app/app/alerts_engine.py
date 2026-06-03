"""Pure alert-rule matching. `rule_matches` takes a rule and a flat trade context and returns
(matched, reason) — no DB, so it is unit-testable and shared by the preview endpoint and the
dispatch job. Delivery (ntfy/webhook/email) lives in ingest/alerts_dispatch.py."""

RULE_TYPES = ("member", "ticker", "sector", "large", "cluster", "conflict", "late", "options", "event_proximity")

STOCK_ACT_DAYS = 45


def _num(v, default=0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def rule_matches(rule_type, params, ctx):
    """ctx keys: member_id, ticker, sector, amount_min, amount_max, lag_days, option_type,
    signal_types (set/list). Returns (bool, reason_str)."""
    params = params or {}
    sig = set(ctx.get("signal_types") or [])

    if rule_type == "member":
        want = params.get("member_id")
        if want is not None and ctx.get("member_id") == int(want):
            return True, f"watched member traded {ctx.get('ticker') or 'an asset'}"
        return False, ""

    if rule_type == "ticker":
        want = (params.get("ticker") or "").upper()
        if want and (ctx.get("ticker") or "").upper() == want:
            return True, f"watched ticker {want} traded"
        return False, ""

    if rule_type == "sector":
        want = params.get("sector")
        if want and ctx.get("sector") == want:
            return True, f"trade in watched sector {want}"
        return False, ""

    if rule_type == "large":
        threshold = _num(params.get("min_amount"), 100_000)
        size = max(_num(ctx.get("amount_max")), _num(ctx.get("amount_min")))
        if size >= threshold:
            return True, f"large trade (≥ ${int(threshold):,})"
        return False, ""

    if rule_type == "cluster":
        if "cluster_buy" in sig or "cluster_sell" in sig:
            return True, "clustered congressional activity"
        return False, ""

    if rule_type == "conflict":
        if "conflict" in sig:
            return True, "committee/sector conflict"
        return False, ""

    if rule_type == "options":
        if "options" in sig or ctx.get("option_type"):
            return True, "options / derivative position"
        return False, ""

    if rule_type == "event_proximity":
        if "corp_event" in sig:
            return True, "SEC 8-K/Form 4 near the trade"
        return False, ""

    if rule_type == "late":
        min_lag = _num(params.get("min_lag"), STOCK_ACT_DAYS)
        lag = ctx.get("lag_days")
        if lag is not None and lag >= min_lag:
            return True, f"disclosed {int(lag)}d after trading (≥ {int(min_lag)}d)"
        return False, ""

    return False, ""
