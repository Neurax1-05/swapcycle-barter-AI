"""Sensitivity + ablation of the edge-weight constants.

    python experiments/sensitivity_analysis.py

Answers: "how much does the matching outcome depend on constants that have no
citation?"  Each weight is perturbed one at a time (+-20%, +-50%); each scoring
term is also switched off (ablation). For every setting we rebuild the
exchange graph, run the matcher, and compare to the baseline weights.

Metrics (mean over seeds):
  d_matched   change in number of matched users vs baseline
  d_edges     change in number of graph edges vs baseline (%)
  jaccard     overlap of the SET of matched users with the baseline (1 = same)
Outputs results/sensitivity.csv, results/ablation.csv, results/sensitivity.png
"""
import contextlib, csv, io, sys
from dataclasses import fields, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "experiments"))
import firestore_bridge as bridge
from cycle_arbitration import select_cycles
from matching_config import DEFAULT_WEIGHTS, EdgeWeights
from synth import marketplace

N, SEEDS = 300, range(6)


def run(weights, seed):
    L, P = marketplace(N, seed)
    with contextlib.redirect_stdout(io.StringIO()):
        G = bridge.build_graph(L, P, weights, max_edges_per_buyer=12)
    cycles, rem, _ = select_cycles(G, 4, log=lambda *a: None)
    matched = {u for c in cycles for u in c}
    return matched, G.number_of_edges()


def compare(weights):
    dm, de, jac = [], [], []
    for s in SEEDS:
        bm, be = BASE[s]; m, e = run(weights, s)
        dm.append(len(m) - len(bm)); de.append(100 * (e - be) / be if be else 0)
        u = bm | m; jac.append(len(bm & m) / len(u) if u else 1.0)
    k = len(SEEDS)
    return sum(dm) / k, sum(de) / k, sum(jac) / k


BASE = {s: run(DEFAULT_WEIGHTS, s) for s in SEEDS}
print("baseline matched users:", {s: len(BASE[s][0]) for s in SEEDS})

rows = []
for f in fields(EdgeWeights):
    for pct in (-50, -20, 20, 50):
        w = replace(DEFAULT_WEIGHTS, **{f.name: getattr(DEFAULT_WEIGHTS, f.name) * (1 + pct / 100)})
        dm, de, j = compare(w)
        rows.append(dict(weight=f.name, change_pct=pct, d_matched=round(dm, 2), d_edges_pct=round(de, 2), jaccard=round(j, 3)))
        print(rows[-1], flush=True)
with open(ROOT / "results" / "sensitivity.csv", "w", newline="") as fh:
    w_ = csv.DictWriter(fh, fieldnames=rows[0].keys()); w_.writeheader(); w_.writerows(rows)

ABL = {
    "no brand term": dict(brand=0.0),
    "no condition terms": dict(condition_ok=0.0, condition_fail_penalty=0.0),
    "no flexibility term": dict(flexibility_scale=0.0),
    "no keyword credit": dict(keyword=0.0),
    "category = keyword credit": dict(category=0.15),
    "brand+condition+flexibility off": dict(brand=0.0, condition_ok=0.0, condition_fail_penalty=0.0, flexibility_scale=0.0),
}
arows = []
for name, ov in ABL.items():
    dm, de, j = compare(replace(DEFAULT_WEIGHTS, **ov))
    arows.append(dict(variant=name, d_matched=round(dm, 2), d_edges_pct=round(de, 2), jaccard=round(j, 3)))
    print(arows[-1], flush=True)
with open(ROOT / "results" / "ablation.csv", "w", newline="") as fh:
    w_ = csv.DictWriter(fh, fieldnames=arows[0].keys()); w_.writeheader(); w_.writerows(arows)

import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
names = [f.name for f in fields(EdgeWeights)]
spread = [max(abs(r["d_edges_pct"]) for r in rows if r["weight"] == n) for n in names]
mspread = [max(abs(r["d_matched"]) for r in rows if r["weight"] == n) for n in names]
order = sorted(range(len(names)), key=lambda i: spread[i])
fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
ax[0].barh([names[i] for i in order], [spread[i] for i in order]); ax[0].set_xlabel("max |change in edges| (%) over +-50%")
ax[0].set_title("Graph size sensitivity")
ax[1].barh([names[i] for i in order], [mspread[i] for i in order]); ax[1].set_xlabel("max |change in matched users| over +-50%")
ax[1].set_title("Outcome sensitivity")
plt.tight_layout(); plt.savefig(ROOT / "results" / "sensitivity.png", dpi=150)
