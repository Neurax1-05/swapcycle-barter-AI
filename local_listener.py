"""Local stand-in for the Cloud Function (no Blaze plan needed).

Watches Firestore and runs the SAME pipeline as the Cloud Function
(firestore_bridge.run_matching) when something happens that can change
who should be matched:

  * a new preference is created          (someone wants something)
  * a new listing is created             (something new is on offer)
  * a match is declined                  (people are freed for other cycles)

Leave it running in a terminal during demos and UAT sessions.

    python local_listener.py            # AI on
    python local_listener.py --no-ai    # plain BGCC only

Stop with Ctrl+C. Needs serviceAccountKey.json and .env (OPENROUTER_API_KEY)
in this folder, same as `python firestore_bridge.py`.
"""
import argparse
import threading
import time

import firestore_bridge as bridge

DEBOUNCE_SECONDS = 5  # wait for several changes landing at once

# Match statuses that free people up again.
FREEING_STATUSES = ("declined", "expired")


def is_trigger(collection, change):
    """Should this change start a matching run?"""

    kind = change.type.name

    if collection in ("preferences", "listings"):
        return kind == "ADDED"

    if collection == "matches":
        if kind != "MODIFIED":
            return False
        data = change.document.to_dict() or {}
        return data.get("status") in FREEING_STATUSES

    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-ai", action="store_true")
    parser.add_argument("--max-cycle-length", type=int, default=4)
    args = parser.parse_args()

    db = bridge.initialize_firebase()

    wake = threading.Event()
    seen_first = {}

    def make_callback(collection):

        def callback(docs, changes, _read_time):
            # The first callback per collection is the existing data.
            # Only the preferences one triggers a run (to process any
            # backlog); after that, react to real changes only. The
            # pipeline itself edits preference docs (pending ->
            # processed); those MODIFIED events must not loop.
            if not seen_first.get(collection):
                seen_first[collection] = True
                if collection == "preferences":
                    print(f"Connected. {len(docs)} preference(s) already "
                          "stored; processing any that are pending...")
                    wake.set()
                return

            if any(is_trigger(collection, c) for c in changes):
                print(f"Change in '{collection}' detected.")
                wake.set()

        return callback

    watches = [
        db.collection(name).on_snapshot(make_callback(name))
        for name in ("preferences", "listings", "matches")
    ]
    print("Listening for new preferences, new listings and declined "
          "matches. Ctrl+C to stop.")

    try:
        while True:
            # Short timeout so Ctrl+C works on Windows.
            if not wake.wait(timeout=1):
                continue
            time.sleep(DEBOUNCE_SECONDS)  # let simultaneous changes land
            wake.clear()
            try:
                summary = bridge.run_matching(
                    db,
                    no_ai=args.no_ai,
                    max_cycle_length=args.max_cycle_length,
                )
                print(f"Matching finished: {summary}")
            except Exception as exc:  # keep listening after a failed run
                print(f"Matching run failed: {exc!r}")
    except KeyboardInterrupt:
        print("Stopping.")
    finally:
        for w in watches:
            w.unsubscribe()


if __name__ == "__main__":
    main()
