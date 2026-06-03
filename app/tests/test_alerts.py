from app import alerts_engine as ae


def test_member_rule():
    ok, why = ae.rule_matches("member", {"member_id": 7}, {"member_id": 7, "ticker": "NVDA"})
    assert ok and "NVDA" in why
    assert not ae.rule_matches("member", {"member_id": 7}, {"member_id": 8})[0]


def test_ticker_rule_case_insensitive():
    assert ae.rule_matches("ticker", {"ticker": "nvda"}, {"ticker": "NVDA"})[0]
    assert not ae.rule_matches("ticker", {"ticker": "AAPL"}, {"ticker": "NVDA"})[0]


def test_large_rule_uses_max_bound():
    assert ae.rule_matches("large", {"min_amount": 250000}, {"amount_min": 100000, "amount_max": 500000})[0]
    assert not ae.rule_matches("large", {"min_amount": 250000}, {"amount_min": 1000, "amount_max": 15000})[0]


def test_signal_rules():
    assert ae.rule_matches("conflict", {}, {"signal_types": {"conflict"}})[0]
    assert ae.rule_matches("cluster", {}, {"signal_types": {"cluster_sell"}})[0]
    assert ae.rule_matches("options", {}, {"signal_types": set(), "option_type": "call"})[0]
    assert ae.rule_matches("event_proximity", {}, {"signal_types": {"corp_event"}})[0]
    assert not ae.rule_matches("conflict", {}, {"signal_types": {"large"}})[0]


def test_late_rule():
    assert ae.rule_matches("late", {}, {"lag_days": 60})[0]            # default threshold 45
    assert ae.rule_matches("late", {"min_lag": 90}, {"lag_days": 120})[0]
    assert not ae.rule_matches("late", {"min_lag": 90}, {"lag_days": 50})[0]
    assert not ae.rule_matches("late", {}, {"lag_days": None})[0]
