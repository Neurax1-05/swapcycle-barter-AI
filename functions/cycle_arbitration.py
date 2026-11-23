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

import hashlib
import re
from collections import defaultdict

import networkx as nx

DEFAULT_TOP_K = 4
DEFAULT_MIN_WEIGHT_RATIO = 0.6

# Scalability guards (see docs/SCALABILITY.md).
#   max_out_degree : keep only each user's N best outgoing edges before
#                    enumerating cycles. Cycle count grows ~ d^L, so this is
#                    the single most effective lever.
#   max_cycles     : hard stop for enumeration so one dense graph can never
#                    hang a Cloud Function; the run proceeds on what was found.
DEFAULT_MAX_OUT_DEGREE = 12
DEFAULT_MAX_CYCLES = 200_000
ILP_MAX_POOL = 20_000  # above this, the exact solver is skipped (greedy used)


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


def enumerate_cycles(G, max_len=4, max_cycles=None):
    """
    All simple directed cycles with 2 <= length <= max_len.

    Uses NetworkX's length_bound so cycles longer than max_len are never
    generated. (Enumerating every cycle and filtering afterwards blows up
    exponentially on larger graphs and breaks the O(n^2 * d^L) claim.)

    max_cycles optionally caps the result (see enumerate_cycles_capped to
    learn whether the cap was hit).
    """
    return enumerate_cycles_capped(G, max_len, max_cycles)[0]


def enumerate_cycles_capped(G, max_len=4, max_cycles=None):
    """
    Like enumerate_cycles but returns (cycles, truncated).

    Bounded DFS: every cycle is rooted at its lowest-ranked node and only
    visits higher-ranked nodes, so each cycle is produced exactly once and
    the search is O(n * d^(L-1)). This is several times faster than
    nx.simple_cycles(length_bound=...), which spends most of its time
    exploring paths that cannot close within the bound.
    """
    order = {u: i for i, u in enumerate(G.nodes())}
    succ = {u: [v for v in G.successors(u) if v != u] for u in G.nodes()}
    succ_set = {u: set(vs) for u, vs in succ.items()}
    out = []

    for root in G.nodes():
        r = order[root]
        path = [root]
        on_path = {root}

        # iterative DFS: stack of iterators over successors
        stack = [iter(succ[root])]
        while stack:
            v = next(stack[-1], None)
            if v is None:
                stack.pop()
                on_path.discard(path.pop())
                continue
            if order[v] < r or v in on_path:
                continue
            path.append(v)
            on_path.add(v)
            if root in succ_set[v] and len(path) >= 2:
                out.append(list(path))
                if max_cycles is not None and len(out) >= max_cycles:
                    return out, True
            if len(path) < max_len:
                stack.append(iter(succ[v]))
            else:
                on_path.discard(path.pop())
    return out, False


def edge_tiebreak(u, v):
    """
    Deterministic pseudo-random order for equal-weight edges. Breaking ties by
    id would make every buyer keep the same alphabetically-first sellers,
    creating hubs and starving the graph of cycles; hashing spreads the kept
    edges evenly while staying reproducible.
    """
    return hashlib.sha1(f"{u}|{v}".encode("utf-8")).hexdigest()


def trim_to_sccs(G):
    """
    Keep only edges whose endpoints lie in the same strongly connected
    component. A directed cycle can only exist inside one SCC, so every other
    edge (dead ends, one-way chains between groups) can never be part of an
    exchange and only wastes the degree budget and enumeration time.
    """
    comp = {}
    for i, scc in enumerate(nx.strongly_connected_components(G)):
        if len(scc) > 1:
            for u in scc:
                comp[u] = i
    H = nx.DiGraph()
    H.add_nodes_from(G.nodes(data=True))
    for u, v, data in G.edges(data=True):
        if u in comp and comp.get(v) == comp[u]:
            H.add_edge(u, v, **data)
    return H


def prune_graph(G, max_out_degree):
    """
    Copy of G reduced for cycle search:
      1. drop edges that cannot lie on any cycle (outside a shared SCC);
      2. keep each user's `max_out_degree` highest-weight outgoing edges
         (ties broken by edge_tiebreak);
      3. drop edges that the top-k step orphaned (SCC trim again).
    Cycles in the pruned graph are valid cycles of the original graph.
    None / 0 disables pruning entirely.
    """
    if not max_out_degree:
        return G
    base = trim_to_sccs(G)
    H = nx.DiGraph()
    H.add_nodes_from(G.nodes(data=True))
    for u in base.nodes():
        edges = sorted(
            base.out_edges(u, data=True),
            key=lambda e: (-e[2].get("weight", 0.0), edge_tiebreak(u, e[1])),
        )
        for _, v, data in edges[:max_out_degree]:
            H.add_edge(u, v, **data)
    return trim_to_sccs(H)


def _rank_key(G, cycle):
    # Highest utility first; ties go to the fairer cycle (egalitarian score),
    # then deterministically by member ids.
    return (
        -round(cycle_weight(G, cycle), 9),
        -round(egalitarian_score(G, cycle), 9),
        tuple(sorted(cycle)),
    )


# ------------------------------------------------------------------
# Selection
# ------------------------------------------------------------------

def _ilp_pack(G, pool):
    """Exact max-weight set packing over an already-enumerated pool, or None
    if PuLP is missing / the pool is too large / the solver fails."""
    if not pool or len(pool) > ILP_MAX_POOL:
        return None
    try:
        import pulp
    except ImportError:
        return None
    try:
        prob = pulp.LpProblem("CYCLE_PACK", pulp.LpMaximize)
        x = [pulp.LpVariable(f"x_{i}", cat="Binary") for i in range(len(pool))]
        prob += pulp.lpSum(cycle_weight(G, c) * x[i] for i, c in enumerate(pool))
        by_node = defaultdict(list)
        for i, c in enumerate(pool):
            for u in c:
                by_node[u].append(i)
        for ids in by_node.values():
            prob += pulp.lpSum(x[i] for i in ids) <= 1
        prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=10))
        return [pool[i] for i in range(len(pool)) if (x[i].value() or 0) > 0.5]
    except Exception:
        return None


def select_cycles(
    G,
    max_len=4,
    context=None,
    arbiter=None,
    top_k=DEFAULT_TOP_K,
    min_weight_ratio=DEFAULT_MIN_WEIGHT_RATIO,
    log=print,
    max_out_degree=None,
    max_cycles=None,
    solver="greedy",
    stats=None,
):
    """
    Bounded Greedy Cycle Cover with optional AI arbitration.

    Cycles are enumerated ONCE. Each round then takes the best still-available
    cycle; picking a cycle retires every cycle sharing a user with it (via a
    user -> cycles index), so a round costs O(cycles touching the picked
    users) instead of a fresh enumeration of the whole graph.

    context: {user_id: {...qualitative info...}} - users with no entry are
             treated as "no extra information".
    arbiter: callable(records, context) -> dict containing
             "recommended_candidate" (1-based index into records). Each record
             is {"cycle": [...], "total_utility": x, "egalitarian_score": y}.
             None means plain BGCC.
    max_out_degree: keep only each user's best N outgoing edges (None = all).
    max_cycles: stop enumerating after this many cycles (None = no cap).
    solver: "greedy" (default; supports arbitration) or "ilp" (exact packing
            over the same pool; no arbitration; falls back to greedy if the
            pool is too large or PuLP is unavailable).
    stats: optional dict, filled with cycles_enumerated, truncated, edges_used.

    Returns (cycles, remaining_users, decisions) where decisions maps
    frozenset(cycle members) -> details of the AI decision for that cycle.
    """
    context = context or {}
    chosen = []
    decisions = {}

    H = prune_graph(G, max_out_degree)
    pool, truncated = enumerate_cycles_capped(H, max_len, max_cycles)
    if stats is not None:
        stats.update(
            cycles_enumerated=len(pool),
            truncated=truncated,
            edges_used=H.number_of_edges(),
        )
    if truncated:
        log(
            f"    WARNING: cycle enumeration stopped at {len(pool)} cycles "
            f"(max_cycles); results use the cycles found so far. Lower "
            f"max_out_degree to keep the search complete."
        )

    remaining = set(G.nodes())

    # "auto" = exact packing when no AI arbiter is in play, greedy otherwise.
    if solver in ("ilp", "auto") and arbiter is None:
        packed = _ilp_pack(G, pool)
        if packed is not None:
            # CBC stops at its time limit with its best incumbent, which is
            # not guaranteed to beat greedy; never return something worse.
            greedy, _, _ = select_cycles(
                G, max_len, solver="greedy", log=lambda *a: None,
                max_out_degree=max_out_degree, max_cycles=max_cycles,
            )
            if sum(cycle_weight(G, c) for c in greedy) > sum(
                cycle_weight(G, c) for c in packed
            ) + 1e-9:
                packed = greedy
            packed.sort(key=lambda c: _rank_key(G, c))
            for c in packed:
                remaining -= set(c)
            return packed, remaining, decisions
        log("    ILP unavailable or pool too large; using greedy.")

    ranked = sorted(pool, key=lambda c: _rank_key(G, c))
    weights = [cycle_weight(G, c) for c in ranked]
    members = [set(c) for c in ranked]
    alive = [True] * len(ranked)
    by_user = defaultdict(list)
    for i, c in enumerate(ranked):
        for u in c:
            by_user[u].append(i)

    ptr = 0
    while True:
        while ptr < len(ranked) and not alive[ptr]:
            ptr += 1
        if ptr == len(ranked):
            break

        best_i = ptr
        best = ranked[best_i]
        pick = best
        best_users = members[best_i]

        # Competing cycles: alive, share a user with best, not much worse.
        floor = min_weight_ratio * weights[best_i]
        rivals = sorted(
            {
                i
                for u in best
                for i in by_user[u]
                if alive[i] and i != best_i
            }
        )
        conflict = [best]
        for i in rivals:
            if len(conflict) >= top_k:
                break
            if weights[i] >= floor:
                conflict.append(ranked[i])

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
        pick_users = set(pick)
        remaining -= pick_users
        for u in pick_users:
            for i in by_user[u]:
                alive[i] = False

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
