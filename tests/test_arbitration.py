"""Tests for BGCC + AI arbitration (cycle_arbitration.py)."""

import networkx as nx
import pytest

from cycle_arbitration import (
    build_context,
    build_labels,
    enumerate_cycles,
    make_ai_arbiter,
    select_cycles,
)


def graph(*edges):
    G = nx.DiGraph()
    for u, v, w in edges:
        G.add_edge(u, v, weight=w)
    return G


def conflict_graph():
    """
    Two cycles compete for the same slot next to X and Y:
        X -> A -> Y -> X   (A: higher utility)
        X -> B -> Y -> X   (B: slightly lower)
    A can ALSO join a different cycle  A -> P -> Q -> A.
    """
    return graph(
        ("X", "A", 0.90), ("A", "Y", 0.90), ("Y", "X", 0.90),
        ("X", "B", 0.85), ("B", "Y", 0.85),
        ("A", "P", 0.80), ("P", "Q", 0.80), ("Q", "A", 0.80),
    )


def ok(index, reason="urgency"):
    return {
        "recommended_candidate": index,
        "reason": reason,
        "qualitative_factors_considered": ["urgency"],
        "limitations": [],
        "suggested_adjustment": None,
        "confidence": 0.9,
    }


def pick_cycle_containing(user):
    def arbiter(records, context):
        for i, r in enumerate(records, start=1):
            if user in r["cycle"]:
                return ok(i)
        raise AssertionError("user not offered")
    return arbiter


CONTEXT = {
    "B": {"urgency": "high - recital next week"},
    "A": {"urgency": "low - no rush"},
}


def test_plain_bgcc_picks_highest_utility_cycle():
    cycles, _, decisions = select_cycles(conflict_graph(), 4)
    assert any("A" in c and "X" in c for c in cycles)
    assert not any("B" in c for c in cycles)
    assert decisions == {}


def test_urgent_user_wins_and_loser_joins_another_cycle():
    cycles, remaining, decisions = select_cycles(
        conflict_graph(), 4, CONTEXT, pick_cycle_containing("B"), log=lambda *_: None
    )
    sets = [set(c) for c in cycles]
    assert {"B", "X", "Y"} in sets          # B got the cycle A would have won
    assert {"A", "P", "Q"} in sets          # A was placed in another cycle
    assert remaining == set()
    assert frozenset({"B", "X", "Y"}) in decisions


def test_chosen_cycles_are_always_disjoint():
    cycles, _, _ = select_cycles(
        conflict_graph(), 4, CONTEXT, pick_cycle_containing("B"), log=lambda *_: None
    )
    used = [u for c in cycles for u in c]
    assert len(used) == len(set(used))


def test_ai_can_only_choose_cycles_bgcc_found():
    G = conflict_graph()
    valid = {frozenset(c) for c in enumerate_cycles(G, 4)}
    cycles, _, _ = select_cycles(
        G, 4, CONTEXT, pick_cycle_containing("B"), log=lambda *_: None
    )
    assert all(frozenset(c) in valid for c in cycles)


def test_out_of_range_choice_falls_back_to_plain_bgcc():
    plain, _, _ = select_cycles(conflict_graph(), 4)
    cycles, _, decisions = select_cycles(
        conflict_graph(), 4, CONTEXT, lambda r, c: ok(99), log=lambda *_: None
    )
    assert [set(c) for c in cycles] == [set(c) for c in plain]
    assert decisions == {}


@pytest.mark.parametrize("bad", [0, -1, True, "1", None, 1.0])
def test_invalid_choice_types_fall_back(bad):
    plain, _, _ = select_cycles(conflict_graph(), 4)
    cycles, _, decisions = select_cycles(
        conflict_graph(), 4, CONTEXT, lambda r, c: ok(bad), log=lambda *_: None
    )
    assert [set(c) for c in cycles] == [set(c) for c in plain]
    assert decisions == {}


def test_arbiter_exception_falls_back_to_plain_bgcc():
    def boom(records, context):
        raise RuntimeError("OpenRouter is down")

    plain, _, _ = select_cycles(conflict_graph(), 4)
    cycles, _, decisions = select_cycles(
        conflict_graph(), 4, CONTEXT, boom, log=lambda *_: None
    )
    assert [set(c) for c in cycles] == [set(c) for c in plain]
    assert decisions == {}


def test_ai_not_called_without_context():
    calls = []
    select_cycles(
        conflict_graph(), 4, {}, lambda r, c: calls.append(1) or ok(1),
        log=lambda *_: None,
    )
    assert calls == []


def test_ai_not_called_when_cycles_do_not_conflict():
    G = graph(
        ("A", "B", 0.9), ("B", "A", 0.9),
        ("C", "D", 0.8), ("D", "C", 0.8),
    )
    calls = []
    cycles, _, _ = select_cycles(
        G, 4, {"A": {"urgency": "high"}}, lambda r, c: calls.append(1) or ok(1),
        log=lambda *_: None,
    )
    assert calls == [] and len(cycles) == 2


def test_weak_alternative_is_not_offered_to_the_ai():
    # B's cycle is much worse than A's (0.3 vs 0.9) -> below the 60% floor
    G = graph(
        ("X", "A", 0.90), ("A", "Y", 0.90), ("Y", "X", 0.90),
        ("X", "B", 0.30), ("B", "Y", 0.30),
    )
    offered = []

    def arbiter(records, context):
        offered.append([r["cycle"] for r in records])
        return ok(1)

    select_cycles(G, 4, CONTEXT, arbiter, log=lambda *_: None)
    assert offered == []  # only one viable candidate -> nothing to arbitrate


def test_min_weight_ratio_is_configurable():
    G = graph(
        ("X", "A", 0.90), ("A", "Y", 0.90), ("Y", "X", 0.90),
        ("X", "B", 0.30), ("B", "Y", 0.30),
    )
    offered = []

    def arbiter(records, context):
        offered.append(len(records))
        return ok(1)

    select_cycles(G, 4, CONTEXT, arbiter, min_weight_ratio=0.1, log=lambda *_: None)
    assert offered == [2]


def test_records_offered_to_ai_carry_scores_and_best_comes_first():
    seen = {}

    def arbiter(records, context):
        seen["records"] = records
        return ok(1)

    select_cycles(conflict_graph(), 4, CONTEXT, arbiter, log=lambda *_: None)
    records = seen["records"]
    assert records[0]["total_utility"] >= records[1]["total_utility"]
    assert {"cycle", "total_utility", "egalitarian_score"} <= records[0].keys()


# ------------------------------------------------------------ adapters

def test_build_labels_first_names_when_unique():
    labels = build_labels(["u1", "u2"], {"u1": "Alice Tan", "u2": "Bob Lee"})
    assert labels == {"u1": "Alice", "u2": "Bob"}


def test_build_labels_disambiguates_duplicates():
    labels = build_labels(
        ["u1", "u2", "u3"],
        {"u1": "Sam Tan", "u2": "Sam Lee", "u3": "Nadia"},
    )
    assert len({v.lower() for v in labels.values()}) == 3
    assert labels["u3"] == "Nadia"
    assert labels["u1"] != labels["u2"]


def test_build_labels_handles_missing_names():
    labels = build_labels(["abcd1234"], {})
    assert labels["abcd1234"].startswith("User abcd")


def test_build_context_uses_only_what_the_user_said():
    prefs = [
        {"userId": "b", "normalized": {
            "urgency": "high", "urgency_reason": "recital next week",
            "notes": "wants clean fretboard", "flexibility": 0.1,
            "desired_item": "acoustic guitar"}},
        {"userId": "a", "normalized": {
            "urgency": "none", "urgency_reason": "", "notes": "",
            "flexibility": 0.5, "desired_item": "bike"}},
        {"userId": "", "normalized": {"urgency": "high"}},
    ]
    ctx = build_context(prefs)
    assert set(ctx) == {"b"}
    assert ctx["b"]["urgency"] == "high - recital next week"
    assert ctx["b"]["condition_notes"] == "wants clean fretboard"
    assert "strict" in ctx["b"]["priority"]
    assert ctx["b"]["wants"] == "acoustic guitar"


def test_make_ai_arbiter_sends_names_never_uids():
    captured = {}

    def fake_evaluate(preferences, candidates, qualitative_context, known_items):
        captured.update(
            preferences=preferences, candidates=candidates,
            qualitative_context=qualitative_context, known_items=known_items,
        )
        return ok(1)

    labels = {"uidA": "Alice", "uidB": "Bob", "uidX": "Xena"}
    arbiter = make_ai_arbiter(labels, fake_evaluate, {"guitar"})
    records = [
        {"cycle": ["uidX", "uidA"], "total_utility": 1.6, "egalitarian_score": 0.8},
        {"cycle": ["uidX", "uidB"], "total_utility": 1.5, "egalitarian_score": 0.7},
    ]
    context = {"uidB": {"urgency": "high", "wants": "guitar"}}
    arbiter(records, context)

    assert captured["candidates"][0]["cycle"] == ["Xena", "Alice"]
    assert "Bob" in captured["qualitative_context"]
    assert "wants" not in captured["qualitative_context"]["Bob"]
    assert captured["preferences"]["Bob"] == {"wants": "guitar"}
    flat = str(captured)
    assert "uidA" not in flat and "uidB" not in flat and "uidX" not in flat
    assert captured["known_items"] == {"guitar"}
