# Academic wording

SwapCycle models item exchanges as a directed, weighted exchange graph. Users are vertices; feasible desired-item transfers are directed edges; edge weights represent estimated receiving-user utility.

BGCC repeatedly selects the highest-weight feasible directed cycle up to a predefined maximum length, removes its participating vertices, and continues until no bounded cycle remains.

The AI component has a bounded preference-normalization role: it converts free-form natural-language preferences into structured data consumed by the deterministic matching layer. It does not select the final exchange cycle.

BGCC is evaluated against an exact ILP formulation using total utility, matched cycles, optimality gap, and runtime.

Do not claim BGCC is always optimal. Say it matched the exact ILP objective on the tested instances when that is what the measurements show.
