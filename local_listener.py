"""Local stand-in for the Cloud Function (no Blaze plan needed).

Watches Firestore and runs the SAME pipeline as the Cloud Function
(firestore_bridge.run_matching) whenever a new preference document is
created. Leave it running in a terminal during demos and UAT sessions.

    python local_listener.py            # AI on
    python local_listener.py --no-ai    # plain BGCC only

Stop with Ctrl+C. Needs serviceAccountKey.json and .env (OPENROUTER_API_KEY)
in this folder, same as `python firestore_bridge.py`.
"""
import argparse
import threading
import time

import firestore_bridge as bridge

DEBOUNCE_SECONDS = 5  # wait for several people submitting at once


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-ai", action="store_true")
    parser.add_argument("--max-cycle-length", type=int, default=4)
    args = parser.parse_args()

    db = bridge.initialize_firebase()

    wake = threading.Event()
    first_snapshot = {"done": False}

    def on_preferences(_docs, changes, _read_time):
        # The first callback is the existing backlog: run once for it.
        # After that, react to ADDED only. The pipeline itself edits
        # preference docs (pending -> processed); those MODIFIED events
        # must not trigger another run.
        if not first_snapshot["done"]:
            first_snapshot["done"] = True
            print(f"Connected. {len(_docs)} preference(s) already stored; "
                  "processing any that are pending...")
            wake.set()
            return
        if any(c.type.name == "ADDED" for c in changes):
            print("New preference detected.")
            wake.set()

    watch = db.collection("preferences").on_snapshot(on_preferences)
    print("Listening for new preferences. Ctrl+C to stop.")

    try:
        while True:
            # Short timeout so Ctrl+C works on Windows (a bare wait() blocks it)
            if not wake.wait(timeout=1):
                continue
            time.sleep(DEBOUNCE_SECONDS)  # let simultaneous submissions land
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
        watch.unsubscribe()


if __name__ == "__main__":
    main()
