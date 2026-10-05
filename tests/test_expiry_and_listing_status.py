"""Stale pending matches expire; listing status follows the matches."""

from datetime import datetime, timedelta, timezone

import firestore_bridge as bridge

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


class Snap:
    def __init__(self, store, key):
        self.id, self._store = key, store

    @property
    def exists(self):
        return self.id in self._store

    def to_dict(self):
        return dict(self._store[self.id])


class Ref:
    def __init__(self, store, key):
        self.store, self.key = store, key

    def get(self):
        return Snap(self.store, self.key)

    def update(self, data):
        self.store[self.key].update(data)


class Coll:
    def __init__(self, store, rows=None):
        self.store = store
        self.rows = list(store) if rows is None else rows

    def document(self, key):
        return Ref(self.store, key)

    def where(self, field, op, value):
        ok = (lambda v: v in value) if op == "in" else (lambda v: v == value)
        return Coll(self.store, [k for k in self.rows
                                 if ok(self.store[k].get(field))])

    def stream(self):
        return [Snap(self.store, k) for k in self.rows]


class DB:
    def __init__(self, matches=None, listings=None):
        self.data = {"matches": matches or {}, "listings": listings or {}}

    def collection(self, name):
        return Coll(self.data[name])


def match(status, ids, **kw):
    return {"status": status, "cycle": ["a", "b"], "listingIds": ids, **kw}


# ---------------------------------------------------------------- expiry

def test_pending_match_past_expiresat_expires():
    db = DB(matches={"m": match("pending", [], expiresAt=NOW - timedelta(minutes=1))})
    assert bridge.expire_stale_matches(db, now=NOW) == 1
    assert db.data["matches"]["m"]["status"] == "expired"


def test_pending_match_before_expiresat_is_left_alone():
    db = DB(matches={"m": match("pending", [], expiresAt=NOW + timedelta(hours=1))})
    assert bridge.expire_stale_matches(db, now=NOW) == 0
    assert db.data["matches"]["m"]["status"] == "pending"


def test_only_pending_matches_expire():
    old = NOW - timedelta(days=30)
    db = DB(matches={
        "c": match("confirmed", [], expiresAt=old),
        "d": match("completed", [], expiresAt=old),
    })
    assert bridge.expire_stale_matches(db, now=NOW) == 0


def test_legacy_match_without_expiresat_uses_created_at():
    ttl = timedelta(hours=bridge.MATCH_TTL_HOURS)
    db = DB(matches={
        "old": match("pending", [], createdAt=NOW - ttl - timedelta(hours=1)),
        "new": match("pending", [], createdAt=NOW - timedelta(hours=1)),
        "none": match("pending", []),
    })
    assert bridge.expire_stale_matches(db, now=NOW) == 1
    assert db.data["matches"]["old"]["status"] == "expired"
    assert db.data["matches"]["new"]["status"] == "pending"


def test_expired_match_frees_its_members_and_listings():
    db = DB(matches={"m": match("pending", ["L1"], expiresAt=NOW - timedelta(hours=1))})
    bridge.expire_stale_matches(db, now=NOW)
    users, listings, _ = bridge.fetch_locked_state(db)
    assert users == set() and listings == set()


# ------------------------------------------------------- listing statuses

def L(status="active"):
    return {"status": status, "ownerId": "a", "item": "x"}


def test_open_match_marks_listings_in_trade():
    db = DB(matches={"m": match("pending", ["L1", "L2"])},
            listings={"L1": L(), "L2": L(), "L3": L()})
    assert bridge.sync_listing_statuses(db) == 2
    s = {k: v["status"] for k, v in db.data["listings"].items()}
    assert s == {"L1": "in_trade", "L2": "in_trade", "L3": "active"}


def test_completed_match_marks_listings_traded():
    db = DB(matches={"m": match("completed", ["L1"])},
            listings={"L1": L("in_trade")})
    bridge.sync_listing_statuses(db)
    assert db.data["listings"]["L1"]["status"] == "traded"


def test_declined_or_expired_match_releases_listings():
    db = DB(matches={"m": match("declined", ["L1"]), "n": match("expired", ["L2"])},
            listings={"L1": L("in_trade"), "L2": L("in_trade")})
    bridge.sync_listing_statuses(db)
    assert {v["status"] for v in db.data["listings"].values()} == {"active"}


def test_listing_in_another_open_match_stays_in_trade():
    db = DB(matches={"m": match("declined", ["L1"]), "n": match("pending", ["L1"])},
            listings={"L1": L("in_trade")})
    bridge.sync_listing_statuses(db)
    assert db.data["listings"]["L1"]["status"] == "in_trade"


def test_traded_listings_never_revert():
    db = DB(matches={}, listings={"L1": L("traded")})
    assert bridge.sync_listing_statuses(db) == 0
    assert db.data["listings"]["L1"]["status"] == "traded"


def test_sync_is_idempotent():
    db = DB(matches={"m": match("confirmed", ["L1"])}, listings={"L1": L()})
    bridge.sync_listing_statuses(db)
    assert bridge.sync_listing_statuses(db) == 0


def test_new_matches_get_an_expiry_deadline():
    from test_bridge_integration import FakeDB as SaveDB
    import networkx as nx

    G = nx.DiGraph()
    G.add_edge("a", "b", weight=0.9, listingId="Lb", item="guitar", category="g", brand="")
    G.add_edge("b", "a", weight=0.8, listingId="La", item="camera", category="c", brand="")
    db = SaveDB()
    assert bridge.save_matches(db, G, [["a", "b"]]) == 1
    saved = next(iter(db.collections["matches"].values()))
    delta = saved["expiresAt"] - datetime.now(timezone.utc)
    assert abs(delta - timedelta(hours=bridge.MATCH_TTL_HOURS)) < timedelta(minutes=1)
