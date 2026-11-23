"""End-to-end runtime on realistic (clustered) marketplace data.

Random sparse graphs understate the problem: their cycle count does not grow
with n. Real marketplaces cluster by category, so the number of edges and
cycles per user is much higher. This benchmark builds the exchange graph from
synthetic listings/preferences (experiments/synth.py) exactly as run_matching
does, then selects cycles.

    python experiments/pipeline_benchmark.py            # n up to 2000
    python experiments/pipeline_benchmark.py --big      # adds 5000
Writes results/pipeline_benchmark.csv
"""
import contextlib, csv, io, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "experiments"))
import firestore_bridge as bridge
from cycle_arbitration import select_cycles
from synth import marketplace

sizes = [200, 500, 1000, 2000] + ([5000] if "--big" in sys.argv else [])
rows = []
for n in sizes:
    L, P = marketplace(n, 1)
    for k in (6, 12):
        t = time.time()
        with contextlib.redirect_stdout(io.StringIO()):
            G = bridge.build_graph(L, P, max_edges_per_buyer=k)
        t_build = time.time() - t
        st = {}; t = time.time()
        c, rem, _ = select_cycles(G, 4, log=lambda *a: None, solver="greedy", stats=st, max_cycles=200_000)
        t_sel = time.time() - t
        rows.append(dict(users=n, max_out_degree=k, edges=G.number_of_edges(), build_graph_s=round(t_build, 2),
                         cycles_enumerated=st["cycles_enumerated"], truncated=st["truncated"],
                         select_s=round(t_sel, 2), matched_users=n - len(rem)))
        print(rows[-1], flush=True)
with open(ROOT / "results" / "pipeline_benchmark.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
