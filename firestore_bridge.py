import argparse
import hashlib
import os
import sys

import firebase_admin
import networkx as nx
from firebase_admin import credentials, firestore

from ai_preference import normalize_preference

from bgcc_prototype import (
    bounded_greedy_cycle_cover,
    cycle_weight,
    egalitarian_score,
    find_cycles,
)


# ============================================================
# OPTIONAL AI CYCLE EVALUATOR
# ============================================================

try:
    from ai_cycle_evaluator import evaluate_candidates

    AI_EVALUATOR_AVAILABLE = True

except Exception:
    AI_EVALUATOR_AVAILABLE = False


# ============================================================
# CONFIG
# ============================================================

SERVICE_ACCOUNT_PATH = os.getenv(
    "SERVICE_ACCOUNT_PATH",
    "serviceAccountKey.json",
)

CONDITION_RANK = {
    "poor": 0,
    "fair": 1,
    "good": 2,
    "like new": 3,
    "like_new": 3,
    "new": 4,
    "any": 0,
}

EDGE_WEIGHT_THRESHOLD = 0.5


# ============================================================
# CONDITION CHECK
# ============================================================

def meets_min_condition(
    actual_condition,
    minimum_condition,
):
    actual = str(
        actual_condition or ""
    ).strip().lower()

    minimum = str(
        minimum_condition or ""
    ).strip().lower()

    return CONDITION_RANK.get(
        actual,
        0,
    ) >= CONDITION_RANK.get(
        minimum,
        0,
    )


# ============================================================
# EDGE WEIGHT
# ============================================================

def compute_edge_weight(
    preference,
    listing,
):
    """
    Calculate how well a listing satisfies
    a user's preference.

    Exact desired-item matches receive strong
    priority over AI category classification.
    """

    weight = 0.3

    preference_category = str(
        preference.get(
            "item_category",
            "",
        )
    ).strip().lower()

    desired_item = str(
        preference.get(
            "desired_item",
            "",
        )
    ).strip().lower()

    listing_category = str(
        listing.get(
            "category",
            "",
        )
    ).strip().lower()

    listing_item = str(
        listing.get(
            "item",
            "",
        )
    ).strip().lower()

    listing_brand = str(
        listing.get(
            "brand",
            "",
        )
    ).strip().lower()

    # Combined text for matching
    item_text = (
        f"{listing_item} "
        f"{listing_brand} "
        f"{listing_category}"
    ).strip().lower()

    # ========================================================
    # EXACT DESIRED ITEM MATCH
    # ========================================================

    exact_item_match = False

    if desired_item:

        if desired_item == listing_item:
            exact_item_match = True

        elif desired_item in item_text:
            exact_item_match = True

        else:
            desired_words = set(
                desired_item.split()
            )

            listing_words = set(
                item_text.split()
            )

            if (
                desired_words
                and desired_words.issubset(
                    listing_words
                )
            ):
                exact_item_match = True

    if exact_item_match:

        # Strong exact-item match.
        weight += 0.35

    # ========================================================
    # CATEGORY MATCH
    # ========================================================

    elif (
        preference_category
        and listing_category
        == preference_category
    ):

        weight += 0.35

    # ========================================================
    # KEYWORD MATCH
    # ========================================================

    else:

        keywords = preference.get(
            "keywords",
            [],
        )

        matched_keyword = False

        for keyword in keywords:

            keyword = str(
                keyword
            ).strip().lower()

            if (
                keyword
                and keyword in item_text
            ):
                matched_keyword = True
                break

        if matched_keyword:

            weight += 0.15

        else:

            weight -= 0.2

    # ========================================================
    # BRAND
    # ========================================================

    acceptable_brands = preference.get(
        "acceptable_brands",
        [],
    )

    if not isinstance(
        acceptable_brands,
        list,
    ):
        acceptable_brands = []

    acceptable_brands = [
        str(brand)
        .strip()
        .lower()
        for brand in acceptable_brands
    ]

    if (
        acceptable_brands
        and listing_brand
        in acceptable_brands
    ):

        weight += 0.1

    # ========================================================
    # CONDITION
    # ========================================================

    minimum_condition = str(
        preference.get(
            "minimum_condition",
            "any",
        )
    ).strip().lower()

    actual_condition = str(
        listing.get(
            "condition",
            "",
        )
    ).strip().lower()

    if meets_min_condition(
        actual_condition,
        minimum_condition,
    ):

        weight += 0.15

    else:

        weight -= 0.25

    # ========================================================
    # FLEXIBILITY
    # ========================================================

    flexibility = preference.get(
        "flexibility",
        0.0,
    )

    try:
        flexibility = float(
            flexibility
        )

    except (
        TypeError,
        ValueError,
    ):
        flexibility = 0.0

    weight += flexibility * 0.1

    return max(
        0.0,
        min(
            1.0,
            round(
                weight,
                2,
            ),
        ),
    )


# ============================================================
# FIREBASE INITIALIZATION
# ============================================================

def initialize_firebase():

    print(
        "[0] Initializing Firebase..."
    )

    if not os.path.exists(
        SERVICE_ACCOUNT_PATH
    ):

        print(
            "ERROR: Service account file not found: "
            f"{SERVICE_ACCOUNT_PATH}"
        )

        sys.exit(1)

    if not firebase_admin._apps:

        cred = credentials.Certificate(
            SERVICE_ACCOUNT_PATH
        )

        firebase_admin.initialize_app(
            cred
        )

    db = firestore.client()

    print(
        "    Firebase initialized successfully."
    )

    return db


# ============================================================
# FETCH ACTIVE LISTINGS
# ============================================================

def fetch_active_listings(db):

    print(
        "[1] Fetching active listings..."
    )

    listings = []

    docs = (
        db.collection("listings")
        .where(
            "status",
            "==",
            "active",
        )
        .stream()
    )

    for doc in docs:

        data = doc.to_dict() or {}

        listing = {
            "id": doc.id,
            "ownerId": data.get(
                "ownerId",
                "",
            ),
            "item": data.get(
                "item",
                "",
            ),
            "category": data.get(
                "category",
                "",
            ),
            "brand": data.get(
                "brand",
                "",
            ),
            "condition": data.get(
                "condition",
                "",
            ),
            "status": data.get(
                "status",
                "active",
            ),
        }

        listings.append(
            listing
        )

    print(
        f"    {len(listings)} active listing(s) found."
    )

    return listings


# ============================================================
# FETCH PREFERENCES
# ============================================================

def fetch_preferences(db):

    print(
        "[2] Fetching preferences..."
    )

    pending = []
    processed = []

    try:

        docs = (
            db.collection("preferences")
            .where(
                "status",
                "in",
                [
                    "pending",
                    "processed",
                ],
            )
            .stream()
        )

        for doc in docs:

            data = doc.to_dict() or {}

            preference = {
                "id": doc.id,
                **data,
            }

            status = data.get(
                "status"
            )

            if status == "pending":

                pending.append(
                    preference
                )

            elif status == "processed":

                processed.append(
                    preference
                )

    except Exception as e:

        print(
            "    Combined preference query failed."
        )

        print(
            "    Falling back to all preferences."
        )

        print(
            f"    Reason: {e}"
        )

        pending = []
        processed = []

        docs = (
            db.collection(
                "preferences"
            )
            .stream()
        )

        for doc in docs:

            data = doc.to_dict() or {}

            preference = {
                "id": doc.id,
                **data,
            }

            status = data.get(
                "status"
            )

            if status == "pending":

                pending.append(
                    preference
                )

            elif status == "processed":

                processed.append(
                    preference
                )

    print(
        f"    {len(pending)} pending preference(s) found."
    )

    print(
        f"    {len(processed)} processed preference(s) found."
    )

    return (
        pending,
        processed,
    )


# ============================================================
# NORMALIZE PENDING PREFERENCES
# ============================================================

def normalize_pending(
    db,
    pending,
):

    print(
        "[3] Normalizing pending preferences via AI..."
    )

    processed = []

    for preference in pending:

        doc_id = preference.get(
            "id",
            "",
        )

        raw_text = preference.get(
            "rawText",
            "",
        )

        print(
            f"    Normalizing preference {doc_id}..."
        )

        try:

            normalized = normalize_preference(
                raw_text
            )

            if normalized is None:

                raise ValueError(
                    "AI returned no normalized preference."
                )

            update_data = {
                "normalized": normalized,
                "status": "processed",
            }

            (
                db.collection(
                    "preferences"
                )
                .document(
                    doc_id
                )
                .update(
                    update_data
                )
            )

            preference[
                "normalized"
            ] = normalized

            preference[
                "status"
            ] = "processed"

            processed.append(
                preference
            )

            print(
                f"    Successfully normalized {doc_id}."
            )

        except Exception as e:

            print(
                f"    WARNING: Failed to normalize "
                f"{doc_id}: {e}"
            )

    print(
        f"    {len(processed)} new preference(s) normalized."
    )

    return processed


# ============================================================
# TIMESTAMP SORT VALUE
# ============================================================

def timestamp_value(value):

    if value is None:
        return 0

    try:
        return value.timestamp()

    except Exception:
        pass

    return str(value)


# ============================================================
# SELECT LATEST PREFERENCE PER USER
# ============================================================

def select_latest_preferences(
    preferences,
):

    latest_by_user = {}

    for preference in preferences:

        user_id = preference.get(
            "userId",
            "",
        )

        if not user_id:
            continue

        current = latest_by_user.get(
            user_id
        )

        if current is None:

            latest_by_user[
                user_id
            ] = preference

            continue

        current_time = timestamp_value(
            current.get(
                "submittedAt"
            )
        )

        new_time = timestamp_value(
            preference.get(
                "submittedAt"
            )
        )

        if new_time >= current_time:

            latest_by_user[
                user_id
            ] = preference

    return list(
        latest_by_user.values()
    )


# ============================================================
# PRINT NORMALIZED PREFERENCES
# ============================================================

def print_preferences(
    preferences,
):

    print()

    print(
        "    Active normalized preferences:"
    )

    for preference in preferences:

        print()

        print(
            f"      User: "
            f"{preference.get('userId', '')}"
        )

        print(
            f"      Wants: "
            f"{preference.get('normalized', {})}"
        )

    print()


# ============================================================
# BUILD GRAPH
# ============================================================

def build_graph(
    listings,
    preferences,
):

    print(
        "[5] Building weighted exchange graph..."
    )

    graph = nx.DiGraph()

    # ========================================================
    # ADD USERS
    # ========================================================

    users = set()

    for listing in listings:

        owner = listing.get(
            "ownerId",
            "",
        )

        if owner:
            users.add(
                owner
            )

    for preference in preferences:

        user_id = preference.get(
            "userId",
            "",
        )

        if user_id:
            users.add(
                user_id
            )

    for user_id in users:

        graph.add_node(
            user_id
        )

    # ========================================================
    # BUILD EDGES
    # ========================================================

    for preference in preferences:

        buyer = preference.get(
            "userId",
            "",
        )

        if not buyer:
            continue

        normalized = preference.get(
            "normalized",
            {},
        )

        if not isinstance(
            normalized,
            dict,
        ):

            print(
                f"    WARNING: Preference for "
                f"{buyer} has invalid normalized data."
            )

            continue

        best_edges = []

        for listing in listings:

            seller = listing.get(
                "ownerId",
                "",
            )

            # User cannot receive their own listing.
            if (
                not seller
                or seller == buyer
            ):
                continue

            weight = compute_edge_weight(
                normalized,
                listing,
            )

            if (
                weight
                >= EDGE_WEIGHT_THRESHOLD
            ):

                best_edges.append(
                    (
                        weight,
                        seller,
                        listing,
                    )
                )

        # ====================================================
        # ONE EDGE PER SELLER
        # ====================================================

        best_by_seller = {}

        for (
            weight,
            seller,
            listing,
        ) in best_edges:

            existing = best_by_seller.get(
                seller
            )

            if (
                existing is None
                or weight > existing[0]
            ):

                best_by_seller[
                    seller
                ] = (
                    weight,
                    listing,
                )

        # ====================================================
        # NO MATCH
        # ====================================================

        if not best_by_seller:

            print(
                f"    {buyer} -> no suitable listing"
            )

            continue

        # ====================================================
        # ADD EDGES
        # ====================================================

        for seller, (
            weight,
            listing,
        ) in best_by_seller.items():

            graph.add_edge(
                buyer,
                seller,
                weight=weight,
                listingId=listing.get(
                    "id",
                    "",
                ),
                item=listing.get(
                    "item",
                    "",
                ),
                category=listing.get(
                    "category",
                    "",
                ),
                brand=listing.get(
                    "brand",
                    "",
                ),
            )

            print(
                f"    {buyer} -> {seller} | "
                f"{listing.get('item', '')} | "
                f"weight={weight}"
            )

    print()

    print(
        f"    Graph has "
        f"{graph.number_of_nodes()} nodes, "
        f"{graph.number_of_edges()} edges."
    )

    print()

    print(
        "    Exchange edges:"
    )

    for (
        buyer,
        seller,
        data,
    ) in graph.edges(
        data=True
    ):

        print(
            f"      {buyer} -> {seller} | "
            f"item={data.get('item', '')} | "
            f"weight={data.get('weight', 0)} | "
            f"listingId={data.get('listingId', '')}"
        )

    return graph


# ============================================================
# EXTRACT BGCC CYCLE
# ============================================================

def extract_cycle(result):

    """
    BGCC implementations may return:

        ["userA", "userB"]

    or:

        (["userA", "userB"], score)

    or:

        [[userA, userB], score]

    This function extracts only the actual
    list of user IDs.
    """

    # Plain list of strings
    if isinstance(
        result,
        list,
    ):

        if result and all(
            isinstance(
                item,
                str,
            )
            for item in result
        ):

            return list(
                result
            )

        if (
            len(result) >= 1
            and isinstance(
                result[0],
                (list, tuple),
            )
        ):

            first = result[0]

            if all(
                isinstance(
                    item,
                    str,
                )
                for item in first
            ):

                return list(
                    first
                )

    # Tuple
    if isinstance(
        result,
        tuple,
    ):

        if all(
            isinstance(
                item,
                str,
            )
            for item in result
        ):

            return list(
                result
            )

        if (
            len(result) >= 1
            and isinstance(
                result[0],
                (list, tuple),
            )
        ):

            first = result[0]

            if all(
                isinstance(
                    item,
                    str,
                )
                for item in first
            ):

                return list(
                    first
                )

    return []


# ============================================================
# NORMALIZE BGCC RESULTS
# ============================================================

def normalize_bgcc_cycles(
    raw_cycles,
):

    cycles = []

    for result in raw_cycles:

        cycle = extract_cycle(
            result
        )

        if len(cycle) >= 2:

            cycles.append(
                cycle
            )

    return cycles


# ============================================================
# CANONICAL CYCLE
# ============================================================

def canonical_cycle(
    cycle,
):

    cycle = list(
        cycle
    )

    if not cycle:
        return cycle

    rotations = [
        cycle[i:] + cycle[:i]
        for i in range(
            len(cycle)
        )
    ]

    return min(
        rotations
    )


# ============================================================
# MATCH ID
# ============================================================

def make_match_id(
    cycle,
    listing_ids,
):

    cycle = canonical_cycle(
        cycle
    )

    # Sort listing IDs only for deterministic
    # duplicate detection while retaining
    # the actual exchange order separately.
    raw = "|".join(
        cycle
        + ["LISTINGS"]
        + listing_ids
    )

    digest = hashlib.sha256(
        raw.encode(
            "utf-8"
        )
    ).hexdigest()[:20]

    return (
        f"match_{digest}"
    )


# ============================================================
# SAVE MATCHES
# ============================================================

def save_matches(
    db,
    graph,
    cycles,
):

    print(
        "[8] Saving matches to Firestore..."
    )

    if not cycles:

        print(
            "    No matches to save."
        )

        return 0

    matches_ref = db.collection(
        "matches"
    )

    saved = 0

    for (
        cycle_number,
        original_cycle,
    ) in enumerate(
        cycles,
        start=1,
    ):

        cycle = extract_cycle(
            original_cycle
        )

        if len(cycle) < 2:

            print(
                f"    WARNING: Invalid cycle "
                f"{cycle_number}; skipping."
            )

            continue

        # ====================================================
        # GET CYCLE EDGES
        # ====================================================

        edges = []

        valid_cycle = True

        for i in range(
            len(cycle)
        ):

            buyer = cycle[i]

            seller = cycle[
                (
                    i + 1
                )
                % len(cycle)
            ]

            if not graph.has_edge(
                buyer,
                seller,
            ):

                valid_cycle = False

                break

            edge = graph[
                buyer
            ][
                seller
            ]

            edges.append(
                edge
            )

        if not valid_cycle:

            print(
                f"    WARNING: Skipping invalid "
                f"cycle {cycle_number}."
            )

            continue

        # ====================================================
        # LISTING IDS
        # ====================================================

        listing_ids = [
            edge.get(
                "listingId",
                "",
            )
            for edge in edges
        ]

        listing_ids = [
            listing_id
            for listing_id in listing_ids
            if listing_id
        ]

        # ====================================================
        # UTILITY
        # ====================================================

        try:

            total_utility = float(
                cycle_weight(
                    graph,
                    cycle,
                )
            )

        except Exception:

            total_utility = sum(
                float(
                    edge.get(
                        "weight",
                        0,
                    )
                )
                for edge in edges
            )

        # ====================================================
        # FAIRNESS
        # ====================================================

        try:

            fairness = float(
                egalitarian_score(
                    graph,
                    cycle,
                )
            )

        except Exception:

            weights = [
                float(
                    edge.get(
                        "weight",
                        0,
                    )
                )
                for edge in edges
            ]

            fairness = (
                min(weights)
                if weights
                else 0.0
            )

        # ====================================================
        # MATCH ID
        # ====================================================

        match_id = make_match_id(
            cycle,
            listing_ids,
        )

        # ====================================================
        # MATCH DATA
        # ====================================================

        match_data = {

            "cycle": cycle,

            "listingIds": listing_ids,

            "totalUtility": round(
                total_utility,
                2,
            ),

            "egalitarianScore": round(
                fairness,
                2,
            ),

            "status": "pending",

            "exchanges": [
                {
                    "fromUser": cycle[i],

                    "toUser": cycle[
                        (
                            i + 1
                        )
                        % len(cycle)
                    ],

                    "listingId": edges[i].get(
                        "listingId",
                        "",
                    ),

                    "item": edges[i].get(
                        "item",
                        "",
                    ),

                    "weight": edges[i].get(
                        "weight",
                        0,
                    ),
                }
                for i in range(
                    len(edges)
                )
            ],

            "createdAt":
                firestore.SERVER_TIMESTAMP,
        }

        # ====================================================
        # CHECK EXISTING MATCH
        # ====================================================

        existing_ref = (
            matches_ref
            .document(
                match_id
            )
        )

        existing_doc = (
            existing_ref.get()
        )

        if existing_doc.exists:

            print(
                f"    Match already exists: "
                f"{match_id}"
            )

            continue

        # ====================================================
        # SAVE
        # ====================================================

        existing_ref.set(
            match_data
        )

        saved += 1

        print()

        print(
            f"    Saved match {cycle_number}:"
        )

        print(
            f"      Cycle: "
            f"{' -> '.join(cycle)}"
        )

        print(
            f"      Match ID: "
            f"{match_id}"
        )

        print(
            f"      Listings: "
            f"{listing_ids}"
        )

        print(
            f"      Total utility: "
            f"{total_utility:.2f}"
        )

        print(
            f"      Fairness: "
            f"{fairness:.2f}"
        )

    print()

    print(
        f"    {saved} new match(es) saved "
        f"to Firestore."
    )

    return saved


# ============================================================
# AI CYCLE EVALUATION
# ============================================================

def run_ai_cycle_evaluation(
    graph,
    cycles,
):

    print(
        "[9] Running AI cycle evaluation..."
    )

    if not AI_EVALUATOR_AVAILABLE:

        print(
            "    AI cycle evaluator unavailable."
        )

        return

    if not cycles:

        print(
            "    No cycles to evaluate."
        )

        return

    try:

        graph_data = {

            "nodes": list(
                graph.nodes()
            ),

            "edges": [
                {
                    "fromUser": source,

                    "toUser": target,

                    "weight": data.get(
                        "weight",
                        0,
                    ),

                    "listingId": data.get(
                        "listingId",
                        "",
                    ),

                    "item": data.get(
                        "item",
                        "",
                    ),
                }

                for (
                    source,
                    target,
                    data,
                )
                in graph.edges(
                    data=True
                )
            ],
        }

        result = evaluate_candidates(
            graph_data,
            cycles,
        )

        print(
            "    AI evaluation completed."
        )

        print(
            f"    Result: {result}"
        )

    except Exception as e:

        print(
            "    WARNING: AI cycle evaluation "
            f"failed: {e}"
        )


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "SwapCycle Firestore matching bridge"
        )
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Run matching without writing "
            "matches to Firestore."
        ),
    )

    parser.add_argument(
        "--max-cycle-length",
        type=int,
        default=4,
        help=(
            "Maximum exchange cycle length "
            "(default: 4)."
        ),
    )

    args = parser.parse_args()

    print()

    print(
        "=" * 60
    )

    print(
        "SWAPCYCLE FIRESTORE MATCHING BRIDGE"
    )

    print(
        "=" * 60
    )

    # ========================================================
    # FIREBASE
    # ========================================================

    db = initialize_firebase()

    # ========================================================
    # LISTINGS
    # ========================================================

    listings = fetch_active_listings(
        db
    )

    # ========================================================
    # PREFERENCES
    # ========================================================

    (
        pending,
        processed,
    ) = fetch_preferences(
        db
    )

    # ========================================================
    # NORMALIZE
    # ========================================================

    newly_processed = normalize_pending(
        db,
        pending,
    )

    all_processed = (
        processed
        + newly_processed
    )

    print()

    print(
        f"    {len(all_processed)} total processed "
        "preference(s) available."
    )

    if not all_processed:

        print()

        print(
            "Nothing to process."
        )

        print()

        return

    # ========================================================
    # LATEST PER USER
    # ========================================================

    print(
        "[4] Selecting latest preference per user..."
    )

    preferences = select_latest_preferences(
        all_processed
    )

    print(
        f"    {len(preferences)} unique user "
        "preference(s) after deduplication."
    )

    # ========================================================
    # DEBUG PREFERENCES
    # ========================================================

    print_preferences(
        preferences
    )

    # ========================================================
    # BUILD GRAPH
    # ========================================================

    graph = build_graph(
        listings,
        preferences,
    )

    # ========================================================
    # BGCC
    # ========================================================

    print(
        "[6] Running BGCC matching..."
    )

    try:

        raw_matched_cycles = (
            bounded_greedy_cycle_cover(
                graph,
                max_cycle_length=(
                    args.max_cycle_length
                ),
            )
        )

    except TypeError:

        raw_matched_cycles = (
            bounded_greedy_cycle_cover(
                graph,
                args.max_cycle_length,
            )
        )

    # ========================================================
    # FIX BGCC RETURN FORMAT
    # ========================================================

    matched_cycles = normalize_bgcc_cycles(
        raw_matched_cycles
    )

    print(
        f"    BGCC matched "
        f"{len(matched_cycles)} cycle(s)."
    )

    print()

    print(
        "    BGCC selected cycles:"
    )

    for cycle in matched_cycles:

        print(
            f"      {' -> '.join(cycle)}"
        )

    # ========================================================
    # CYCLE DETAILS
    # ========================================================

    print()

    print(
        "[7] Cycle details..."
    )

    try:

        discovered_cycles = find_cycles(
            graph,
            max_length=(
                args.max_cycle_length
            ),
        )

    except TypeError:

        try:

            discovered_cycles = find_cycles(
                graph,
                args.max_cycle_length,
            )

        except TypeError:

            discovered_cycles = find_cycles(
                graph
            )

    if discovered_cycles:

        print(
            f"    {len(discovered_cycles)} "
            "cycle(s) found:"
        )

        for (
            index,
            raw_cycle,
        ) in enumerate(
            discovered_cycles,
            start=1,
        ):

            cycle = extract_cycle(
                raw_cycle
            )

            if len(cycle) < 2:
                continue

            try:

                weight = cycle_weight(
                    graph,
                    cycle,
                )

            except Exception:

                weight = 0.0

            try:

                fairness = egalitarian_score(
                    graph,
                    cycle,
                )

            except Exception:

                fairness = 0.0

            print()

            print(
                f"    Cycle {index}:"
            )

            print(
                f"      Users: "
                f"{' -> '.join(cycle)}"
            )

            print(
                f"      Weight: "
                f"{float(weight):.2f}"
            )

            print(
                f"      Egalitarian score: "
                f"{float(fairness):.2f}"
            )

    else:

        print(
            "    No cycles found."
        )

    # ========================================================
    # SAVE
    # ========================================================

    if args.dry_run:

        print()

        print(
            "[8] DRY RUN: matches will NOT "
            "be written to Firestore."
        )

    else:

        save_matches(
            db,
            graph,
            matched_cycles,
        )

    # ========================================================
    # AI EVALUATOR
    # ========================================================

    run_ai_cycle_evaluation(
        graph,
        matched_cycles,
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    print()

    print(
        "=" * 60
    )

    print(
        "SUMMARY"
    )

    print(
        "=" * 60
    )

    print(
        f"Listings: "
        f"{len(listings)}"
    )

    print(
        f"Pending prefs: "
        f"{len(pending)}"
    )

    print(
        f"Processed prefs: "
        f"{len(all_processed)}"
    )

    print(
        f"Unique users: "
        f"{len(preferences)}"
    )

    print(
        f"Graph nodes: "
        f"{graph.number_of_nodes()}"
    )

    print(
        f"Graph edges: "
        f"{graph.number_of_edges()}"
    )

    print(
        f"Cycles found: "
        f"{len(discovered_cycles)}"
    )

    print(
        f"BGCC matched: "
        f"{len(matched_cycles)}"
    )

    print(
        "=" * 60
    )

    print()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()