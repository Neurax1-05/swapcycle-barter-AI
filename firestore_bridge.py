import argparse
import hashlib
import os
import re
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

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

from matching_config import DEFAULT_WEIGHTS, engine_from_env, weights_from_env
from cycle_arbitration import (
    edge_tiebreak,
    build_context,
    build_labels,
    make_ai_arbiter,
    select_cycles,
)


# ============================================================
# OPTIONAL AI CYCLE EVALUATOR
# ============================================================

try:
    from ai_cycle_evaluator import MODEL as AI_MODEL
    from ai_cycle_evaluator import evaluate_candidates

    AI_EVALUATOR_AVAILABLE = True

except Exception:
    AI_MODEL = ""
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

EDGE_WEIGHT_THRESHOLD = DEFAULT_WEIGHTS.threshold  # see matching_config.py

# Categories so wide that "same category" says almost nothing (a phone and
# a pair of headphones are both "electronics"). For these the listing must
# also hit the wanted item or one of the keywords to count as relevant.
BROAD_CATEGORIES = {
    "electronics",
    "clothing",
    "other",
    "misc",
    "general",
}

# A pending match nobody finishes confirming is released after this long.
MATCH_TTL_HOURS = float(os.getenv("MATCH_TTL_HOURS", "72"))


def _tokens(text):
    return set(re.findall(r"[a-z0-9]+", str(text).lower()))


def phrase_in_text(phrase, text):
    """Whole-word match ('phone' must not hit 'headphones'). A plain
    plural ('guitars') still matches."""

    phrase = str(phrase or "").strip().lower()

    if not phrase:
        return False

    pattern = (
        r"(?<![a-z0-9])"
        + re.escape(phrase)
        + r"(?:s|es)?(?![a-z0-9])"
    )

    return re.search(pattern, str(text).lower()) is not None


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
    weights=None,
):
    """
    Calculate how well a listing satisfies
    a user's preference.

    Exact desired-item matches receive strong
    priority over AI category classification.
    """

    w = weights or DEFAULT_WEIGHTS

    weight = w.base

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

    # Broad categories ("electronics", "other") carry no signal, so they
    # are left out of the text a wanted item / keyword is matched against.
    broad = (
        preference_category in BROAD_CATEGORIES
        or listing_category in BROAD_CATEGORIES
    )

    item_text = (
        f"{listing_item} "
        f"{listing_brand} "
        f"{'' if listing_category in BROAD_CATEGORIES else listing_category}"
    ).strip().lower()

    # ========================================================
    # EXACT DESIRED ITEM MATCH
    # ========================================================

    exact_item_match = False

    if desired_item:

        if desired_item == listing_item:
            exact_item_match = True

        elif phrase_in_text(desired_item, item_text):
            exact_item_match = True

        else:
            desired_words = _tokens(
                desired_item
            )

            listing_words = _tokens(
                item_text
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
        weight += w.exact_item

    # ========================================================
    # CATEGORY MATCH
    # ========================================================

    elif (
        preference_category
        and listing_category
        == preference_category
        and not broad
    ):

        weight += w.category

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
                and phrase_in_text(
                    keyword,
                    item_text,
                )
            ):
                matched_keyword = True
                break

        if matched_keyword:

            weight += w.keyword

        else:

            weight -= w.no_relevance_penalty

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

        weight += w.brand

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

        weight += w.condition_ok

    else:

        weight -= w.condition_fail_penalty

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

    weight += flexibility * w.flexibility_scale

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

MAX_NORMALIZE_ATTEMPTS = 3          # then the preference is marked 'failed'
NORMALIZE_WORKERS = int(os.getenv("SWAP_LLM_WORKERS", "6"))
NORMALIZE_BUDGET_SECONDS = float(os.getenv("SWAP_NORMALIZE_BUDGET", "180"))


def _normalize_one(preference):
    """LLM call only (no Firestore) so it is safe to run in a thread."""
    normalized = normalize_preference(preference.get("rawText", ""))
    if normalized is None:
        raise ValueError("AI returned no normalized preference.")
    return normalized


def normalize_pending(
    db,
    pending,
):
    """
    Normalise pending preferences with bounded concurrency.

    * LLM calls run in a small thread pool (was: one blocking call at a time).
    * A wall-clock budget stops new work before the Cloud Function timeout;
      anything not reached stays 'pending' for the next run.
    * Each failure bumps `normalizeAttempts`; after MAX_NORMALIZE_ATTEMPTS the
      preference is marked 'failed' so one bad row stops costing an LLM call
      (and up to 60s) on every future run.
    """
    print(
        "[3] Normalizing pending preferences via AI..."
    )

    processed = []
    deadline = time.monotonic() + NORMALIZE_BUDGET_SECONDS

    def work(preference):
        if time.monotonic() > deadline:
            return preference, None, "skipped: time budget used"
        try:
            return preference, _normalize_one(preference), None
        except Exception as e:
            return preference, None, e

    workers = max(1, min(NORMALIZE_WORKERS, len(pending) or 1))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(work, pending))

    for preference, normalized, error in results:

        doc_id = preference.get("id", "")
        ref = db.collection("preferences").document(doc_id)

        if error is None:
            ref.update({"normalized": normalized, "status": "processed"})
            preference["normalized"] = normalized
            preference["status"] = "processed"
            processed.append(preference)
            print(f"    Successfully normalized {doc_id}.")
            continue

        if isinstance(error, str):  # skipped, not a failure
            print(f"    {doc_id}: {error}")
            continue

        attempts = int(preference.get("normalizeAttempts") or 0) + 1
        update = {"normalizeAttempts": attempts}
        if attempts >= MAX_NORMALIZE_ATTEMPTS:
            update["status"] = "failed"
        try:
            ref.update(update)
        except Exception as exc:
            print(f"    Could not record failure for {doc_id}: {exc}")
        print(
            f"    WARNING: Failed to normalize {doc_id} "
            f"(attempt {attempts}/{MAX_NORMALIZE_ATTEMPTS}): {error}"
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
# CANDIDATE INDEX (avoids the O(preferences x listings) scan)
# ============================================================

def _listing_text_tokens(listing):
    return _tokens(
        f"{listing.get('item', '')} {listing.get('brand', '')} "
        f"{listing.get('category', '')}"
    )


def _build_listing_index(listings):
    by_token = {}
    by_category = {}
    for i, listing in enumerate(listings):
        for tok in _listing_text_tokens(listing):
            by_token.setdefault(tok, set()).add(i)
        cat = str(listing.get("category", "")).strip().lower()
        by_category.setdefault(cat, set()).add(i)
    return by_token, by_category


def _candidate_listing_ids(normalized, index, n_listings, w):
    """
    Indexes of listings that could possibly reach the edge threshold for this
    preference, or None meaning "scan everything".

    Without a relevance hit (wanted item / category / keyword) the best score
    a listing can reach is base - no_relevance_penalty + brand + condition_ok
    + flexibility term. When that is below the threshold, only listings with
    a relevance hit matter, and those are found through the inverted index.
    The result is identical to a full scan (tests/test_candidate_index.py).
    """
    keywords = normalized.get("keywords", [])
    if not isinstance(keywords, list):
        return None
    try:
        flex = float(normalized.get("flexibility", 0.0))
    except (TypeError, ValueError):
        flex = 0.0
    ceiling = (
        w.base - w.no_relevance_penalty + w.brand + w.condition_ok
        + flex * w.flexibility_scale
    )
    if ceiling >= w.threshold:
        return None

    by_token, by_category = index
    cands = set()

    category = str(normalized.get("item_category", "")).strip().lower()
    if category:
        cands |= by_category.get(category, set())

    phrases = [str(normalized.get("desired_item", ""))]
    phrases += [str(k) for k in keywords]
    for phrase in phrases:
        for tok in _tokens(phrase):
            for variant in (tok, tok + "s", tok + "es"):
                cands |= by_token.get(variant, set())
    return cands


# ============================================================
# BUILD GRAPH
# ============================================================

def build_graph(
    listings,
    preferences,
    weights=None,
    use_index=True,
    max_edges_per_buyer=None,
):

    print(
        "[5] Building weighted exchange graph..."
    )

    w = weights or DEFAULT_WEIGHTS
    index = _build_listing_index(listings) if use_index else None

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

        candidate_ids = (
            _candidate_listing_ids(
                normalized, index, len(listings), w
            )
            if use_index
            else None
        )

        scan = (
            listings
            if candidate_ids is None
            else [listings[i] for i in sorted(candidate_ids)]
        )

        for listing in scan:

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
                weights,
            )

            if (
                weight
                >= (weights or DEFAULT_WEIGHTS).threshold
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

        edge_items = best_by_seller.items()

        if max_edges_per_buyer:
            # Same ordering as cycle_arbitration.prune_graph, applied early
            # so the graph never holds more than K edges per buyer.
            edge_items = sorted(
                edge_items,
                key=lambda kv: (-kv[1][0], edge_tiebreak(buyer, kv[0])),
            )[:max_edges_per_buyer]

        for seller, (
            weight,
            listing,
        ) in edge_items:

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

            if len(preferences) <= 50:
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
    ) in (
        graph.edges(data=True)
        if len(preferences) <= 50
        else []
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
# DISPLAY NAMES (the AI needs readable names, not Firestore uids)
# ============================================================

def fetch_display_names(db, uids):
    names = {}

    for uid in uids:
        try:
            doc = db.collection("users").document(uid).get()

            if doc.exists:
                names[uid] = (doc.to_dict() or {}).get("displayName", "")

        except Exception as exc:
            print(
                f"    WARNING: could not read display name "
                f"for {uid}: {exc}"
            )

    return names


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
# ATOMIC CLAIM + RUN LOCK
# ============================================================

USER_LOCKS = "userLocks"
RUN_LOCK_PATH = ("system", "matchingRun")
RUN_LEASE_SECONDS = 600


def _claim_txn(transaction, db, match_ref, match_data, cycle):
    """
    Body of the claim transaction (reads first, then writes).

    A user is "locked" by userLocks/{uid} -> matchId, but only while that
    match is still open, so locks release themselves when a match is
    declined / expired / completed (no separate cleanup job to forget).
    """
    if match_ref.get(transaction=transaction).exists:
        return "exists"

    lock_refs = [db.collection(USER_LOCKS).document(u) for u in cycle]
    locks = [ref.get(transaction=transaction) for ref in lock_refs]

    for lock in locks:
        if not lock.exists:
            continue
        other_id = (lock.to_dict() or {}).get("matchId")
        if not other_id or other_id == match_ref.id:
            continue
        other = (
            db.collection("matches")
            .document(other_id)
            .get(transaction=transaction)
        )
        if other.exists and (other.to_dict() or {}).get(
            "status"
        ) in OPEN_MATCH_STATUSES:
            return "locked"

    transaction.set(match_ref, match_data)
    for ref in lock_refs:
        transaction.set(
            ref,
            {"matchId": match_ref.id, "updatedAt": firestore.SERVER_TIMESTAMP},
        )
    return "saved"


def claim_and_write_match(db, match_ref, match_data, cycle):
    """Returns "saved", "exists" or "locked"."""
    transaction = db.transaction()
    return firestore.transactional(_claim_txn)(
        transaction, db, match_ref, match_data, cycle
    )


def _run_lock_ref(db):
    return db.collection(RUN_LOCK_PATH[0]).document(RUN_LOCK_PATH[1])


def _acquire_txn(transaction, ref, owner, now, lease):
    snap = ref.get(transaction=transaction)
    data = snap.to_dict() or {} if snap.exists else {}
    until = _as_datetime(data.get("leaseUntil")) if data.get("leaseUntil") else None
    if until and until > now and data.get("owner") != owner:
        # Someone else is running: ask them to go round once more so this
        # trigger's new data is not lost, then back off.
        transaction.update(ref, {"rerunRequested": True})
        return False
    transaction.set(
        ref,
        {"owner": owner, "leaseUntil": now + lease, "rerunRequested": False},
    )
    return True


def acquire_run_lock(db, owner, now=None, lease_seconds=RUN_LEASE_SECONDS):
    """Single-flight guard: only one matching run at a time across the Cloud
    Function and local_listener. Leases expire so a crashed run cannot block
    forever."""
    now = now or datetime.now(timezone.utc)
    transaction = db.transaction()
    return firestore.transactional(_acquire_txn)(
        transaction,
        _run_lock_ref(db),
        owner,
        now,
        timedelta(seconds=lease_seconds),
    )


def release_run_lock(db, owner):
    """Release; returns True if another trigger asked for a re-run."""
    ref = _run_lock_ref(db)
    snap = ref.get()
    data = snap.to_dict() or {} if snap.exists else {}
    if data.get("owner") != owner:
        return False
    ref.set({"owner": None, "leaseUntil": None, "rerunRequested": False})
    return bool(data.get("rerunRequested"))


# ============================================================
# SAVE MATCHES
# ============================================================

def save_matches(
    db,
    graph,
    cycles,
    ai_decisions=None,
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

            "expiresAt": (
                datetime.now(timezone.utc)
                + timedelta(
                    hours=MATCH_TTL_HOURS
                )
            ),
        }

        # ----------------------------------------------------
        # AI ARBITRATION RESULT (advisory explanation only)
        # ----------------------------------------------------
        decision = (ai_decisions or {}).get(frozenset(cycle))

        if decision:
            match_data["aiEvaluation"] = {
                "reason": decision.get("reason", ""),
                "qualitative_factors_considered": decision.get(
                    "qualitative_factors_considered", []
                ),
                "limitations": decision.get("limitations", []),
                "suggested_adjustment": decision.get(
                    "suggested_adjustment"
                ),
                "confidence": decision.get("confidence"),
                "alternatives_considered": decision.get(
                    "alternatives_considered", 0
                ),
                "model": AI_MODEL,
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

        # ====================================================
        # SAVE (atomic: lock check + match write in ONE transaction)
        # ====================================================

        if hasattr(db, "transaction"):

            outcome = claim_and_write_match(
                db,
                existing_ref,
                match_data,
                cycle,
            )

        else:  # minimal fakes / legacy clients without transactions

            outcome = (
                "exists"
                if existing_ref.get().exists
                else "saved"
            )

            if outcome == "saved":
                existing_ref.set(match_data)

        if outcome == "exists":

            print(
                f"    Match already exists: "
                f"{match_id}"
            )

            continue

        if outcome == "locked":

            print(
                f"    Skipped {match_id}: a participant is already "
                f"in another open match (concurrent run)."
            )

            continue

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

# ============================================================
# LOCK USERS / LISTINGS ALREADY IN A TRADE
# ============================================================
#
# Nothing in the app marks a listing as used once it is matched, and
# preferences stay "processed" forever. Without this step every run rebuilds
# the graph from ALL active listings and preferences, so anyone already in an
# open match gets pulled into a new, differently-shaped cycle and receives
# duplicate matches (several confirm/decline cards).
#
#   pending / confirmed  -> those users and their listings are locked
#   completed            -> those listings are gone, and the members' older
#                           preferences are used up (newer ones still count)
#   declined             -> free again (the exact same cycle is never
#                           re-proposed, because its match id already exists)

OPEN_MATCH_STATUSES = ("pending", "confirmed")
LOCKING_LISTING_STATUSES = ("pending", "confirmed", "completed")


def fetch_locked_state(db):
    """Read matches and return (locked_users, locked_listing_ids,
    completed_cutoffs). completed_cutoffs maps uid -> timestamp of that
    user's latest completed match."""

    locked_users = set()
    locked_listings = set()
    completed_cutoffs = {}

    docs = (
        db.collection("matches")
        .where("status", "in", list(LOCKING_LISTING_STATUSES))
        .stream()
    )

    for doc in docs:
        data = doc.to_dict() or {}
        status = data.get("status")
        cycle = data.get("cycle") or []

        locked_listings.update(
            str(x) for x in (data.get("listingIds") or []) if x
        )

        if status in OPEN_MATCH_STATUSES:
            locked_users.update(cycle)

        elif status == "completed":
            stamp = timestamp_value(data.get("createdAt"))
            for uid in cycle:
                if not isinstance(stamp, (int, float)):
                    stamp = 0
                completed_cutoffs[uid] = max(
                    completed_cutoffs.get(uid, 0), stamp
                )

    return locked_users, locked_listings, completed_cutoffs


def apply_locks(
    listings,
    preferences,
    locked_users,
    locked_listings,
    completed_cutoffs,
):
    """Drop listings/preferences that belong to a trade already underway."""

    free_listings = [
        listing
        for listing in listings
        if listing.get("id") not in locked_listings
        and listing.get("ownerId") not in locked_users
    ]

    free_preferences = []

    for preference in preferences:

        uid = preference.get("userId")

        if uid in locked_users:
            continue

        cutoff = completed_cutoffs.get(uid)

        if cutoff is not None:
            submitted = timestamp_value(preference.get("submittedAt"))
            if (
                isinstance(submitted, (int, float))
                and submitted <= cutoff
            ):
                continue

        free_preferences.append(preference)

    return free_listings, free_preferences


# ============================================================
# EXPIRY + LISTING STATUS HOUSEKEEPING
# ============================================================

def _as_datetime(value):
    """Firestore timestamps arrive as datetimes; treat naive ones as UTC."""

    if not isinstance(value, datetime):
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value


def expire_stale_matches(db, now=None):
    """Pending matches past their expiresAt become 'expired', which frees
    every member for the next run. Matches written before expiresAt existed
    fall back to createdAt + MATCH_TTL_HOURS. Returns how many expired."""

    now = now or datetime.now(timezone.utc)
    ttl = timedelta(hours=MATCH_TTL_HOURS)
    expired = 0

    docs = (
        db.collection("matches")
        .where("status", "==", "pending")
        .stream()
    )

    for doc in docs:
        data = doc.to_dict() or {}

        deadline = _as_datetime(data.get("expiresAt"))

        if deadline is None:
            created = _as_datetime(data.get("createdAt"))

            if created is None:
                continue

            deadline = created + ttl

        if deadline <= now:
            (
                db.collection("matches")
                .document(doc.id)
                .update(
                    {
                        "status": "expired",
                        "expiredAt": firestore.SERVER_TIMESTAMP,
                    }
                )
            )
            expired += 1

    if expired:
        print(f"    {expired} stale pending match(es) expired.")

    return expired


def sync_listing_statuses(db):
    """Keep listings.status in step with the matches (backend only; the
    rules stop owners from setting it):

      listing in a pending/confirmed match -> 'in_trade'
      listing in a completed match         -> 'traded'
      'in_trade' but no open match any more -> back to 'active'

    Returns the number of listings changed."""

    in_trade = set()
    traded = set()

    docs = (
        db.collection("matches")
        .where("status", "in", list(LOCKING_LISTING_STATUSES))
        .stream()
    )

    for doc in docs:
        data = doc.to_dict() or {}
        ids = {str(x) for x in (data.get("listingIds") or []) if x}

        if data.get("status") == "completed":
            traded |= ids
        else:
            in_trade |= ids

    in_trade -= traded
    changed = 0
    listings = db.collection("listings")

    for listing_id, target in (
        [(i, "traded") for i in sorted(traded)]
        + [(i, "in_trade") for i in sorted(in_trade)]
    ):
        snap = listings.document(listing_id).get()

        if not snap.exists:
            continue

        if (snap.to_dict() or {}).get("status") != target:
            listings.document(listing_id).update({"status": target})
            changed += 1

    stuck = (
        listings.where("status", "==", "in_trade").stream()
    )

    for doc in stuck:
        if doc.id not in in_trade and doc.id not in traded:
            listings.document(doc.id).update({"status": "active"})
            changed += 1

    if changed:
        print(f"    {changed} listing status(es) updated.")

    return changed


def housekeeping(db):
    """Run before every matching pass. Never blocks matching."""

    for step in (expire_stale_matches, sync_listing_statuses):
        try:
            step(db)
        except Exception as exc:
            print(f"    WARNING: {step.__name__} failed: {exc}")


def _run_matching_once(
    db,
    *,
    dry_run=False,
    no_ai=False,
    max_cycle_length=4,
):
    """Run the whole matching pipeline against an already-initialised
    Firestore client `db`.

    Shared by the command-line entry point (main) and the Cloud Function
    trigger in functions/main.py, so both run exactly the same code.
    Returns a small summary dict.
    """


    # Expire stale pending matches and sync listing statuses first, so
    # freed people and items are part of this run.
    if not dry_run:
        housekeeping(db)

    # ========================================================
    # LISTINGS
    # ========================================================

    listings = fetch_active_listings(
        db
    )

    (
        locked_users,
        locked_listings,
        completed_cutoffs,
    ) = fetch_locked_state(db)

    if locked_users or locked_listings:
        print(
            f"    {len(locked_users)} user(s) and "
            f"{len(locked_listings)} listing(s) are already in a "
            "trade; excluded from matching."
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

        return {"status": "nothing_to_process", "matched_cycles": 0}

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

    listings, preferences = apply_locks(
        listings,
        preferences,
        locked_users,
        locked_listings,
        completed_cutoffs,
    )

    print(
        f"    {len(preferences)} preference(s) and "
        f"{len(listings)} listing(s) available after excluding "
        "trades already underway."
    )

    if not preferences:

        print()

        print(
            "Nothing new to match."
        )

        print()

        return {"status": "nothing_to_process", "matched_cycles": 0}

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
        weights_from_env(),
        max_edges_per_buyer=engine_from_env().max_out_degree,
    )

    # ========================================================
    # BGCC
    # ========================================================

    print(
        "[6] Running BGCC matching..."
    )

    # BGCC picks the best cycle each round. When several candidate
    # cycles compete for the same user and we know something about the
    # users involved (urgency, notes), Gemini #2 chooses among BGCC's own
    # valid candidates; the loser stays in the pool for a later cycle.
    context = build_context(preferences)

    arbiter = None

    if no_ai:
        print("    AI arbitration disabled (--no-ai).")

    elif not AI_EVALUATOR_AVAILABLE:
        print("    AI evaluator unavailable; using plain BGCC.")

    elif not context:
        print(
            "    No urgency/notes context from any user; "
            "using plain BGCC."
        )

    else:
        node_ids = list(graph.nodes())

        labels = build_labels(
            node_ids,
            fetch_display_names(db, node_ids),
        )

        known_items = {
            str(value)
            for listing in listings
            for value in (listing.get("item"), listing.get("brand"))
            if value
        }

        arbiter = make_ai_arbiter(
            labels,
            evaluate_candidates,
            known_items,
        )

    engine = engine_from_env()
    match_stats = {}

    matched_cycles, _unmatched_users, ai_decisions = select_cycles(
        graph,
        max_len=max_cycle_length,
        context=context,
        arbiter=arbiter,
        max_out_degree=engine.max_out_degree,
        max_cycles=engine.max_cycles,
        solver=engine.solver,
        stats=match_stats,
    )

    # Cycles are enumerated once, inside select_cycles; reuse its count
    # instead of enumerating the whole graph a second time for logging.
    cycles_found = match_stats.get("cycles_enumerated", 0)

    print(
        f"    {cycles_found} candidate cycle(s) enumerated "
        f"({match_stats.get('edges_used', 0)} edges used)."
    )

    print(
        f"    BGCC matched "
        f"{len(matched_cycles)} cycle(s)."
    )

    print()

    print(
        "[7] Selected cycle details..."
    )

    if matched_cycles:

        for index, cycle in enumerate(matched_cycles, start=1):

            print()

            print(f"    Cycle {index}: {' -> '.join(cycle)}")

            print(
                f"      Weight: {cycle_weight(graph, cycle):.2f} | "
                f"Egalitarian: {egalitarian_score(graph, cycle):.2f}"
            )

    else:

        print(
            "    No cycles found."
        )

    # ========================================================
    # SAVE
    # ========================================================

    if dry_run:

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
            ai_decisions,
        )

        try:
            sync_listing_statuses(db)
        except Exception as exc:
            print(f"    WARNING: listing status sync failed: {exc}")

    # (The old stand-alone run_ai_cycle_evaluation step was replaced by
    # the arbitration inside select_cycles above.)

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
        f"{cycles_found}"
    )

    print(
        f"BGCC matched: "
        f"{len(matched_cycles)}"
    )

    print(
        "=" * 60
    )

    print()

    return {
        "status": "ok",
        "listings": len(listings),
        "pending_preferences": len(pending),
        "users": len(preferences),
        "cycles_found": cycles_found,
        "matched_cycles": len(matched_cycles),
        "dry_run": dry_run,
    }



def run_matching(
    db,
    *,
    dry_run=False,
    no_ai=False,
    max_cycle_length=4,
    max_reruns=2,
):
    """
    Single-flight wrapper around one matching pass.

    Only one run proceeds at a time (lease lock in Firestore). If another
    trigger arrived meanwhile, the holder runs again (up to max_reruns), so no
    new preference is lost and no two runs overlap.
    """
    if dry_run or not hasattr(db, "transaction"):
        return _run_matching_once(
            db,
            dry_run=dry_run,
            no_ai=no_ai,
            max_cycle_length=max_cycle_length,
        )

    owner = uuid.uuid4().hex

    if not acquire_run_lock(db, owner):
        print("Another matching run is in progress; it will re-run for us.")
        return {"status": "skipped_locked", "matched_cycles": 0}

    summary = {"status": "nothing_to_process", "matched_cycles": 0}
    try:
        for _ in range(max_reruns + 1):
            summary = _run_matching_once(
                db,
                dry_run=dry_run,
                no_ai=no_ai,
                max_cycle_length=max_cycle_length,
            )
            if not release_run_lock(db, owner):
                owner = None
                break
            # A trigger arrived while we ran: take the lock again and re-run.
            if not acquire_run_lock(db, owner):
                owner = None
                break
    finally:
        if owner:
            release_run_lock(db, owner)
    return summary


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
        "--no-ai",
        action="store_true",
        help=(
            "Plain BGCC only: do not use the AI to arbitrate "
            "between conflicting cycles."
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
    print("=" * 60)
    print("SWAPCYCLE FIRESTORE MATCHING BRIDGE")
    print("=" * 60)

    db = initialize_firebase()

    run_matching(
        db,
        dry_run=args.dry_run,
        no_ai=args.no_ai,
        max_cycle_length=args.max_cycle_length,
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()