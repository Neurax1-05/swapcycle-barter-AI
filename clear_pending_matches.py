"""One-off cleanup: delete duplicate PENDING matches left by the old bug.

Only matches whose status is "pending" are touched. Confirmed, completed and
declined matches are never deleted.

    python clear_pending_matches.py            # list only (nothing deleted)
    python clear_pending_matches.py --delete   # asks for YES, then deletes

After this, users are free again and the next run creates ONE fresh match.
"""
import argparse

import firestore_bridge as bridge


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--delete", action="store_true")
    args = parser.parse_args()

    db = bridge.initialize_firebase()
    docs = list(
        db.collection("matches").where("status", "==", "pending").stream()
    )

    if not docs:
        print("No pending matches.")
        return

    print(f"{len(docs)} pending match(es):")
    for doc in docs:
        data = doc.to_dict() or {}
        print(f"  {doc.id}  cycle={data.get('cycle')}  "
              f"listings={data.get('listingIds')}")

    if not args.delete:
        print("\nNothing deleted. Re-run with --delete to remove them.")
        return

    if input("\nType YES to delete these pending matches: ").strip() != "YES":
        print("Cancelled.")
        return

    for doc in docs:
        doc.reference.delete()
    print(f"Deleted {len(docs)} pending match(es).")


if __name__ == "__main__":
    main()
