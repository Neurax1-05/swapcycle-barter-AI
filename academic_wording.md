# Academic Wording

Reference phrasing for reports, the defence script, and supervisor Q&A — precise terms to avoid overclaiming.

## Model

SwapCycle models item exchanges as a **directed, weighted exchange graph**:
- Users are vertices
- Feasible desired-item transfers are directed edges
- Edge weights represent estimated receiving-user utility

## BGCC algorithm

BGCC repeatedly selects the highest-weight feasible directed cycle (up to a predefined maximum length), removes its participating vertices, and continues until no bounded cycle remains.

## AI role

The AI component has a **bounded preference-normalization role**: it converts free-form natural-language preferences into structured data consumed by the deterministic matching layer. It does **not** select the final exchange cycle.

## Evaluation

BGCC is evaluated against an exact ILP (Integer Linear Programming) formulation using: total utility, matched cycles, optimality gap, and runtime.

## Claims to avoid

- ❌ "BGCC is always optimal"
- ✅ "BGCC matched the exact ILP objective on the tested instances" — state only what the measurements actually show
