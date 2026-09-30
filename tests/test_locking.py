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


# ---------------------------------------------------------------------------
# Declined trades: people are freed, the same swap is not offered again
# ---------------------------------------------------------------------------

import networkx as nx

from cycle_arbitration import select_cycles


class DeclinedDB:
    def __init__(self, rows):
        self.rows = rows

    def collection(self, name):
        assert name == "matches"
        return self

    def where(self, field, op, value):
        assert (field, op, value) == ("status", "==", "declined")
        return self

    def stream(self):
        return [Doc(r) for r in self.rows]


def exchanges():
    return [
        {"fromUser": "a", "toUser": "b", "listingId": "Lb", "weight": 0.9},
        {"fromUser": "b", "toUser": "c", "listingId": "Lc", "weight": 0.9},
        {"fromUser": "c", "toUser": "a", "listingId": "La", "weight": 0.9},
    ]


def test_declinedBy_bans_only_the_decliners_edge():
    rows = [{"status": "declined", "declinedBy": "a", "exchanges": exchanges()}]

    assert bridge.fetch_declined_edges(DeclinedDB(rows)) == {("a", "b", "Lb")}


def test_legacy_decline_without_declinedBy_bans_weakest_edge():
    ex = exchanges()
    ex[1]["weight"] = 0.4
    rows = [{"status": "declined", "exchanges": ex}]

    assert bridge.fetch_declined_edges(DeclinedDB(rows)) == {("b", "c", "Lc")}


def test_declined_swap_is_not_reproposed_but_the_others_are_freed():
    """a declines a->b->c->a. b and c must still be matchable together."""
    G = nx.DiGraph()
    G.add_edge("a", "b", weight=0.9, listingId="Lb", item="x")
    G.add_edge("b", "c", weight=0.9, listingId="Lc", item="y")
    G.add_edge("c", "a", weight=0.9, listingId="La", item="z")
    G.add_edge("c", "b", weight=0.8, listingId="Lb2", item="w")   # alternative

    # Before the decline the best cycle is the 3-way.
    before, _, _ = select_cycles(G.copy(), max_len=4, context={}, arbiter=None)
    assert [set(c) for c in before] == [{"a", "b", "c"}]

    banned = bridge.fetch_declined_edges(DeclinedDB(
        [{"status": "declined", "declinedBy": "a", "exchanges": exchanges()}]
    ))
    assert bridge.remove_declined_edges(G, banned) == 1

    after, _, _ = select_cycles(G, max_len=4, context={}, arbiter=None)
    assert [set(c) for c in after] == [{"b", "c"}]      # b and c are free


def test_ban_ignored_when_that_listing_is_no_longer_the_edge():
    G = nx.DiGraph()
    G.add_edge("a", "b", weight=0.9, listingId="OTHER", item="x")

    assert bridge.remove_declined_edges(G, {("a", "b", "Lb")}) == 0
    assert G.has_edge("a", "b")
