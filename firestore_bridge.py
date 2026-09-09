"""
firestore_bridge.py

Manual bridge between the SwapCycle Flutter app (Firestore) and the
existing Python matching pipeline (ai_preference.py, bgcc_prototype.py,
ai_cycle_evaluator.py).

Why manual, not a Cloud Function trigger:
Cloud Functions (including Firestore triggers) require the Blaze plan
because they depend on Cloud Build / Artifact Registry. This project is
on Spark, so this script does the same job by hand: run it whenever you
want to process newly-submitted preferences. Swapping this for a real
onCreate trigger later is a one-file change once Blaze is available —
noted as future work, same pattern as the CV pillar in the checklist.

Usage:
    python firestore_bridge.py            # process + write matches
    python firestore_bridge.py --dry-run  # process, print, write nothing

Requires:
    pip install firebase-admin
    A service account key downloaded from:
      Firebase Console -> Project Settings -> Service accounts
      -> Generate new private key
    Saved as serviceAccountKey.json in this same folder.
    NEVER commit serviceAccountKey.json — add it to .gitignore.
"""

import argparse
import os
import sys

import firebase_admin
import networkx as nx
from firebase_admin import credentials, firestore

from ai_preference import normalize_preference
from bgcc_prototype import (
    bounded_greedy_cycle_cover,
    cycle_edges,
    cycle_weight,
    egalitarian_score,
    find_cycles,
)

try:
    from ai_cycle_evaluator import evaluate_candidates
    AI_EVALUATOR_AVAILABLE = True
except Exception:
    AI_EVALUATOR_AVAILABLE = False


SERVICE_ACCOUNT_PATH = os.getenv("SERVICE_ACCOUNT_PATH", "serviceAccountKey.json")

# Deterministic utility engine: converts a structured preference + a
# candidate listing into an edge weight. No LLM involved here — this is
# the "DETERMINISTIC UTILITY ENGINE" component from the pipeline diagram.
CONDITION_RANK = {"fair": 1, "good": 2, "like_new": 3, "new": 4, "any": 0}
EDGE_WEIGHT_THRESHOLD = 0.5  # below this, we don't consider it a real edge


def meets_min_condition(actual_condition, minimum_condition):
    return CONDITION_RANK.get(actual_condition, 0) >= CONDITION_RANK.get(minimum_condition, 0)


def compute_edge_weight(preference, listing):
    """Deterministic score for 'listing satisfies preference'. 0.0-1.0."""
    weight = 0.3

    if listing["category"].strip().lower() == preference["item_category"].strip().lower():
        weight += 0.35
    else:
        # category mismatch is close to disqualifying, but keyword overlap
        # can still rescue a partial match
        item_text = f"{listing['item']} {listing['brand']}".lower()
        if any(k.lower() in item_text for k in preference.get("keywords", [])):
            weight += 0.15
        else:
            weight -= 0.2

    brands = [b.lower() for b in preference.get("acceptable_brands", [])]
    if brands and listing["brand"].lower() in brands:
        weight += 0.1

    if meets_min_condition(listing["condition"], preference["minimum_condition"]):
        weight += 0.15
    else:
        weight -= 0.25

    weight += preference.get("flexibility", 0.0) * 0.1

    return max(0.0, min(1.0, round(weight, 2)))


def init_firestore():
    if not os.path.exists(SERVICE_ACCOUNT_PATH):
        sys.exit(
            f"Missing {SERVICE_ACCOUNT_PATH}. Download it from Firebase "
            "Console -> Project Settings -> Service accounts -> "
            "Generate new private key, and place it next to this script."
        )
    cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
    firebase_admin.initialize_app(cred)
    return firestore.client()


def fetch_listings(db):
    listings = []
    for doc in db.collection("listings").where("status", "==", "active").stream():
        data = doc.to_dict()
        data["id"] = doc.id
        listings.append(data)
    return listings


def fetch_pending_preferences(db):
    return list(db.collection("preferences").where("status", "==", "pending").stream())


def normalize_pending(db, pending_docs, dry_run):
    processed = []
    for doc in pending_docs:
        data = doc.to_dict()
        raw_text = data.get("rawText", "")
        print(f"  Normalizing preference {doc.id} (user {data.get('userId')}): {raw_text!r}")
        try:
            normalized = normalize_preference(raw_text)
        except Exception as exc:
            print(f"    FAILED: {exc}")
            if not dry_run:
                doc.reference.update({"status": "error", "error": str(exc)})
            continue

        if not dry_run:
            doc.reference.update({"normalized": normalized, "status": "processed"})

        processed.append({
            "id": doc.id,
            "userId": data.get("userId"),
            "normalized": normalized,
            "notes": normalized.get("notes", ""),
        })
    return processed


def build_graph(listings, processed_prefs):
    """
    One directed edge per (buyer, seller) pair, weight = best-matching
    listing that seller owns for the buyer's stated preference. Buyers
    who own nothing, or whose preference matches nothing above the
    threshold, simply get no outgoing edge (unmatched).
    """
    G = nx.DiGraph()

    listings_by_owner = {}
    for listing in listings:
        listings_by_owner.setdefault(listing["ownerId"], []).append(listing)

    for pref in processed_prefs:
        G.add_node(pref["userId"])
    for listing in listings:
        G.add_node(listing["ownerId"])

    for pref in processed_prefs:
        buyer = pref["userId"]
        best_seller, best_weight, best_listing = None, 0.0, None

        for listing in listings:
            if listing["ownerId"] == buyer:
                continue  # can't trade with yourself
            w = compute_edge_weight(pref["normalized"], listing)
            if w > best_weight:
                best_seller, best_weight, best_listing = listing["ownerId"], w, listing

        if best_seller and best_weight >= EDGE_WEIGHT_THRESHOLD:
            G.add_edge(
                buyer, best_seller,
                weight=best_weight,
                item=best_listing["item"],
                listingId=best_listing["id"],
            )

    return G


def build_qualitative_context(processed_prefs):
    """
    Best-effort qualitative context for the AI evaluator, sourced from
    the free-text 'notes' field normalize_preference() already extracts.
    Structured urgency/priority/distance fields don't exist in the
    current Firestore schema yet -- flagged here as a known gap, not
    silently guessed at.
    """
    context = {}
    for pref in processed_prefs:
        context[pref["userId"]] = {
            "urgency": "not specified",
            "condition_notes": pref["notes"] or "not specified",
            "priority": "not specified",
            "collection_distance": "not specified",
        }
    return context


def run_matching(G, max_len=4):
    matched, unmatched = bounded_greedy_cycle_cover(G, max_len)
    all_cycles = find_cycles(G, max_len)
    return matched, unmatched, all_cycles


def write_match(db, G, cycle, processed_prefs, all_cycles, dry_run):
    listing_ids = [G[u][v]["listingId"] for u, v in cycle_edges(cycle)]
    total_utility = cycle_weight(G, cycle)
    fairness = egalitarian_score(G, cycle)

    match_doc = {
        "cycle": cycle,
        "listingIds": listing_ids,
        "totalUtility": round(total_utility, 2),
        "egalitarianScore": round(fairness, 2),
        "algorithm": "BGCC",
        "status": "pending",
    }

    # Only call the AI evaluator when there's a genuine choice to make --
    # multiple valid cycles sharing a participant with this one. A single
    # obvious cycle doesn't need advisory reasoning.
    overlapping = [c for c in all_cycles if set(c) & set(cycle)]
    if AI_EVALUATOR_AVAILABLE and os.getenv("OPENROUTER_API_KEY") and len(overlapping) > 1:
        candidates = [
            {"cycle": c, "total_utility": round(cycle_weight(G, c), 2),
             "egalitarian_score": round(egalitarian_score(G, c), 2)}
            for c in overlapping
        ]
        preferences = {p["userId"]: p["normalized"] for p in processed_prefs}
        qualitative_context = build_qualitative_context(processed_prefs)
        try:
            ai_result = evaluate_candidates(preferences, candidates, qualitative_context)
            match_doc["aiRecommendation"] = ai_result
            print(f"    AI evaluation: {ai_result['reason']}")
        except Exception as exc:
            print(f"    AI evaluator skipped (error): {exc}")

    print(f"  MATCH: {' -> '.join(cycle)} -> {cycle[0]} "
          f"| utility={total_utility:.2f} fairness={fairness:.2f}")

    if not dry_run:
        db.collection("matches").add(match_doc)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                         help="Process and print, but write nothing to Firestore.")
    args = parser.parse_args()

    print("=" * 70)
    print("SWAPCYCLE FIRESTORE BRIDGE")
    print("=" * 70)

    db = init_firestore()

    print("\n[1] Fetching active listings...")
    listings = fetch_listings(db)
    print(f"    {len(listings)} active listing(s) found.")

    print("\n[2] Fetching pending preferences...")
    pending = fetch_pending_preferences(db)
    print(f"    {len(pending)} pending preference(s) found.")
    if not pending:
        print("\nNothing to process. Exiting.")
        return

    print("\n[3] Normalizing preferences via AI...")
    processed_prefs = normalize_pending(db, pending, args.dry_run)
    if not processed_prefs:
        print("\nNo preferences normalized successfully. Exiting.")
        return

    print("\n[4] Building weighted exchange graph...")
    G = build_graph(listings, processed_prefs)
    print(f"    {G.number_of_nodes()} nodes, {G.number_of_edges()} edges.")

    print("\n[5] Running BGCC matching...")
    matched, unmatched, all_cycles = run_matching(G)
    print(f"    {len(matched)} cycle(s) matched, {len(unmatched)} user(s) unmatched.")

    if not matched:
        print("\nNo valid exchange cycles found this run.")
        return

    print("\n[6] Writing match results" + (" (dry run, not writing)" if args.dry_run else "") + "...")
    for cycle in matched:
        write_match(db, G, cycle, processed_prefs, all_cycles, args.dry_run)

    print("\n" + "=" * 70)
    print("BRIDGE RUN COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
