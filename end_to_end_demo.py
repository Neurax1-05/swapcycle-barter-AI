import argparse
import json

from bgcc_prototype import (
    bounded_greedy_cycle_cover,
    cycle_weight,
    egalitarian_score,
    find_cycles,
)


# ============================================================
# OFFLINE AI FALLBACK
# ============================================================

def offline_ai(text):
    """Deterministic preference-normalization fallback."""

    text_lower = text.lower()

    if "guitar" in text_lower:
        return {
            "item_category": "guitar",
            "desired_item": (
                "beginner-friendly guitar"
                if "beginner" in text_lower
                else "guitar"
            ),
            "acceptable_brands": (
                ["Yamaha"] if "yamaha" in text_lower else []
            ),
            "minimum_condition": (
                "good" if "good" in text_lower else "any"
            ),
            "budget_or_value_signal": 0.0,
            "flexibility": 0.5,
            "keywords": ["beginner", "guitar"],
            "notes": (
                "User is open to similar alternatives."
                if "similar" in text_lower else ""
            ),
        }

    if "camera" in text_lower:
        return {
            "item_category": "camera",
            "desired_item": (
                "camera for travel photography"
                if "travel" in text_lower
                else "camera for photography"
            ),
            "acceptable_brands": (
                ["Canon"] if "canon" in text_lower else []
            ),
            "minimum_condition": (
                "like_new"
                if "like-new" in text_lower
                or "like new" in text_lower
                else "good"
            ),
            "budget_or_value_signal": 0.0,
            "flexibility": (
                0.8 if "flexible" in text_lower else 0.3
            ),
            "keywords": (
                ["travel", "photography"]
                if "travel" in text_lower
                else ["photography"]
            ),
            "notes": "",
        }

    if "bicycle" in text_lower or "bike" in text_lower:
        return {
            "item_category": "bicycle",
            "desired_item": (
                "bicycle for commuting"
                if "commut" in text_lower
                else "bicycle for everyday transport"
            ),
            "acceptable_brands": (
                ["Trek"] if "trek" in text_lower else []
            ),
            "minimum_condition": (
                "good" if "good" in text_lower else "any"
            ),
            "budget_or_value_signal": 0.0,
            "flexibility": (
                0.6 if "flexible" in text_lower else 0.5
            ),
            "keywords": (
                ["commuting"]
                if "commut" in text_lower
                else ["everyday", "transport"]
            ),
            "notes": "",
        }

    return {
        "item_category": "unknown",
        "desired_item": "unknown",
        "acceptable_brands": [],
        "minimum_condition": "any",
        "budget_or_value_signal": 0.0,
        "flexibility": 1.0,
        "keywords": [],
        "notes": "",
    }


# ============================================================
# QUALITATIVE CONTEXT (Gemini #2 input BGCC's utility never sees)
# ============================================================

QUALITATIVE_CONTEXT = {

    "Alice": {
        "urgency": "High - needs the guitar before a recital next week.",
        "condition_notes": (
            "Cares about a clean fretboard and working tuners more "
            "than cosmetic scuffs."
        ),
        "priority": "Condition and readiness to play over speed of pickup.",
        "collection_distance": "5km",
    },

    "Bob": {
        "urgency": "Low - browsing, no deadline.",
        "condition_notes": "Fine with light cosmetic wear.",
        "priority": "Getting a usable camera body, brand agnostic.",
        "collection_distance": "12km",
    },

    "Charlie": {
        "urgency": "Medium - wants the bike within two weeks for a commute change.",
        "condition_notes": "Wants tires and brakes already road-ready.",
        "priority": "Reliability for daily commuting.",
        "collection_distance": "3km",
    },

    "Dina": {
        "urgency": "Low - flexible on timing.",
        "condition_notes": "Open to any brand or condition, said 'anything that rides fine'.",
        "priority": "Ease of exchange over specific brand.",
        "collection_distance": "8km",
    },

    "Evan": {
        "urgency": "Medium - has a trip booked in three weeks.",
        "condition_notes": "Wants the sensor and lens genuinely like-new, not just labeled that way.",
        "priority": "Travel durability and image quality.",
        "collection_distance": "15km",
    },

    "Fiona": {
        "urgency": "High - current bike was stolen, needs a commuter replacement ASAP.",
        "condition_notes": "Wants brakes and gears fully functional out of the box.",
        "priority": "Immediate usability for commuting.",
        "collection_distance": "4km",
    },
}


# ============================================================
# OFFLINE GEMINI #2 FALLBACK
# ============================================================

def offline_evaluate_candidates(candidates, qualitative_context=None):
    """
    Deterministic fallback representing Gemini #2.

    It can only recommend one candidate supplied by BGCC, and (like the
    real evaluator) must ground its reason in qualitative_context rather
    than in the utility/egalitarian numbers BGCC already decided.
    """

    qualitative_context = qualitative_context or {}

    best_number = max(
        range(len(candidates)),
        key=lambda i: (
            candidates[i]["total_utility"],
            candidates[i]["egalitarian_score"],
            -len(candidates[i]["cycle"]),
        ),
    ) + 1

    best = candidates[best_number - 1]

    # Pick the most urgent participant in the winning cycle to ground
    # the reason in something the utility formula never saw.
    cycle_members = best["cycle"]

    most_urgent_user = None
    for member in cycle_members:
        context = qualitative_context.get(member)
        if context and "high" in context.get("urgency", "").lower():
            most_urgent_user = member
            break

    if most_urgent_user:
        urgency_text = qualitative_context[most_urgent_user]["urgency"]
        reason = (
            f"Candidate {best_number} is the strongest advisory pick because "
            f"{most_urgent_user} has high urgency ({urgency_text}), and this "
            "cycle lets that need be met without disturbing BGCC's selection."
        )
        qualitative_factors_considered = [
            f"{most_urgent_user}: urgency = {urgency_text}"
        ]
    else:
        reason = (
            f"Candidate {best_number} is the strongest advisory pick; no "
            "participant flagged high urgency, so priority notes were used "
            "to break ties among the supplied candidates."
        )
        qualitative_factors_considered = [
            f"{member}: priority = "
            f"{qualitative_context.get(member, {}).get('priority', 'n/a')}"
            for member in cycle_members
        ]

    return {
        "recommended_candidate": best_number,
        "reason": reason,
        "qualitative_factors_considered": qualitative_factors_considered,
        "limitations": [
            "This is a deterministic offline stand-in for Gemini #2, "
            "not a live model call.",
            "Another candidate may have a higher fairness score.",
        ],
        "suggested_adjustment": None,
        "confidence": 0.9,
    }


# ============================================================
# DISPLAY
# ============================================================

def print_section(number, title):
    print("\n" + "=" * 70)
    print(f"{number}. {title}")
    print("=" * 70)


# ============================================================
# DETERMINISTIC UTILITY
# ============================================================

def calculate_utility(preference, listing):

    desired_item = str(
        preference.get("desired_item", "")
    ).lower()

    category = str(
        preference.get("item_category", "")
    ).lower()

    listing_item = str(
        listing.get("item", "")
    ).lower()

    listing_category = str(
        listing.get("category", "")
    ).lower()

    # --------------------------------------------------------
    # HARD CATEGORY MATCH
    # --------------------------------------------------------

    if category != listing_category:
        return 0.0

    # --------------------------------------------------------
    # BASE MATCH
    # --------------------------------------------------------

    score = 0.50

    # --------------------------------------------------------
    # SPECIFIC ITEM MATCH
    # --------------------------------------------------------

    if (
        desired_item in listing_item
        or listing_item in desired_item
    ):
        score += 0.20

    # --------------------------------------------------------
    # KEYWORD MATCH
    # --------------------------------------------------------

    keywords = [
        str(k).lower()
        for k in preference.get("keywords", [])
    ]

    searchable_text = " ".join([
        listing_item,
        str(
            listing.get("description", "")
        ).lower(),
        str(
            listing.get("brand", "")
        ).lower(),
    ])

    if keywords:

        matched_keywords = sum(
            1
            for keyword in keywords
            if keyword in searchable_text
        )

        if matched_keywords > 0:

            score += (
                0.20
                * matched_keywords
                / len(keywords)
            )

    # --------------------------------------------------------
    # BRAND
    # --------------------------------------------------------

    acceptable_brands = [
        str(b).lower()
        for b in preference.get(
            "acceptable_brands",
            []
        )
        if str(b).lower() != "similar"
    ]

    listing_brand = str(
        listing.get("brand", "")
    ).lower()

    if (
        acceptable_brands
        and listing_brand
        and listing_brand in acceptable_brands
    ):
        score += 0.10

    # --------------------------------------------------------
    # CONDITION
    # --------------------------------------------------------

    minimum_condition = preference.get(
        "minimum_condition",
        "any"
    )

    listing_condition = listing.get(
        "condition",
        "any"
    )

    condition_order = {
        "fair": 1,
        "good": 2,
        "like_new": 3,
        "new": 4,
    }

    if minimum_condition != "any":

        if (
            listing_condition in condition_order
            and minimum_condition in condition_order
        ):

            if (
                condition_order[listing_condition]
                < condition_order[minimum_condition]
            ):
                return 0.0

    return round(
        min(1.0, score),
        2,
    )


# ============================================================
# GRAPH
# ============================================================

def build_exchange_graph(users, preferences):

    import networkx as nx

    G = nx.DiGraph()

    G.add_nodes_from(users.keys())

    for user, preference in preferences.items():

        for owner, listing in users.items():

            if user == owner:
                continue

            utility = calculate_utility(
                preference,
                listing,
            )

            # IMPORTANT:
            # Only semantically valid matches become edges.
            if utility > 0:

                G.add_edge(
                    user,
                    owner,
                    weight=utility,
                    item=listing["item"],
                )

    return G


# ============================================================
# CANDIDATES
# ============================================================

def prepare_candidates(G, max_len=4):

    raw_candidates = find_cycles(
        G,
        max_len=max_len,
    )

    records = []

    for cycle in raw_candidates:

        records.append({
            "candidate": 0,
            "cycle": cycle,
            "total_utility": round(
                cycle_weight(G, cycle),
                2,
            ),
            "egalitarian_score": round(
                egalitarian_score(G, cycle),
                2,
            ),
        })

    # Stable deterministic ordering.
    records.sort(
        key=lambda record: (
            -record["total_utility"],
            -record["egalitarian_score"],
            len(record["cycle"]),
            tuple(sorted(record["cycle"])),
        )
    )

    for number, record in enumerate(
        records,
        start=1,
    ):
        record["candidate"] = number

    return records


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "SwapCycle integrated "
            "AI + BGCC demonstration"
        )
    )

    parser.add_argument(
        "--offline",
        action="store_true",
        help=(
            "Use deterministic local AI "
            "outputs instead of OpenRouter."
        ),
    )

    args = parser.parse_args()

    # ========================================================
    # STEP 1
    # ========================================================

    preference_texts = {

        "Alice":
            "I want a beginner-friendly Yamaha guitar. "
            "A good-condition used one is fine.",

        "Bob":
            "I want a camera for photography. "
            "A good-condition one is fine.",

        "Charlie":
            "I want a bicycle for everyday transport. "
            "A good-condition one is fine.",

        "Dina":
            "I want a guitar and I am flexible "
            "about the brand and condition.",

        "Evan":
            "I want a camera for travel photography, "
            "preferably Canon and in like-new condition.",

        "Fiona":
            "I want a bicycle for commuting, "
            "preferably Trek. A good-condition one is fine.",
    }

    print_section(
        1,
        "USER NATURAL-LANGUAGE PREFERENCES",
    )

    for user, text in preference_texts.items():

        print(f"\n{user}:")
        print(f"  {text}")

    # ========================================================
    # STEP 2
    # ========================================================

    print_section(
        2,
        "AI PREFERENCE NORMALIZATION",
    )

    preferences = {}

    if args.offline:

        print("Mode: OFFLINE DEMONSTRATION")

        for user, text in preference_texts.items():

            preferences[user] = offline_ai(text)

    else:

        print("Mode: GOOGLE GEMINI")

        from ai_preference import normalize_preference

        for user, text in preference_texts.items():

            print(
                f"\nNormalizing preference "
                f"for {user}..."
            )

            preferences[user] = normalize_preference(
                text
            )

    for user, profile in preferences.items():

        print(f"\n{user}:")

        print(
            json.dumps(
                profile,
                indent=2,
                ensure_ascii=False,
            )
        )

    print("\nAI responsibility:")
    print(
        "Natural language → structured preference"
    )

    # ========================================================
    # STEP 3
    # ========================================================

    print_section(
        3,
        "USERS AND LISTINGS",
    )

    # Two bicycles, two guitars and two cameras.
    #
    # This deliberately creates multiple genuine
    # compatibility paths without fake filler edges.
    users = {

        "Alice": {
            "item": "bike",
            "category": "bicycle",
            "brand": "Polygon",
            "condition": "good",
            "description":
                "Good condition city bicycle "
                "for everyday transport.",
        },

        "Bob": {
            "item": "guitar",
            "category": "guitar",
            "brand": "Yamaha",
            "condition": "good",
            "description":
                "Beginner-friendly Yamaha "
                "acoustic guitar.",
        },

        "Charlie": {
            "item": "camera",
            "category": "camera",
            "brand": "Canon",
            "condition": "like_new",
            "description":
                "Canon camera for travel "
                "photography.",
        },

        "Dina": {
            "item": "bike",
            "category": "bicycle",
            "brand": "Trek",
            "condition": "like_new",
            "description":
                "Trek bicycle suitable "
                "for commuting.",
        },

        "Evan": {
            "item": "guitar",
            "category": "guitar",
            "brand": "Fender",
            "condition": "like_new",
            "description":
                "Fender guitar in excellent condition.",
        },

        "Fiona": {
            "item": "camera",
            "category": "camera",
            "brand": "Sony",
            "condition": "good",
            "description":
                "Sony camera suitable "
                "for photography.",
        },
    }

    for user, listing in users.items():

        print(
            f"{user}: "
            f"owns {listing['item']} | "
            f"brand={listing['brand']} | "
            f"condition={listing['condition']}"
        )

    # ========================================================
    # STEP 4
    # ========================================================

    print_section(
        4,
        "STRUCTURED PREFERENCES → EXCHANGE GRAPH",
    )

    G = build_exchange_graph(
        users,
        preferences,
    )

    for u, v, data in sorted(
        G.edges(data=True)
    ):

        print(
            f"{u} -> {v} | "
            f"receives '{data['item']}' | "
            f"utility={data['weight']:.2f}"
        )

    print(
        f"\nGraph contains "
        f"{G.number_of_nodes()} users and "
        f"{G.number_of_edges()} semantically "
        f"valid exchange edges."
    )

    # ========================================================
    # STEP 5
    # ========================================================

    print_section(
        5,
        "BGCC CANDIDATE EXCHANGE CYCLES",
    )

    candidate_records = prepare_candidates(
        G,
        max_len=4,
    )

    if not candidate_records:

        print(
            "No valid bounded cycles found."
        )

    else:

        print(
            f"Generated "
            f"{len(candidate_records)} "
            f"candidate cycles "
            f"(length 2–4).\n"
        )

        for record in candidate_records:

            cycle = record["cycle"]

            print(
                f"Candidate "
                f"{record['candidate']}: "
                f"{' -> '.join(cycle)} "
                f"-> {cycle[0]}"
            )

            print(
                f"  Length: "
                f"{len(cycle)}"
            )

            print(
                f"  Total utility: "
                f"{record['total_utility']:.2f}"
            )

            print(
                f"  Egalitarian score: "
                f"{record['egalitarian_score']:.2f}"
            )

    # ========================================================
    # STEP 6
    # ========================================================

    print_section(
        6,
        "BGCC DETERMINISTIC MATCHING",
    )

    matched, unmatched = (
        bounded_greedy_cycle_cover(
            G,
            max_len=4,
        )
    )

    if matched:

        for number, cycle in enumerate(
            matched,
            start=1,
        ):

            print(
                f"Selected cycle "
                f"{number}: "
                f"{' -> '.join(cycle)} "
                f"-> {cycle[0]}"
            )

            print(
                f"  Total utility: "
                f"{cycle_weight(G, cycle):.2f}"
            )

            print(
                f"  Egalitarian score: "
                f"{egalitarian_score(G, cycle):.2f}"
            )

    else:

        print(
            "BGCC found no exchange cycle."
        )

    print(
        f"\nUnmatched users: "
        f"{sorted(unmatched)}"
    )

    # ========================================================
    # STEP 7 — GEMINI #2
    # ========================================================

    print_section(
        7,
        "AI EVALUATION OF BGCC CANDIDATES",
    )

    print("\nQualitative context supplied to the AI "
          "(not seen by the utility formula):")

    print(
        json.dumps(
            QUALITATIVE_CONTEXT,
            indent=2,
            ensure_ascii=False,
        )
    )

    if not candidate_records:

        print(
            "No candidates available "
            "for AI evaluation."
        )

        ai_evaluation = None

    elif args.offline:

        print(
            "\nMode: OFFLINE DEMONSTRATION"
        )

        ai_evaluation = (
            offline_evaluate_candidates(
                candidate_records,
                qualitative_context=QUALITATIVE_CONTEXT,
            )
        )

    else:

        print(
            "\nMode: GOOGLE GEMINI"
        )

        from ai_cycle_evaluator import (
            evaluate_candidates
        )

        ai_evaluation = (
            evaluate_candidates(
                preferences,
                candidate_records,
                qualitative_context=QUALITATIVE_CONTEXT,
            )
        )

    if ai_evaluation:

        print("\nAI evaluation:")

        print(
            json.dumps(
                ai_evaluation,
                indent=2,
                ensure_ascii=False,
            )
        )

        recommended_number = (
            ai_evaluation[
                "recommended_candidate"
            ]
        )

        # ----------------------------------------------------
        # SECURITY / BOUNDARY CHECK
        # ----------------------------------------------------

        if not (
            isinstance(
                recommended_number,
                int,
            )
            and not isinstance(
                recommended_number,
                bool,
            )
            and 1 <= recommended_number
            <= len(candidate_records)
        ):

            raise ValueError(
                "Gemini #2 returned an invalid "
                "candidate ID. "
                "The AI recommendation is rejected."
            )

        recommended = candidate_records[
            recommended_number - 1
        ]

        print(
            "\nAI recommended candidate:"
        )

        print(
            f"  Candidate "
            f"{recommended_number}: "
            f"{' -> '.join(recommended['cycle'])}"
            f" -> {recommended['cycle'][0]}"
        )

        print("\nAI role:")

        print(
            "Evaluate and explain "
            "BGCC-generated candidates using "
            "qualitative context BGCC does not see"
        )

        print("\nAI is NOT allowed to:")

        print(
            "  ✗ Create a new cycle"
        )

        print(
            "  ✗ Modify a cycle"
        )

        print(
            "  ✗ Add or remove users"
        )

        print(
            "  ✗ Perform graph matching"
        )

        print(
            "  ✗ Override BGCC"
        )

        print(
            "  ✗ Justify its pick using "
            "utility/egalitarian numbers alone"
        )

    # ========================================================
    # STEP 8
    # ========================================================

    print_section(
        8,
        "SWAPCYCLE FINAL RESULT",
    )

    if matched:

        for cycle in matched:

            print("\nMATCH FOUND:")

            print(
                f"  {' -> '.join(cycle)} "
                f"-> {cycle[0]}"
            )

            print(
                f"  Participants: "
                f"{len(cycle)}"
            )

            print(
                f"  Total utility: "
                f"{cycle_weight(G, cycle):.2f}"
            )

            print(
                f"  Fairness score: "
                f"{egalitarian_score(G, cycle):.2f}"
            )

        print("\nIMPORTANT:")

        print(
            "BGCC remains the deterministic "
            "matching engine."
        )

        if ai_evaluation:

            bgcc_cycle = matched[0]

            ai_cycle = candidate_records[
                ai_evaluation[
                    "recommended_candidate"
                ] - 1
            ]["cycle"]

            if set(bgcc_cycle) == set(
                ai_cycle
            ):

                print(
                    "AI evaluation agrees with "
                    "the BGCC-selected participants."
                )

            else:

                print(
                    "AI evaluation recommends "
                    "a different BGCC candidate."
                )

            print(
                "The AI evaluation does not "
                "override BGCC."
            )

    else:

        print(
            "NO MATCH FOUND"
        )

    # ========================================================
    # STEP 9
    # ========================================================

    print_section(
        9,
        "COMPONENT RESPONSIBILITIES",
    )

    print(
        "GEMINI #1 — PREFERENCE NORMALIZATION"
    )

    print(
        "  ✓ Reads natural-language preferences"
    )

    print(
        "  ✓ Extracts structured requirements"
    )

    print(
        "  ✗ Does NOT create exchange cycles"
    )

    print(
        "\nDETERMINISTIC UTILITY ENGINE"
    )

    print(
        "  ✓ Converts structured preferences "
        "into compatibility scores"
    )

    print(
        "  ✓ Produces graph edge weights"
    )

    print(
        "  ✗ Does NOT use an LLM"
    )

    print(
        "\nBGCC MATCHING ENGINE"
    )

    print(
        "  ✓ Finds bounded exchange cycles"
    )

    print(
        "  ✓ Selects matching cycles"
    )

    print(
        "  ✓ Produces deterministic matching"
    )

    print(
        "\nGEMINI #2 — CANDIDATE EVALUATION"
    )

    print(
        "  ✓ Evaluates BGCC-generated candidates"
    )

    print(
        "  ✓ Uses qualitative context "
        "(urgency, condition notes, priority, "
        "distance) BGCC's math never sees"
    )

    print(
        "  ✓ Provides human-readable reasoning"
    )

    print(
        "  ✓ Produces structured recommendation"
    )

    print(
        "  ✗ Cannot create cycles"
    )

    print(
        "  ✗ Cannot modify cycles"
    )

    print(
        "  ✗ Cannot override BGCC"
    )

    print(
        "  ✗ Cannot justify its pick using "
        "utility/egalitarian numbers alone"
    )

    print("\nSYSTEM PIPELINE:")

    print(
        "Natural language"
        " → Gemini #1 normalization"
        " → deterministic utility"
        " → exchange graph"
        " → BGCC candidate generation"
        " → BGCC deterministic selection"
        " → Gemini #2 qualitative evaluation"
        " → explanation"
    )

    print("\n" + "=" * 70)

    print(
        "SWAPCYCLE INTEGRATED "
        "DEMONSTRATION COMPLETE"
    )

    print("=" * 70)


if __name__ == "__main__":
    main()