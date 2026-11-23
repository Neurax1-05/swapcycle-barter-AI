# Edge weights: what they are, how sensitive the result is, how to calibrate

## Honest status
The constants in `matching_config.py::EdgeWeights` are **initial heuristic
estimates**. They were chosen by judgement, not derived from data or a
published source. The *form* (an additive weighted sum of per-attribute
scores, clamped to [0,1]) is standard multi-attribute utility modelling
(Keeney & Raiffa, 1976); the *numbers* are not yet calibrated. FYP2 replaces
them with values elicited from QIU students (`survey/SURVEY.md`,
`calibrate_weights.py`).

## Rationale per constant
Every constant now has a one-line rationale in `matching_config.py`. In short:
`base` 0.30 keeps merely "not bad" listings below the 0.50 threshold;
item/category credit (0.35) is the dominant relevance signal; keyword credit
(0.15) is weaker evidence; a condition miss (-0.25) costs more than meeting it
earns (+0.15); brand (0.10) and flexibility (0.10) are minor tie-breakers.

## Sensitivity analysis (measured)
`python experiments/sensitivity_analysis.py` — 300 synthetic users, 6 seeds,
each weight moved +-20% and +-50% one at a time. Baseline matches about 190 of
300 users. Full table: `results/sensitivity.csv`, chart `results/sensitivity.png`.

Worst case over +-50% (mean over seeds):

| Weight | max change in matched users | max change in edges | min overlap of matched set |
|---|---|---|---|
| threshold | 20.2 | 16.2% | 0.87 |
| condition_fail_penalty | 17.3 | 6.2% | 0.87 |
| base | 15.0 | 8.6% | 0.69 |
| category | 8.0 | 3.3% | 0.68 |
| exact_item | 7.7 | 3.3% | 0.65 |
| brand | 4.7 | 0.8% | 0.76 |
| flexibility_scale | 3.8 | 2.0% | 0.76 |
| no_relevance_penalty | 2.7 | 3.0% | 0.98 |
| condition_ok | 2.3 | 1.7% | 0.77 |
| keyword | 2.2 | 0.0% | 0.86 |

**Reading it honestly.** The matching is *not* insensitive to the weights, so
"it doesn't matter" is not a defensible claim. What the data supports:

* Three parameters dominate: the **edge threshold**, **base**, and the
  **condition penalty**. Calibrate these first; the others move the outcome by
  a few users.
* A +-50% change moves matched users by at most about 10%, and the *number*
  of cycles is much more stable than *which* users are matched (overlap
  0.65-0.98). Small edge changes reshuffle greedy choices.
* The weights act mostly through **which edges exist** (threshold, base),
  not through fine-grained ranking among existing edges.

## Ablation (measured, `results/ablation.csv`)
| Variant | change in matched users | overlap with baseline |
|---|---|---|
| no brand term | -5.0 | 0.69 |
| no flexibility term | -4.2 | 0.71 |
| no keyword credit | -4.0 | 0.89 |
| category credit = keyword credit | -4.8 | 0.64 |
| **no condition terms** | **+19.5** | 0.62 |
| brand + condition + flexibility all off | -8.2 | 0.54 |

Removing the condition terms *increases* matches by about 20 users: the
condition requirement is the main thing that stops otherwise-compatible
swaps. That is a real design trade-off (safety/quality versus match rate) to
discuss, and it is the strongest argument for calibrating
`condition_fail_penalty` from user data.

Caveat: the data is synthetic (`experiments/synth.py`); effect sizes on real
QIU listings will differ.

## Calibration plan (FYP2)
1. Run the survey (`survey/SURVEY.md`), 20-30 students.
2. `python calibrate_weights.py survey/responses.csv` -> `calibrated_weights.json`.
3. Load with `EdgeWeights(**json.load(...))` or `SWAP_W_*` env vars.
4. Re-run the sensitivity analysis on the calibrated weights and report both.
5. Validate: ask a held-out group to accept/reject matches and report
   acceptance rate versus the default weights.
