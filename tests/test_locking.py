"""Users/listings already in a trade must not be matched again.

Regression test for: the listener re-matched the same people on every run,
producing several pending matches (duplicate confirm/decline cards).
"""

from datetime import datetime, timezone

import firestore_bridge as bridge


def ts(n):
    return datetime.fromtimestamp(n, tz=timezone.utc)


class Doc:
    def __init__(self, data):
        self._d = data

    def to_dict(self):
        return self._d


class MatchesCollection:
    def __init__(self, rows):
        self.rows = rows
        self.asked = None

    def where(self, field, op, value):
        assert (field, op) == ("status", "in")
        self.asked = value
        self.rows = [r for r in self.rows if r.get("status") in value]
        return self

    def stream(self):
        return [Doc(r) for r in self.rows]


class DB:
    def __init__(self, rows):
        self.matches = MatchesCollection(rows)

    def collection(self, name):
        assert name == "matches"
        return self.matches


MATCHES = [
    {"status": "pending", "cycle": ["a", "b", "c"],
     "listingIds": ["La", "Lb", "Lc"], "createdAt": ts(100)},
    {"status": "confirmed", "cycle": ["d", "e"],
     "listingIds": ["Ld", "Le"], "createdAt": ts(100)},
    {"status": "completed", "cycle": ["f", "g"],
     "listingIds": ["Lf", "Lg"], "createdAt": ts(100)},
    {"status": "declined", "cycle": ["h", "i"],
     "listingIds": ["Lh", "Li"], "createdAt": ts(100)},
]


def test_fetch_locked_state_by_status():
    users, listings, cutoffs = bridge.fetch_locked_state(DB(MATCHES))

    assert users == {"a", "b", "c", "d", "e"}          # open matches only
    assert listings == {"La", "Lb", "Lc", "Ld", "Le", "Lf", "Lg"}
    assert set(cutoffs) == {"f", "g"}                   # completed only
    assert "h" not in users and "Lh" not in listings    # declined is free


def L(i, owner):
    return {"id": i, "ownerId": owner, "item": "x", "status": "active"}


def P(uid, when):
    return {"userId": uid, "submittedAt": ts(when)}


def test_open_match_members_and_listings_are_excluded():
    listings = [L("La", "a"), L("Lz", "z"), L("Lnew", "a")]
    prefs = [P("a", 200), P("z", 200)]

    ls, ps = bridge.apply_locks(listings, prefs, {"a"}, {"La"}, {})

    assert [x["id"] for x in ls] == ["Lz"]          # a's other listing too
    assert [x["userId"] for x in ps] == ["z"]


def test_completed_trade_uses_up_old_preference_but_not_a_new_one():
    prefs = [P("f", 50), P("f", 100), P("g", 500)]

    _, ps = bridge.apply_locks([], prefs, set(), set(), {"f": 100, "g": 100})

    # f's preferences at/before the completed match are used up;
    # g asked again after it completed, so that one counts.
    assert [(p["userId"], p["submittedAt"]) for p in ps] == [("g", ts(500))]


def test_declined_and_unrelated_users_are_untouched():
    listings = [L("Lh", "h"), L("Lz", "z")]
    prefs = [P("h", 10), P("z", 10)]

    users, locked, cutoffs = bridge.fetch_locked_state(DB(MATCHES))
    ls, ps = bridge.apply_locks(listings, prefs, users, locked, cutoffs)

    assert len(ls) == 2 and len(ps) == 2


def test_second_run_with_same_data_finds_nothing_new(monkeypatch):
    """The reported bug: everyone already matched, listener runs again."""
    listings = [L("La", "a"), L("Lb", "b"), L("Lc", "c")]
    prefs = [P("a", 1), P("b", 1), P("c", 1)]

    users, locked, cutoffs = bridge.fetch_locked_state(DB(MATCHES))
    ls, ps = bridge.apply_locks(listings, prefs, users, locked, cutoffs)

    assert ls == [] and ps == []
