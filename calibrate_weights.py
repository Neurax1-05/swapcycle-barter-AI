"""Derive EdgeWeights from survey data instead of hand-picked constants.

    python calibrate_weights.py survey/responses.csv  [--base 0.30] [--out weights.json]

Input CSV (one row per respondent), see survey/SURVEY.md:
  pts_item, pts_brand, pts_condition, pts_openness     (Part A, sum to 100)
  ahp_item_brand, ahp_item_condition, ahp_item_openness,
  ahp_brand_condition, ahp_brand_openness, ahp_condition_openness
                                                       (Part B, Saaty 1/9..9;
                                                        >1 means the FIRST is
                                                        more important)
Either part may be omitted; if both are present they are averaged.

How the importances become EdgeWeights
  The score is  base + relevance + brand + condition + openness  and the four
  terms share the remaining budget (1 - base), so a perfect listing scores 1.
  keyword credit and the two penalties keep the ratios they have in the
  default weights (a documented assumption - Part C/D of the survey can be
  used to fit them directly).  The edge threshold is taken from Part D
  (`min_acceptable`, mean of the "lowest score you would still accept") when
  present.
"""
import argparse
import csv
import json
import math
from dataclasses import asdict, replace
from pathlib import Path

from matching_config import DEFAULT_WEIGHTS

ATTRS = ["item", "brand", "condition", "openness"]


def ahp_weights(pairs):
    """pairs: {(a, b): ratio a-over-b}. Geometric-mean AHP; returns (w, CR)."""
    n = len(ATTRS)
    M = [[1.0] * n for _ in range(n)]
    for (a, b), r in pairs.items():
        i, j = ATTRS.index(a), ATTRS.index(b)
        M[i][j], M[j][i] = r, 1.0 / r
    gm = [math.prod(row) ** (1 / n) for row in M]
    w = [g / sum(gm) for g in gm]
    # consistency ratio (Saaty): lambda_max via A*w
    aw = [sum(M[i][j] * w[j] for j in range(n)) for i in range(n)]
    lam = sum(aw[i] / w[i] for i in range(n)) / n
    ci = (lam - n) / (n - 1)
    ri = {3: 0.58, 4: 0.90, 5: 1.12}[n]
    return dict(zip(ATTRS, w)), ci / ri


def read(path):
    rows = list(csv.DictReader(open(path, newline="", encoding="utf-8")))
    if not rows:
        raise SystemExit("no responses")
    return rows


def importances(rows, min_cr=0.2):
    point_sets, ahp_sets, dropped = [], [], 0
    for r in rows:
        if all(r.get(f"pts_{a}") not in (None, "") for a in ATTRS):
            p = [float(r[f"pts_{a}"]) for a in ATTRS]
            if sum(p) > 0:
                point_sets.append([x / sum(p) for x in p])
        keys = [(a, b) for i, a in enumerate(ATTRS) for b in ATTRS[i + 1:]]
        if all(r.get(f"ahp_{a}_{b}") not in (None, "") for a, b in keys):
            w, cr = ahp_weights({(a, b): float(r[f"ahp_{a}_{b}"]) for a, b in keys})
            if cr <= min_cr:           # drop inconsistent respondents
                ahp_sets.append([w[a] for a in ATTRS])
            else:
                dropped += 1
    sets = point_sets + ahp_sets
    if not sets:
        raise SystemExit("no usable Part A / Part B answers")
    mean = [sum(s[i] for s in sets) / len(sets) for i in range(len(ATTRS))]
    return dict(zip(ATTRS, mean)), len(sets), dropped


def to_weights(imp, base=0.30, threshold=None):
    d = DEFAULT_WEIGHTS
    budget = 1.0 - base
    exact = budget * imp["item"]
    cond = budget * imp["condition"]
    return replace(
        d,
        base=base,
        exact_item=round(exact, 3),
        category=round(exact, 3),
        keyword=round(exact * d.keyword / d.exact_item, 3),
        brand=round(budget * imp["brand"], 3),
        condition_ok=round(cond, 3),
        condition_fail_penalty=round(cond * d.condition_fail_penalty / d.condition_ok, 3),
        flexibility_scale=round(budget * imp["openness"], 3),
        threshold=round(threshold, 3) if threshold is not None else d.threshold,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--base", type=float, default=0.30)
    ap.add_argument("--out", default="calibrated_weights.json")
    a = ap.parse_args()
    rows = read(a.csv)
    imp, used, dropped = importances(rows)
    thr = [float(r["min_acceptable"]) for r in rows if r.get("min_acceptable") not in (None, "")]
    w = to_weights(imp, a.base, sum(thr) / len(thr) if thr else None)
    print(f"answer sets used: {used} (inconsistent AHP dropped: {dropped}) of {len(rows)} rows")
    print("importances:", {k: round(v, 3) for k, v in imp.items()})
    print("EdgeWeights:", json.dumps(asdict(w), indent=2))
    Path(a.out).write_text(json.dumps(asdict(w), indent=2))
    print(f"saved {a.out}; load with EdgeWeights(**json.load(open('{a.out}')))")


if __name__ == "__main__":
    main()
