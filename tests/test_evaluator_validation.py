"""The AI evaluator's boundary checks: what the AI may and may not say."""

import pytest

import ai_cycle_evaluator as ev

CANDIDATES = [
    {"cycle": ["Alice", "Bob"], "total_utility": 1.6, "egalitarian_score": 0.8},
    {"cycle": ["Carol", "Dan"], "total_utility": 1.5, "egalitarian_score": 0.7},
]
USERS = {"Alice", "Bob", "Carol", "Dan"}
ITEMS = {"guitar", "camera"}


def good(**overrides):
    result = {
        "recommended_candidate": 1,
        "reason": "Alice needs the guitar urgently for a recital.",
        "qualitative_factors_considered": ["Alice's urgency"],
        "limitations": [],
        "suggested_adjustment": None,
        "confidence": 0.8,
    }
    result.update(overrides)
    return result


def check(result):
    return ev.validate_result(result, CANDIDATES, USERS, ITEMS)


def test_valid_result_passes():
    assert check(good())["confidence"] == 0.8


@pytest.mark.parametrize("bad", [0, 3, -1, True, "1", None])
def test_candidate_not_supplied_is_rejected(bad):
    with pytest.raises(ValueError):
        check(good(recommended_candidate=bad))


def test_missing_fields_rejected():
    result = good()
    del result["limitations"]
    with pytest.raises(ValueError, match="missing"):
        check(result)


def test_reason_must_cite_a_qualitative_factor():
    with pytest.raises(ValueError, match="qualitative"):
        check(good(reason="Alice and Bob is simply the best overall choice."))


def test_reason_must_not_cite_a_user_outside_the_cycle():
    with pytest.raises(ValueError, match="not participants"):
        check(good(reason="Alice has urgency, and Carol's need is high too."))


def test_reason_must_name_a_participant():
    with pytest.raises(ValueError, match="does not name"):
        check(good(
            reason="Someone has a high urgency for this.",
            qualitative_factors_considered=["urgency"],
        ))


def test_short_name_is_not_found_inside_a_longer_name():
    # "Al" must not be treated as mentioned just because "Alice" is.
    result = ev.validate_result(
        good(),
        CANDIDATES,
        USERS | {"Al"},
        ITEMS,
    )
    assert result["recommended_candidate"] == 1


def test_adjustment_must_reference_a_known_user_or_item():
    with pytest.raises(ValueError, match="invented"):
        check(good(suggested_adjustment="Add a drum kit to the deal."))
    assert check(good(suggested_adjustment="Bob could add a camera."))


@pytest.mark.parametrize("bad", [-0.1, 1.5, "high"])
def test_confidence_must_be_between_zero_and_one(bad):
    with pytest.raises(ValueError):
        check(good(confidence=bad))


def test_non_object_result_rejected():
    with pytest.raises(ValueError):
        check(["not", "a", "dict"])
