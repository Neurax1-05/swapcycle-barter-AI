# Change log (FYP1 feedback: "algorithm not scalable, many flaws")

Python tests: 213 passing (was 151). New test files:
`test_enumeration.py`, `test_candidate_index.py`, `test_atomic_claim.py`,
`test_normalize_concurrency.py`, `test_calibrate_weights.py`,
`test_functions_in_sync.py`. The Firestore rules tests were extended
(`tests/rules/firestore.rules.test.js`) but **not run** (no emulator available).

## Matching engine
- `cycle_arbitration.py`: enumerate once, user->cycle index, own bounded
  enumerator, SCC trim + top-k pruning, cycle cap, optional ILP, egalitarian
  tie-break, stats.
- `firestore_bridge.py`: inverted-index graph build, early edge cap, no second
  enumeration, configurable weights, atomic claim, run lock, concurrent
  normalisation with retry cap.
- `matching_config.py` (new): every weight with rationale; env overrides.

## Evidence / experiments
- `experiments/scale_benchmark.py`, `pipeline_benchmark.py`,
  `sensitivity_analysis.py`, `synth.py`; outputs in `results/`.
- `calibrate_weights.py`, `survey/SURVEY.md`, `survey/example_responses.csv`.

## Docs
- `docs/SCALABILITY.md`, `docs/WEIGHTS.md`; README and `architecture.md`
  corrected (the AI does choose between competing BGCC candidates).

## Housekeeping
- `sync_functions.py --check` + a test that fails when `functions/` is stale.
- `functions/requirements.txt` gains `pulp` (exact solver).

## Not changed
- Flutter UI, auth domain lock, evaluator prompt, and the original
  `bgcc_prototype.py` benchmark (kept as the FYP1 baseline).
- Reviews are still readable by every QIU user (`firestore.rules`).
- No rate limit on preference creation beyond the new size/shape rules.
