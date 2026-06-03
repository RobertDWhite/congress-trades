from app import analysis_scoring


class Trade:
    id = 1
    ticker = "NVDA"
    amount_min = 1_000_000
    amount_max = 5_000_000


class Member:
    committees = ["House Armed Services"]


class Event:
    event_type = "member_house_vote"


def test_conflict_score_weights_context_and_signals():
    score = analysis_scoring.conflict_score(
        Trade(),
        Member(),
        [{"type": "late_disclosure", "score": 5}, {"type": "conviction", "score": 65}],
        [(Event(), Member())],
        [object()],
    )

    assert score["level"] == "high"
    assert score["score"] >= 70
    assert any("Congress.gov" in r for r in score["reasons"])


def test_unusual_score_marks_first_large_member_trade():
    score = analysis_scoring.unusual_score(Trade(), [{"type": "large", "score": 10}], [])

    assert score["score"] >= 30
    assert "large" in " ".join(score["reasons"])
