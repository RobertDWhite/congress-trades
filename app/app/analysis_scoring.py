import statistics


def amount_mid(row):
    lo = float(row.amount_min) if row.amount_min is not None else 0.0
    hi = float(row.amount_max) if row.amount_max is not None else lo
    return lo + ((hi - lo) / 2)


def signal_types(signals):
    return {s.get("type") for s in (signals or []) if s.get("type")}


def conflict_score(trade, member, signals, policy_events, sec_events):
    types = signal_types(signals)
    score = 0
    reasons = []
    if member and member.committees:
        score += 10
        reasons.append("member committee assignments create oversight context")
    if policy_events:
        vote_events = [e for e, _ in policy_events if "vote" in (e.event_type or "")]
        score += 25 if vote_events else 15
        reasons.append(f"{len(policy_events)} nearby Congress.gov event(s)")
    if sec_events:
        score += 15
        reasons.append(f"{len(sec_events)} nearby SEC event(s)")
    if "conflict" in types or "legislative_context" in types:
        score += 20
        reasons.append("existing conflict/policy-context signal")
    if "late_disclosure" in types:
        score += 10
        reasons.append("late disclosure signal")
    if "large" in types:
        score += 10
        reasons.append("large disclosed range signal")
    conviction = next((s for s in signals if s.get("type") == "conviction"), None)
    if conviction:
        cscore = int(conviction.get("score") or 0)
        if cscore >= 60:
            score += 10
            reasons.append(f"high conviction score ({cscore})")
        elif cscore >= 35:
            score += 5
            reasons.append(f"moderate conviction score ({cscore})")
    if amount_mid(trade) >= 1_000_000:
        score += 10
        reasons.append("million-dollar disclosed range midpoint")
    score = max(0, min(100, score))
    level = "high" if score >= 70 else "medium" if score >= 40 else "low" if score else "none"
    return {"score": score, "level": level, "reasons": reasons}


def unusual_score(trade, signals, history):
    types = signal_types(signals)
    score = 0
    reasons = []
    conviction = next((s for s in signals if s.get("type") == "conviction"), None)
    if conviction:
        cscore = int(conviction.get("score") or 0)
        score += min(25, max(0, cscore // 4))
        if cscore >= 50:
            reasons.append(f"conviction {cscore}")
    weights = {
        "cluster_buy": 20,
        "cluster_sell": 18,
        "large": 18,
        "options": 15,
        "late_disclosure": 12,
        "anomaly": 18,
        "conflict": 20,
        "corp_event": 15,
        "legislative_context": 18,
    }
    for stype in sorted(t for t in types if t != "conviction"):
        score += weights.get(stype, 5)
        reasons.append(stype.replace("_", " "))
    amount = amount_mid(trade)
    if amount >= 1_000_000:
        score += 15
        reasons.append("million-dollar disclosed range midpoint")
    elif amount >= 250_000:
        score += 8
        reasons.append("large disclosed range midpoint")
    if history:
        same_ticker = [t for t in history if t.ticker == trade.ticker and t.id != trade.id]
        if trade.ticker and not same_ticker:
            score += 12
            reasons.append("first observed ticker trade for this member")
        mids = [amount_mid(t) for t in history if t.id != trade.id]
        if mids and amount > max(statistics.median(mids) * 3, 100_000):
            score += 10
            reasons.append("much larger than member median trade")
    return {"score": min(100, score), "reasons": reasons}
