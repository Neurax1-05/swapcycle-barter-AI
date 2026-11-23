import threading
import time

import firestore_bridge as bridge


class Ref:
    def __init__(self, store, key):
        self.store, self.key = store, key

    def update(self, data):
        self.store.setdefault(self.key, {}).update(data)


class DB:
    def __init__(self):
        self.prefs = {}

    def collection(self, name):
        assert name == "preferences"
        db = self

        class C:
            def document(self, key):
                return Ref(db.prefs, key)

        return C()


def prefs(n):
    return [{"id": f"p{i}", "rawText": f"want {i}"} for i in range(n)]


def test_calls_run_concurrently(monkeypatch):
    live, peak = 0, 0
    lock = threading.Lock()

    def slow(p):
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
        time.sleep(0.05)
        with lock:
            live -= 1
        return {"desired_item": p["rawText"]}

    monkeypatch.setattr(bridge, "_normalize_one", slow)
    db = DB()
    out = bridge.normalize_pending(db, prefs(8))
    assert len(out) == 8 and peak > 1
    assert all(v["status"] == "processed" for v in db.prefs.values())


def test_failures_are_counted_then_marked_failed(monkeypatch):
    def boom(p):
        raise RuntimeError("llm down")

    monkeypatch.setattr(bridge, "_normalize_one", boom)
    db = DB()
    p = prefs(1)
    for attempt in range(1, bridge.MAX_NORMALIZE_ATTEMPTS + 1):
        assert bridge.normalize_pending(db, p) == []
        assert db.prefs["p0"]["normalizeAttempts"] == attempt
        p[0]["normalizeAttempts"] = attempt  # what the next fetch would return
    assert db.prefs["p0"]["status"] == "failed"


def test_time_budget_leaves_rest_pending(monkeypatch):
    monkeypatch.setattr(bridge, "NORMALIZE_BUDGET_SECONDS", -1)
    monkeypatch.setattr(bridge, "_normalize_one", lambda p: {"x": 1})
    db = DB()
    assert bridge.normalize_pending(db, prefs(3)) == []
    assert db.prefs == {}  # untouched, still 'pending' in Firestore
