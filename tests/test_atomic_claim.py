"""Atomic claim + single-flight run lock, against an in-memory fake.

The fake runs each 'transaction' serially, which is exactly the guarantee
Firestore transactions give (a conflicting concurrent transaction retries and
then sees the other's writes). So these tests check the LOGIC of the claim:
a user can never be in two open matches, and locks free themselves.
"""
from datetime import datetime, timedelta, timezone

import pytest

import firestore_bridge as bridge


class Snap:
    def __init__(self, id_, data):
        self.id, self._d = id_, data

    @property
    def exists(self):
        return self._d is not None

    def to_dict(self):
        return dict(self._d) if self._d is not None else None


class Ref:
    def __init__(self, db, coll, id_):
        self.db, self.coll, self.id = db, coll, id_

    def get(self, transaction=None):
        return Snap(self.id, self.db.data.setdefault(self.coll, {}).get(self.id))

    def set(self, data):
        self.db.data.setdefault(self.coll, {})[self.id] = dict(data)

    def update(self, data):
        self.db.data[self.coll][self.id].update(data)


class Txn:
    def set(self, ref, data):
        ref.set(data)

    def update(self, ref, data):
        ref.update(data)


class Coll:
    def __init__(self, db, name):
        self.db, self.name = db, name

    def document(self, id_):
        return Ref(self.db, self.name, id_)


class DB:
    def __init__(self):
        self.data = {}

    def collection(self, name):
        return Coll(self, name)

    def transaction(self):
        return Txn()


@pytest.fixture(autouse=True)
def passthrough_transactional(monkeypatch):
    monkeypatch.setattr(bridge.firestore, "transactional", lambda f: f)


def claim(db, mid, cycle):
    ref = db.collection("matches").document(mid)
    return bridge.claim_and_write_match(db, ref, {"cycle": cycle, "status": "pending"}, cycle)


def test_second_overlapping_match_is_refused():
    db = DB()
    assert claim(db, "M1", ["a", "b"]) == "saved"
    assert claim(db, "M2", ["b", "c"]) == "locked"      # b already in M1
    assert "M2" not in db.data["matches"]
    assert claim(db, "M3", ["x", "y"]) == "saved"       # disjoint is fine


def test_same_match_twice_is_idempotent():
    db = DB()
    assert claim(db, "M1", ["a", "b"]) == "saved"
    assert claim(db, "M1", ["a", "b"]) == "exists"


@pytest.mark.parametrize("status", ["declined", "expired", "completed"])
def test_lock_frees_itself_when_match_closes(status):
    db = DB()
    claim(db, "M1", ["a", "b"])
    db.data["matches"]["M1"]["status"] = status
    assert claim(db, "M2", ["b", "c"]) == "saved"


@pytest.mark.parametrize("status", ["pending", "confirmed"])
def test_lock_holds_while_match_open(status):
    db = DB()
    claim(db, "M1", ["a", "b"])
    db.data["matches"]["M1"]["status"] = status
    assert claim(db, "M2", ["b", "c"]) == "locked"


def test_lock_pointing_at_deleted_match_is_ignored():
    db = DB()
    claim(db, "M1", ["a", "b"])
    del db.data["matches"]["M1"]
    assert claim(db, "M2", ["b", "c"]) == "saved"


# ---------------- run lock ----------------

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def test_run_lock_single_flight_and_rerun_flag():
    db = DB()
    assert bridge.acquire_run_lock(db, "A", now=NOW) is True
    assert bridge.acquire_run_lock(db, "B", now=NOW) is False   # B backs off
    assert db.data["system"]["matchingRun"]["rerunRequested"] is True
    assert bridge.release_run_lock(db, "A") is True             # A told to re-run
    assert bridge.acquire_run_lock(db, "B", now=NOW) is True


def test_expired_lease_can_be_taken_over():
    db = DB()
    bridge.acquire_run_lock(db, "A", now=NOW, lease_seconds=60)
    later = NOW + timedelta(seconds=120)
    assert bridge.acquire_run_lock(db, "B", now=later) is True


def test_release_by_non_owner_is_noop():
    db = DB()
    bridge.acquire_run_lock(db, "A", now=NOW)
    assert bridge.release_run_lock(db, "B") is False
    assert db.data["system"]["matchingRun"]["owner"] == "A"


def test_run_matching_skips_when_locked(monkeypatch):
    db = DB()
    bridge.acquire_run_lock(db, "someone-else")
    called = []
    monkeypatch.setattr(bridge, "_run_matching_once", lambda *a, **k: called.append(1) or {})
    out = bridge.run_matching(db)
    assert out["status"] == "skipped_locked" and not called


def test_run_matching_reruns_when_requested(monkeypatch):
    db = DB()
    calls = []

    def once(db_, **k):
        calls.append(1)
        if len(calls) == 1:           # a trigger lands mid-run
            bridge.acquire_run_lock(db_, "late-trigger")
        return {"status": "ok", "matched_cycles": 0}

    monkeypatch.setattr(bridge, "_run_matching_once", once)
    bridge.run_matching(db)
    assert len(calls) == 2
    assert db.data["system"]["matchingRun"]["owner"] is None  # released
