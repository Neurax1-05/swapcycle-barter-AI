"""
SwapCycle - Bounded Greedy Cycle Cover (BGCC) with AI arbitration.

What this adds on top of plain BGCC
-----------------------------------
Plain BGCC repeatedly takes the best-weight cycle among the unmatched users.
That is fine when cycles do not compete, but sometimes two candidate cycles
CONFLICT: they share a user, so only one of them can happen. Example:

    cycle 1:  X -> A -> Y        (A would get the item)
    cycle 2:  X -> B -> Y        (B would get the item)

Plain BGCC picks whichever has the higher utility score, even if B needs the
item far more than A (B has an exam / a recital / a broken bike ...).

Here, when a conflict exists AND we have qualitative context about the users
involved, a scoped AI call (Gemini #2) chooses ONE of the conflicting
candidate cycles. The chosen cycle is accepted, its users leave the pool, and
the loser (A) simply stays in the pool and can be placed into ANOTHER cycle in
a later round. That is the behaviour described in the project checklist.

Guard rails (the AI stays bounded)
----------------------------------
* The AI can ONLY choose among cycles that BGCC itself found (valid cycles).
  It cannot invent a cycle, a user or an item.
* Only cycles with utility >= min_weight_ratio * (best cycle's utility) are
  offered, so the AI cannot sacrifice a lot of total utility for urgency.
* If the AI is unavailable, errors, or returns something invalid, we fall back
  to plain BGCC's choice. The system never depends on the AI to work.
* If no conflict exists, or nobody involved has any qualitative context, the
  AI is not called at all (cheaper, and deterministic).
"""

import re

import networkx as nx

DEFAULT_TOP_K = 4
DEFAULT_MIN_WEIGHT_RATIO = 0.6


# ------------------------------------------------------------------
# Basic cycle helpers
# ------------------------------------------------------------------

def _edges(cycle):
    return list(zip(cycle, cycle[1:] + cycle[:1]))


def cycle_weight(G, cycle):
    """Utilitarian score: total of every participant's satisfaction."""
    return sum(G[u][v]["weight"] for u, v in _edges(cycle))


def egalitarian_score(G, cycle):
    """Fairness score: the least-satisfied participant's satisfaction."""
    return min(G[u][v]["weight"] for u, v in _edges(cycle))


def enumerate_cycles(G, max_len=4):
    """
    All simple directed cycles with 2 <= length <= max_len.

    Uses NetworkX's length_bound so cycles longer than max_len are never
    generated. (Enumerating every cycle and filtering afterwards blows up
    exponentially on larger graphs and breaks the O(n^2 * d^L) claim.)
    """
    return [
        list(c)
        for c in nx.simple_cycles(G, length_bound=max_len)
        if len(c) >= 2
    ]


def _rank_key(G, cycle):
    # Highest utility first; ties broken deterministically by member ids.
    return (-round(cycle_weight(G, cycle), 9), tuple(sorted(cycle)))


# ------------------------------------------------------------------
# Selection
# ------------------------------------------------------------------

def _conflict_set(G, ranked, best, top_k, min_weight_ratio):
    """
    Candidate cycles that compete with `best`: they share at least one user
    with it and are not much worse. `best` is always included and first.
    """
    best_users = set(best)
    floor = min_weight_ratio * cycle_weight(G, best)
    conflict = [best]
    for c in ranked:
        if c is best:
            continue
        if len(conflict) >= top_k:
            break
        if best_users & set(c) and cycle_weight(G, c) >= floor:
            conflict.append(c)
    return conflict


def select_cycles(
    G,
    max_len=4,
    context=None,
    arbiter=None,
    top_k=DEFAULT_TOP_K,
    min_weight_ratio=DEFAULT_MIN_WEIGHT_RATIO,
    log=print,
):
    """
    Bounded Greedy Cycle Cover with optional AI arbitration.

    context: {user_id: {...qualitative info...}} - users with no entry are
             treated as "no extra information".
    arbiter: callable(records, context) -> dict containing
             "recommended_candidate" (1-based index into records). Each record
             is {"cycle": [...], "total_utility": x, "egalitarian_score": y}.
             None means plain BGCC.

    Returns (cycles, remaining_users, decisions) where decisions maps
    frozenset(cycle members) -> details of the AI decision for that cycle.
    """
    context = context or {}
    remaining = set(G.nodes())
    chosen = []
    decisions = {}

    while True:
        candidates = enumerate_cycles(G.subgraph(remaining), max_len)
        if not candidates:
            break

        ranked = sorted(candidates, key=lambda c: _rank_key(G, c))
        best = ranked[0]
        pick = best

        conflict = _conflict_set(G, ranked, best, top_k, min_weight_ratio)
        someone_has_context = any(u in context for c in conflict for u in c)

        if arbiter is not None and len(conflict) >= 2 and someone_has_context:
            records = [
                {
                    "cycle": list(c),
                    "total_utility": round(cycle_weight(G, c), 2),
                    "egalitarian_score": round(egalitarian_score(G, c), 2),
                }
                for c in conflict
            ]
            try:
                result = arbiter(records, context)
                index = result["recommended_candidate"]
                if (
                    isinstance(index, bool)
                    or not isinstance(index, int)
                    or not 1 <= index <= len(conflict)
                ):
                    raise ValueError(
                        f"arbiter chose candidate {index!r}, "
                        f"which was not offered."
                    )
                pick = conflict[index - 1]
                displaced = sorted(
                    {u for c in conflict for u in c} - set(pick)
                )
                decisions[frozenset(pick)] = {
                    "reason": result.get("reason", ""),
                    "qualitative_factors_considered": list(
                        result.get("qualitative_factors_considered", [])
                    ),
                    "limitations": list(result.get("limitations", [])),
                    "suggested_adjustment": result.get("suggested_adjustment"),
                    "confidence": result.get("confidence"),
                    "alternatives_considered": len(conflict),
                    "competing_users": displaced,
                }
                log(
                    f"    AI arbitration: chose {' -> '.join(pick)} "
                    f"over {len(conflict) - 1} conflicting alternative(s)."
                )
            except Exception as exc:  # any AI problem -> plain BGCC
                pick = best
                log(
                    f"    WARNING: AI arbitration failed ({exc}); "
                    f"falling back to plain BGCC for this round."
                )

        chosen.append(pick)
        remaining -= set(pick)

    return chosen, remaining, decisions


# ------------------------------------------------------------------
# Adapters between Firestore data and the evaluator
# ------------------------------------------------------------------

def build_labels(uids, display_names):
    """
    Unique, human-readable labels for the AI (Firestore uids are useless in a
    sentence). First name when it is unique, otherwise the full display name,
    otherwise the full name plus a short uid tag.
    """
    def clean(uid):
        name = (display_names.get(uid) or "").strip()
        return name or f"User {uid[:4]}"

    def first(name):
        token = re.split(r"\s+", name)[0].strip(".,()")
        return token or name

    uids = list(uids)
    labels = {}
    for u in uids:
        real = (display_names.get(u) or "").strip()
        labels[u] = first(real) if real else clean(u)

    def duplicates(mapping):
        seen, dup = {}, set()
        for u, lab in mapping.items():
            key = lab.lower()
            if key in seen:
                dup.add(u)
                dup.add(seen[key])
            seen[key] = u
        return dup

    for u in duplicates(labels):
        labels[u] = clean(u)
    for u in duplicates(labels):
        labels[u] = f"{clean(u)} ({u[:4]})"
    return labels


def build_context(preferences):
    """
    Turn normalized preference documents into qualitative context.

    preferences: iterable of {"userId": ..., "normalized": {...}}.
    Uses urgency / urgency_reason (only ever what the user wrote), the
    free-text notes, and an extreme flexibility value. Users who gave none
    of these get no entry.
    """
    context = {}
    for pref in preferences:
        uid = pref.get("userId")
        norm = pref.get("normalized") or {}
        if not uid:
            continue

        info = {}

        level = str(norm.get("urgency", "none")).strip().lower()
        reason = str(norm.get("urgency_reason", "") or "").strip()
        if level in ("low", "medium", "high"):
            info["urgency"] = f"{level} - {reason}" if reason else level

        notes = str(norm.get("notes", "") or "").strip()
        if notes:
            info["condition_notes"] = notes

        try:
            flexibility = float(norm.get("flexibility"))
        except (TypeError, ValueError):
            flexibility = None
        if flexibility is not None:
            if flexibility <= 0.25:
                info["priority"] = "strict requirements (must-have)"
            elif flexibility >= 0.75:
                info["priority"] = "very flexible, open to alternatives"

        if info:
            wanted = str(norm.get("desired_item", "") or "").strip()
            if wanted:
                info["wants"] = wanted
            context[uid] = info

    return context


def make_ai_arbiter(labels, evaluate_fn, known_items=None):
    """
    Wrap the evaluator (ai_cycle_evaluator.evaluate_candidates or a fake) so
    select_cycles can call it with Firestore uids while the AI only ever sees
    readable names. `labels` maps uid -> label.
    """

    def arbiter(records, context):
        candidates = [
            {
                "cycle": [labels[u] for u in r["cycle"]],
                "total_utility": r["total_utility"],
                "egalitarian_score": r["egalitarian_score"],
            }
            for r in records
        ]

        members = {u for r in records for u in r["cycle"]}
        qualitative = {}
        preferences = {}
        for u in members:
            info = dict(context.get(u, {}))
            wants = info.pop("wants", None)
            qualitative[labels[u]] = info
            preferences[labels[u]] = {"wants": wants} if wants else {}

        return evaluate_fn(
            preferences,
            candidates,
            qualitative_context=qualitative,
            known_items=set(known_items or []),
        )

    return arbiter
