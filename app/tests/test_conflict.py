import datetime as dt
from types import SimpleNamespace

from app import conflict


def _points(result):
    return {c["key"]: c["points"] for c in result["components"]}


def test_empty_facts_score_zero():
    result = conflict.score_components({})
    assert result["score"] == 0
    assert result["level"] == "none"
    assert len(result["components"]) == len(conflict.COMPONENTS)
    assert all(c["points"] == 0 for c in result["components"])


def test_full_conflict_caps_at_100_high():
    facts = {
        "ticker": "XOM",
        "ticker_sector": "Energy",
        "committee_sectors": ["Energy", "Utilities"],
        "vote_proximity_days": 3,
        "vote_title": "Energy Permitting Reform Act",
        "amount_min": 500_000,
        "amount_mid": 750_000,
        "member_median": 50_000,
        "cluster_members": 4,
        "cluster_direction": "bought",
        "lag_days": 200,
        "sec_event_days": 5,
        "sec_event_form": "8-K",
        "fundamentals": {"company": "Exxon", "revenue": 3.4e11, "net_income": 3.6e10, "latest_form": "10-K"},
        "fundamentals_event_days": 10,
    }
    result = conflict.score_components(facts)
    pts = _points(result)
    assert pts == {
        "committee_sector_overlap": 22,
        "vote_proximity": 20,
        "trade_size_vs_history": 16,
        "clustered_activity": 14,
        "disclosure_lateness": 12,
        "company_event_proximity": 10,
        "fundamentals_context": 6,
    }
    assert result["score"] == 100
    assert result["level"] == "high"
    # the most-weighted contributing component leads the summary
    assert result["summary"][0] == "Committee / sector overlap"


def test_partial_context_scores_low():
    facts = {
        "ticker": "AAPL",
        "ticker_sector": "Technology",
        "committee_sectors": ["Energy"],   # no overlap
        "vote_proximity_days": 60,         # 8 pts
        "amount_min": 125_000,
        "amount_mid": 200_000,
        "member_median": 50_000,           # 2.5x -> 6 pts
        "cluster_members": 0,
        "lag_days": 50,                    # 6 pts
        "sec_event_days": None,
        "fundamentals": None,
    }
    result = conflict.score_components(facts)
    assert _points(result)["committee_sector_overlap"] == 0
    assert result["score"] == 20
    assert result["level"] == "low"


def test_gather_facts_derives_proximities():
    tx = dt.date(2026, 1, 15)
    trade = SimpleNamespace(
        ticker="XOM",
        transaction_date=tx,
        disclosure_date=dt.date(2026, 3, 15),  # 59-day lag (past the 45-day window)
        amount_min=300_000,
        amount_max=600_000,
    )
    member = SimpleNamespace(committee_sectors=["Energy"], committees=["House Energy and Commerce"])
    vote = SimpleNamespace(
        event_type="member_house_vote",
        occurred_at=dt.datetime(2026, 1, 10, tzinfo=dt.timezone.utc),  # 5 days before
        sector="Energy",
        title="member voted YEA on Energy bill",
    )
    sec = SimpleNamespace(filed_at=dt.datetime(2026, 1, 20, tzinfo=dt.timezone.utc), form="8-K")  # 5 days after
    fundamentals = {"q_end": dt.date(2026, 1, 1), "fy_end": dt.date(2025, 9, 30), "company": "Exxon"}

    facts = conflict.gather_facts(
        trade, member,
        ticker_sector="Energy",
        signals=[{"type": "cluster_buy", "detail": {"members": 3}}],
        policy_rows=[(vote, member)],
        sec_rows=[sec],
        member_median=60_000,
        fundamentals=fundamentals,
    )
    assert facts["vote_proximity_days"] == 5
    assert facts["cluster_members"] == 3
    assert facts["cluster_direction"] == "bought"
    assert facts["lag_days"] == 59
    assert facts["sec_event_days"] == 5
    assert facts["fundamentals_event_days"] == 14  # closest of q_end(14) / fy_end(107)

    result = conflict.score_components(facts)
    # 22 overlap + 20 vote + 16 size(5x) + 10 cluster(3) + 6 late(59) + 10 sec(5d) + 6 fundamentals(14d)
    assert result["score"] == 90
    assert result["level"] == "high"
