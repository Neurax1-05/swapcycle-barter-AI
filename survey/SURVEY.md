# SwapCycle weight-calibration survey (QIU students)

**Purpose.** The edge-weight constants are currently heuristic estimates. This
short survey measures how much QIU students care about each aspect of an item
they would receive in a swap, so the weights can be derived from data
(`python calibrate_weights.py responses.csv`). Target: 20-30 respondents.
Anonymous; no personal data. ~3 minutes.

**Intro text for respondents.** "Imagine you listed a textbook and asked for a
guitar. A student offers you a guitar in a swap. These questions ask how much
different things about that offer matter to you."

## Part A - Point allocation (columns `pts_*`)
You have **100 points**. Spread them over what matters when judging an offered
item. More points = more important. Must total 100.

| Aspect | Meaning | Column |
|---|---|---|
| Item match | It is exactly (or very close to) what I asked for | `pts_item` |
| Brand | It is a brand I find acceptable | `pts_brand` |
| Condition | It is in at least the condition I require | `pts_condition` |
| Openness | I am relaxed about details; I would accept alternatives | `pts_openness` |

## Part B - Pairwise comparison (columns `ahp_<a>_<b>`)
For each pair, which matters more, and by how much? Use **1** = equal,
**3** = moderately more, **5** = strongly more, **7** = very strongly,
**9** = extremely more. If the SECOND matters more, answer the reciprocal
(1/3, 1/5, 1/7, 1/9). (Online form: show two radio rows and convert.)

1. Item match vs Brand -> `ahp_item_brand`
2. Item match vs Condition -> `ahp_item_condition`
3. Item match vs Openness -> `ahp_item_openness`
4. Brand vs Condition -> `ahp_brand_condition`
5. Brand vs Openness -> `ahp_brand_openness`
6. Condition vs Openness -> `ahp_condition_openness`

The calibration script computes Saaty's consistency ratio per respondent and
drops answers with CR > 0.2 (contradictory comparisons).

## Part C - Scenario ratings (optional, for fitting penalties)
Rate each offer 1-7 ("how happy would you be with this swap?"). Suggested set
(wanted: *acoustic guitar*, minimum condition: *good*):

| # | Offer |
|---|---|
| 1 | Acoustic guitar, good, brand you accept |
| 2 | Acoustic guitar, fair (below your minimum), brand you accept |
| 3 | Acoustic guitar, good, brand you did not list |
| 4 | Ukulele (same category), like new |
| 5 | Keyboard (different category), new |
| 6 | Acoustic guitar, poor |

Use these to sanity-check the penalty sizes (e.g. offer 2 should rate clearly
below offer 1; the model currently subtracts 0.25 for a condition miss).

## Part D - Acceptance threshold (column `min_acceptable`)
"Out of the offers above, what is the lowest rating (as a fraction of the 7-point
scale, e.g. 4/7 = 0.57) you would still say yes to?" -> `min_acceptable`.
The mean becomes the edge threshold.

## Part E - Demographics (optional, for the report only)
Year of study, programme, number of items swapped/sold before. Do not collect
names or student IDs.

## How to cite it in the report
"Attribute weights were elicited from N = __ QIU students using point
allocation and AHP pairwise comparison (Saaty, 1980); respondents with
consistency ratio > 0.2 were excluded. The additive form follows
multi-attribute utility theory (Keeney & Raiffa, 1976)." Verify both
references against the originals before citing.
