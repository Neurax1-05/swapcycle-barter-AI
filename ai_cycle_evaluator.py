import json
import os
import re

import requests
from dotenv import load_dotenv


load_dotenv()

URL = "https://openrouter.ai/api/v1/chat/completions"

MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "google/gemini-2.5-flash-lite",
)


SYSTEM = """
You are SwapCycle's trade-recommendation component.

The graph-matching engine (BGCC) has already found several VALID exchange
cycles. Validity, participants, and utility/egalitarian scores are fully
decided by BGCC's math — you cannot change, question, or re-derive them.

Your job is different: decide which of the ALREADY-VALID cycles is the most
SUITABLE real-world choice, using information the utility formula does not
see. You are given, per user, qualitative context:
  - urgency (how soon they need the item)
  - condition_notes (free-text detail beyond the coarse condition label,
    e.g. "barely used" vs "functional but scuffed")
  - priority (what the user said matters most to them)
  - collection_distance (if provided)

IMPORTANT RULES:

- You may ONLY recommend one candidate ID that appears in the supplied data.
- Do NOT create a new cycle, add participants, remove participants, or
  invent candidate IDs.
- Do NOT perform graph matching and do NOT override BGCC's validity or
  score calculations.
- Do NOT base your reason primarily on total_utility or egalitarian_score —
  those are already decided by BGCC. If two or more candidates are close in
  utility, that is exactly when your qualitative judgment matters most.
- Your reason MUST reference at least one specific qualitative factor
  (urgency, condition_notes, priority, or collection_distance) drawn from
  the supplied data. A reason that only cites utility/fairness numbers is
  invalid.
- The qualitative factor(s) you cite MUST belong to a user who is actually
  a participant in the candidate cycle you are recommending. Do not cite
  another user's urgency, condition notes, priority, or distance to justify
  a cycle they are not part of.
- You may propose ONE small, clearly-labeled trade adjustment ONLY if it
  involves items/users already present in the supplied data (e.g.
  suggesting the cycle proceed but flagging a condition mismatch the users
  should confirm). Never invent a new item, user, or value.
- Do NOT mention any user who is NOT a participant of the candidate you
  recommend, not even to compare ("X needs it more than Y"). Other users'
  details are private to them and this explanation is shown to the
  participants of the recommended cycle. Explain the choice using only the
  recommended cycle's own participants.
- Your recommendation is ADVISORY. BGCC remains the authoritative
  deterministic matching engine for validity and scoring.
- Return JSON only.

Return exactly:

{
  "recommended_candidate": 1,
  "reason": "short explanation citing a specific qualitative factor",
  "qualitative_factors_considered": ["..."],
  "limitations": ["..."],
  "suggested_adjustment": "string or null",
  "confidence": 0.0
}

The recommended_candidate MUST be one of the supplied candidate numbers.
confidence must be between 0.0 and 1.0.
"""


def _users_mentioned(text, known_users):
    """Return the subset of known_users whose name appears in text."""

    # Whole-word match, so a user called "Al" is not "found" inside "Alice".
    return {
        user
        for user in known_users
        if re.search(
            r"(?<!\w)" + re.escape(user.lower()) + r"(?!\w)",
            text.lower(),
        )
    }


def validate_result(result, candidates, known_users, known_items):

    if not isinstance(result, dict):
        raise ValueError(
            "AI evaluator did not return a JSON object."
        )

    required_fields = {
        "recommended_candidate",
        "reason",
        "qualitative_factors_considered",
        "limitations",
        "suggested_adjustment",
        "confidence",
    }

    missing = required_fields - result.keys()

    if missing:
        raise ValueError(
            "AI evaluator response is missing fields: "
            f"{sorted(missing)}"
        )

    candidate_count = len(candidates)

    candidate_id = result["recommended_candidate"]

    if (
        isinstance(candidate_id, bool)
        or not isinstance(candidate_id, int)
        or not (1 <= candidate_id <= candidate_count)
    ):
        raise ValueError(
            "AI evaluator attempted to recommend "
            "a candidate that was not supplied."
        )

    if not isinstance(result["qualitative_factors_considered"], list):
        raise ValueError(
            "qualitative_factors_considered must be a JSON list."
        )

    if not isinstance(result["limitations"], list):
        raise ValueError("limitations must be a JSON list.")

    if not isinstance(result["reason"], str) or not result["reason"].strip():
        raise ValueError("reason must be a non-empty string.")

    # --------------------------------------------------------------
    # BOUNDARY CHECK: reason must always cite a qualitative factor.
    # This is the exact failure mode the supervisor flagged — the AI
    # rewriting a result the math already decided, or hand-waving with
    # no grounding at all.
    #
    # FIX: this used to only fire when the reason mentioned utility/
    # fairness AND nothing qualitative, so a reason with neither
    # (e.g. "Candidate 1 is the best overall choice.") slipped through
    # unchecked. The rule from the system prompt is unconditional —
    # every reason must cite a qualitative factor — so the check now
    # enforces that directly instead of only catching the utility-only
    # case.
    # --------------------------------------------------------------
    reason_lower = result["reason"].lower()

    qualitative_terms = (
        "urgen",
        "condition",
        "priorit",
        "distance",
        "need",
        "prefer",
    )

    mentions_qualitative = any(t in reason_lower for t in qualitative_terms)

    if not mentions_qualitative:
        raise ValueError(
            "AI evaluator's reason does not reference a qualitative "
            "factor (urgency, condition, priority, or distance). A "
            "reason grounded only in utility/fairness numbers, or in "
            "nothing at all, is invalid."
        )

    # --------------------------------------------------------------
    # BOUNDARY CHECK: the qualitative factors cited must belong to a
    # participant of the RECOMMENDED cycle, not some other candidate's
    # cycle. Citing e.g. "Fiona's stolen bike" to justify a cycle that
    # does not contain Fiona is a mismatched, unsupported justification
    # even though it looks like valid qualitative reasoning.
    # --------------------------------------------------------------
    cycle_members = set(candidates[candidate_id - 1].get("cycle", []))

    combined_reasoning_text = " ".join([
        result["reason"],
        *[str(factor) for factor in result["qualitative_factors_considered"]],
    ])

    mentioned_users = _users_mentioned(
        combined_reasoning_text,
        known_users,
    )

    users_outside_cycle = mentioned_users - cycle_members

    if users_outside_cycle:
        raise ValueError(
            "AI evaluator cited qualitative factors belonging to "
            f"{sorted(users_outside_cycle)}, who are not participants "
            f"in recommended candidate {candidate_id} "
            f"({sorted(cycle_members)}). Reasoning must be grounded in "
            "the recommended cycle's own participants."
        )

    if not (mentioned_users & cycle_members):
        raise ValueError(
            "AI evaluator's reasoning does not name any participant "
            f"of recommended candidate {candidate_id} "
            f"({sorted(cycle_members)}). Reason must cite a qualitative "
            "factor belonging to someone actually in that cycle."
        )

    # --------------------------------------------------------------
    # BOUNDARY CHECK: suggested_adjustment cannot invent new
    # users/items not present in the supplied data.
    #
    # FIX: known_items previously was built from candidates' "cycle"
    # lists, which are lists of usernames, not item names — so this
    # check was silently comparing against usernames twice and never
    # actually validated against real item/brand data. known_items is
    # now built by the caller from the real listing data (item names
    # and brands) and passed in directly.
    # --------------------------------------------------------------
    adjustment = result["suggested_adjustment"]

    if adjustment is not None:

        if not isinstance(adjustment, str):
            raise ValueError(
                "suggested_adjustment must be a string or null."
            )

        adjustment_lower = adjustment.lower()

        mentioned_known_entity = any(
            name.lower() in adjustment_lower
            for name in (known_users | known_items)
        )

        if not mentioned_known_entity:
            raise ValueError(
                "suggested_adjustment did not reference any known "
                "user or item from the supplied data — possible "
                "invented entity."
            )

    try:
        confidence = float(result["confidence"])
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence must be numeric.") from exc

    if not (0.0 <= confidence <= 1.0):
        raise ValueError("confidence must be between 0.0 and 1.0.")

    result["confidence"] = round(confidence, 2)

    return result


def evaluate_candidates(
    preferences,
    candidates,
    qualitative_context=None,
    known_items=None,
):
    """
    Evaluate ONLY candidates generated by BGCC, using qualitative context
    (urgency, condition detail, priority, distance) that BGCC's utility
    formula does not see.

    qualitative_context: dict keyed by username, e.g.
        {
          "Alice": {
            "urgency": "high - needs guitar before a recital next week",
            "condition_notes": "wants an actually clean fretboard, not just 'good'",
            "priority": "condition over speed",
            "collection_distance": "5km"
          },
          ...
        }

    known_items: an optional set of real item names / brands drawn from
    the actual listing data (e.g. {"guitar", "Yamaha", "camera", "Canon",
    ...}). This is what suggested_adjustment is checked against, so it
    must reflect genuine items in the system, not usernames — pass this
    in from the caller, which has access to the `users` listing dict.
    If omitted, the suggested_adjustment check falls back to known_users
    only, which is stricter than intended, so callers should supply it.

    The AI cannot create, modify, or override a cycle — see SYSTEM prompt.
    """

    api_key = os.getenv("OPENROUTER_API_KEY")

    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured.")

    qualitative_context = qualitative_context or {}
    known_items = known_items or set()

    known_users = set(preferences.keys()) | set(qualitative_context.keys())

    payload = {
        "preferences": preferences,
        "qualitative_context": qualitative_context,
        "candidates": candidates,
        "note": (
            "total_utility and egalitarian_score below are already "
            "final, BGCC-decided values. Use qualitative_context to "
            "choose among candidates, not these numbers. Any "
            "qualitative factor you cite must belong to a participant "
            "of the candidate you actually recommend."
        ),
    }

    response = requests.post(
        URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        },
        timeout=60,
    )

    response.raise_for_status()

    data = response.json()

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(
            "Unexpected OpenRouter response format."
        ) from exc

    try:
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "AI evaluator did not return valid JSON."
        ) from exc

    return validate_result(
        result,
        candidates,
        known_users,
        known_items,
    )