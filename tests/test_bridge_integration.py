"""
End-to-end check of the new pipeline WITHOUT Firebase or OpenRouter:
graph -> select_cycles (+ real evaluator validation, mocked HTTP) -> save_matches
(into an in-memory fake Firestore).
"""

import json

import networkx as nx
import pytest

import ai_cycle_evaluator as ev
import firestore_bridge as bridge
from cycle_arbitration import build_labels, make_ai_arbiter, select_cycles


class FakeDoc:
    def __init__(self, store, key):
        self.store, self.key = store, key

    @property
    def exists(self):
        return self.key in self.store

    def get(self):
        return self

    def set(self, data):
        self.store[self.key] = data


class FakeCollection:
    def __init__(self, store):
        self.store = store

    def document(self, key):
        return FakeDoc(self.store, key)


class FakeDB:
    def __init__(self):
        self.collections = {}

    def collection(self, name):
        return FakeCollection(self.collections.setdefault(name, {}))


def listing_graph():
    """uids: x, a, b, y, p, q.  x/y trade with a OR b; a can alternatively do p,q."""
    G = nx.DiGraph()

    def edge(u, v, w, item):
        G.add_edge(u, v, weight=w, listingId=f"L-{v}", item=item,
                   category="misc", brand="")

    edge("x", "a", 0.90, "guitar")
    edge("a", "y", 0.90, "camera")
    edge("y", "x", 0.90, "bike")
    edge("x", "b", 0.85, "guitar")
    edge("b", "y", 0.85, "camera")
    edge("a", "p", 0.80, "lamp")
    edge("p", "q", 0.80, "desk")
    edge("q", "a", 0.80, "chair")
    return G


NAMES = {"x": "Xena", "a": "Aiden", "b": "Bella", "y": "Yusuf", "p": "Priya", "q": "Quinn"}
PREFS = [
    {"userId": "b", "normalized": {
        "urgency": "high", "urgency_reason": "recital next week",
        "notes": "", "flexibility": 0.5, "desired_item": "guitar"}},
    {"userId": "a", "normalized": {
        "urgency": "low", "urgency_reason": "no rush",
        "notes": "", "flexibility": 0.5, "desired_item": "camera"}},
]


class FakeHTTP:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": json.dumps(self.payload)}}]}


def run_pipeline(monkeypatch, reply):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(ev.requests, "post", lambda *a, **k: FakeHTTP(reply))

    from cycle_arbitration import build_context

    G = listing_graph()
    labels = build_labels(list(G.nodes()), NAMES)
    arbiter = make_ai_arbiter(labels, ev.evaluate_candidates, {"guitar", "camera"})
    cycles, _, decisions = select_cycles(
        G, 4, build_context(PREFS), arbiter, log=lambda *_: None
    )
    db = FakeDB()
    bridge.save_matches(db, G, cycles, decisions)
    return cycles, decisions, db.collections["matches"]


def test_realistic_ai_reply_is_accepted_and_saved(monkeypatch):
    # candidate order offered to the AI: best utility first (Aiden's cycle),
    # so candidate 2 is the one containing Bella.
    reply = {
        "recommended_candidate": 2,
        "reason": "Bella has a recital next week, so her urgency is high.",
        "qualitative_factors_considered": ["Bella urgency: recital next week"],
        "limitations": ["Urgency is self-reported."],
        "suggested_adjustment": None,
        "confidence": 0.85,
    }
    cycles, decisions, matches = run_pipeline(monkeypatch, reply)

    assert {frozenset(c) for c in cycles} == {
        frozenset({"x", "b", "y"}),
        frozenset({"a", "p", "q"}),      # the loser was placed elsewhere
    }
    assert len(matches) == 2
    with_ai = [m for m in matches.values() if "aiEvaluation" in m]
    without_ai = [m for m in matches.values() if "aiEvaluation" not in m]
    assert len(with_ai) == 1 and len(without_ai) == 1
    ai = with_ai[0]["aiEvaluation"]
    assert "Bella" in ai["reason"]
    assert ai["confidence"] == 0.85
    assert set(with_ai[0]["cycle"]) == {"x", "b", "y"}
    for m in matches.values():
        assert m["status"] == "pending"
        assert len(m["exchanges"]) == len(m["cycle"])


def test_reply_citing_a_user_outside_the_cycle_is_rejected_and_falls_back(monkeypatch):
    bad = {
        "recommended_candidate": 2,
        "reason": "Bella has high urgency, and Priya's need is high too.",
        "qualitative_factors_considered": ["urgency"],
        "limitations": [],
        "suggested_adjustment": None,
        "confidence": 0.9,
    }
    cycles, decisions, matches = run_pipeline(monkeypatch, bad)

    # validation failed -> plain BGCC choice (Aiden's higher-utility cycle)
    assert decisions == {}
    assert any({"x", "a", "y"} == set(c) for c in cycles)
    assert all("aiEvaluation" not in m for m in matches.values())


def test_reply_recommending_a_candidate_that_was_not_offered_is_rejected(monkeypatch):
    bad = {
        "recommended_candidate": 7,
        "reason": "Bella has high urgency.",
        "qualitative_factors_considered": ["urgency"],
        "limitations": [],
        "suggested_adjustment": None,
        "confidence": 0.9,
    }
    cycles, decisions, _ = run_pipeline(monkeypatch, bad)
    assert decisions == {}


def test_comparison_naming_the_displaced_user_is_rejected_for_privacy(monkeypatch):
    """
    "Bella needs it more than Aiden" would show Aiden's private context to
    people who are not in his cycle, so the validator rejects it and the
    pipeline falls back to plain BGCC.
    """
    comparing = {
        "recommended_candidate": 2,
        "reason": "Bella has a recital next week, while Aiden has no rush.",
        "qualitative_factors_considered": ["Bella urgency"],
        "limitations": [],
        "suggested_adjustment": None,
        "confidence": 0.9,
    }
    cycles, decisions, _ = run_pipeline(monkeypatch, comparing)
    assert decisions == {}
