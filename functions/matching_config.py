"""
Every tunable number in the SwapCycle matcher, in one place.

WHY THIS FILE EXISTS
--------------------
The edge-weight constants used to be literals buried in compute_edge_weight.
They are *heuristic estimates*, not values derived from data or literature,
and the project should say so openly. Having them here means:

  * each constant has a stated rationale (below);
  * sensitivity_analysis.py can perturb them and show how much the matching
    result actually depends on them;
  * calibrate_weights.py can replace them with values elicited from a user
    survey (FYP2) without touching the algorithm.

The weighted-sum form is a standard additive multi-attribute utility model
(Keeney & Raiffa, "Decisions with Multiple Objectives", 1976). The specific
numbers are initial estimates pending calibration.
"""
import os
from dataclasses import dataclass, fields, replace


@dataclass(frozen=True)
class EdgeWeights:
    # score = base + (item/category/keyword relevance) + brand + condition
    #         + flexibility * flexibility_scale, clamped to [0, 1]
    base: float = 0.30
    #   Starting point so a listing that is merely "not bad" sits below the
    #   0.5 threshold and needs real evidence of relevance to become an edge.
    exact_item: float = 0.35
    #   The wanted item appears in the listing: the strongest relevance signal.
    category: float = 0.35
    #   Same (non-broad) category. Equal to exact_item on purpose for now:
    #   the AI-normalised category is trusted as much as a text match.
    keyword: float = 0.15
    #   Only a keyword matched: weak evidence, so a smaller reward.
    no_relevance_penalty: float = 0.20
    #   Nothing matched at all: push the edge well below the threshold.
    brand: float = 0.10
    #   Listing brand is one the user said is acceptable.
    condition_ok: float = 0.15
    #   Listing meets the user's minimum condition.
    condition_fail_penalty: float = 0.25
    #   Condition below the minimum: penalised more than it is rewarded,
    #   because receiving something worse than required is the costly error.
    flexibility_scale: float = 0.10
    #   A flexible user (0..1) is slightly easier to satisfy.
    threshold: float = 0.50
    #   Minimum score for an edge to exist in the exchange graph.


DEFAULT_WEIGHTS = EdgeWeights()


def weights_from_env(prefix="SWAP_W_"):
    """Override any weight via env, e.g. SWAP_W_THRESHOLD=0.55."""
    overrides = {}
    for f in fields(EdgeWeights):
        raw = os.getenv(prefix + f.name.upper())
        if raw not in (None, ""):
            try:
                overrides[f.name] = float(raw)
            except ValueError:
                pass
    return replace(DEFAULT_WEIGHTS, **overrides) if overrides else DEFAULT_WEIGHTS


@dataclass(frozen=True)
class EngineConfig:
    """Scalability guards passed to select_cycles (see cycle_arbitration)."""
    max_cycle_length: int = 4
    max_out_degree: int = 12     # best N outgoing edges per user
    max_cycles: int = 200_000    # enumeration hard stop
    solver: str = "auto"         # "auto" | "greedy" (AI arbitration) | "ilp" (exact)


def engine_from_env():
    def _int(name, default):
        try:
            return int(os.getenv(name, default))
        except ValueError:
            return default

    d = EngineConfig()
    return EngineConfig(
        max_cycle_length=_int("SWAP_MAX_CYCLE_LENGTH", d.max_cycle_length),
        max_out_degree=_int("SWAP_MAX_OUT_DEGREE", d.max_out_degree),
        max_cycles=_int("SWAP_MAX_CYCLES", d.max_cycles),
        solver=os.getenv("SWAP_SOLVER", d.solver),
    )
