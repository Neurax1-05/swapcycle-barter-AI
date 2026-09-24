"""Urgency extraction in the Gemini #1 preference normalizer (API mocked)."""

import json

import pytest

import ai_preference


class FakeResponse:
    ok = True
    status_code = 200
    text = ""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return {"choices": [{"message": {"content": json.dumps(self._payload)}}]}


BASE = {
    "item_category": "guitar",
    "desired_item": "acoustic guitar",
    "acceptable_brands": ["Yamaha"],
    "minimum_condition": "good",
    "budget_or_value_signal": 0.2,
    "flexibility": 0.4,
    "keywords": ["guitar"],
    "notes": "",
}


@pytest.fixture
def run(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    def _run(extra):
        payload = {**BASE, **extra}
        monkeypatch.setattr(
            ai_preference.requests, "post",
            lambda *a, **k: FakeResponse(payload),
        )
        return ai_preference.normalize_preference("I want a Yamaha guitar")

    return _run


def test_stated_urgency_is_kept(run):
    out = run({"urgency": "high", "urgency_reason": "recital next week"})
    assert out["urgency"] == "high"
    assert out["urgency_reason"] == "recital next week"


def test_missing_urgency_defaults_to_none(run):
    out = run({})
    assert out["urgency"] == "none" and out["urgency_reason"] == ""


def test_invalid_urgency_value_becomes_none(run):
    out = run({"urgency": "URGENT!!!", "urgency_reason": "trust me"})
    assert out["urgency"] == "none" and out["urgency_reason"] == ""


def test_reason_dropped_when_urgency_is_none(run):
    out = run({"urgency": "none", "urgency_reason": "made up"})
    assert out["urgency_reason"] == ""


def test_urgency_is_case_insensitive(run):
    assert run({"urgency": " Medium ", "urgency_reason": "exam"})["urgency"] == "medium"
