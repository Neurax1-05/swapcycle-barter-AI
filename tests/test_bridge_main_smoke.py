"""
Smoke test of firestore_bridge.main() with Firestore and OpenRouter replaced by
fakes. Catches wiring mistakes (wrong variable names, bad arguments) that unit
tests of the individual pieces cannot.
"""

import json
import sys

import pytest

import ai_cycle_evaluator as ev
import firestore_bridge as bridge
from test_bridge_integration import FakeDB, FakeHTTP


def listing(i, owner, item, category):
    return {"id": f"L{i}", "ownerId": owner, "item": item, "category": category,
            "brand": "", "condition": "good", "status": "active"}


def pref(uid, category, urgency="none", reason=""):
    return {
        "id": f"P-{uid}", "userId": uid, "status": "processed",
        "rawText": f"I want a {category}",
        "normalized": {
            "item_category": category, "desired_item": category,
            "acceptable_brands": [], "minimum_condition": "any",
            "budget_or_value_signal": 0.0, "flexibility": 0.5,
            "keywords": [category], "notes": "",
            "urgency": urgency, "urgency_reason": reason,
        },
    }


# x owns guitar wants camera... two people (a, b) both want x's guitar.
LISTINGS = [
    listing(1, "x", "guitar", "guitar"),
    listing(2, "a", "camera", "camera"),
    listing(3, "b", "camera", "camera"),
    listing(4, "y", "bike", "bike"),
]
PREFS = [
    pref("x", "camera"),                       # x wants a camera (from a or b)
    pref("a", "bike"),
    pref("b", "bike", "high", "exam on Friday"),
    pref("y", "guitar"),
]


@pytest.fixture
def wired(monkeypatch):
    db = FakeDB()
    db.collection("users")  # ensure exists
    monkeypatch.setattr(bridge, "initialize_firebase", lambda: db)
    monkeypatch.setattr(bridge, "fetch_active_listings", lambda _db: LISTINGS)
    monkeypatch.setattr(bridge, "fetch_preferences", lambda _db: ([], PREFS))
    monkeypatch.setattr(bridge, "normalize_pending", lambda _db, pending: [])
    monkeypatch.setattr(bridge, "fetch_display_names",
                        lambda _db, uids: {"x": "Xena", "a": "Aiden", "b": "Bella", "y": "Yusuf"})
    return db


def run_main(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["firestore_bridge.py", *args])
    bridge.main()


def test_no_ai_flag_runs_plain_bgcc_and_saves(monkeypatch, wired):
    run_main(monkeypatch, "--no-ai")
    matches = wired.collections.get("matches", {})
    assert len(matches) >= 1
    assert all("aiEvaluation" not in m for m in matches.values())


def test_dry_run_writes_nothing(monkeypatch, wired):
    run_main(monkeypatch, "--dry-run", "--no-ai")
    assert wired.collections.get("matches", {}) == {}


def test_ai_arbitration_end_to_end(monkeypatch, wired):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    seen = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        seen["payload"] = json
        user = __import__("json").loads(json["messages"][1]["content"])
        # pick whichever candidate contains Bella
        idx = next(i for i, c in enumerate(user["candidates"], 1)
                   if "Bella" in c["cycle"])
        return FakeHTTP({
            "recommended_candidate": idx,
            "reason": "Bella has an exam on Friday, so her urgency is high.",
            "qualitative_factors_considered": ["Bella urgency: exam on Friday"],
            "limitations": ["Urgency is self-reported."],
            "suggested_adjustment": None,
            "confidence": 0.9,
        })

    monkeypatch.setattr(ev.requests, "post", fake_post)
    run_main(monkeypatch)

    matches = wired.collections["matches"]
    assert len(matches) == 1
    (m,) = matches.values()
    assert "b" in m["cycle"] and "a" not in m["cycle"]
    assert "Bella" in m["aiEvaluation"]["reason"]

    # the AI only ever saw readable names, never Firestore ids
    text = __import__("json").dumps(seen["payload"])
    assert "Bella" in text and "Aiden" in text
