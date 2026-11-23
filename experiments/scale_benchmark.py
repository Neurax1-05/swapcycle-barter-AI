"""Scalability benchmark: runtime and solution quality vs number of users.

    python experiments/scale_benchmark.py [--quick]

Writes results/scale_benchmark.csv and results/scale_benchmark.png.
Compares: NEW greedy (enumerate once + top-k edges), the ORIGINAL greedy
(re-enumerate every round, in a subprocess with a timeout), and an exact ILP
over the same cycle pool (when the pool is small enough).
"""
import argparse, csv, json, os, random, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import networkx as nx
from cycle_arbitration import (select_cycles, cycle_weight, enumerate_cycles_capped,
                               prune_graph, _ilp_pack)

OLD_DIR = os.getenv("SWAP_ORIG_DIR", str(ROOT.parent / "swapcycle_orig"))
OLD_TIMEOUT = 30


def random_graph(n, avg_deg, seed):
    r = random.Random(seed)
    G = nx.DiGraph(); G.add_nodes_from(range(n))
    p = min(1.0, avg_deg / (n - 1))
    for u in range(n):
        for v in range(n):
            if u != v and r.random() < p:
                G.add_edge(u, v, weight=round(r.uniform(.5, 1), 2))
    return G


OLD_SNIPPET = """
import sys, json, time, random
sys.path.insert(0, {old!r})
import networkx as nx
from cycle_arbitration import select_cycles
n, d, seed = {n}, {d}, {seed}
r = random.Random(seed); G = nx.DiGraph(); G.add_nodes_from(range(n))
p = min(1.0, d / (n - 1))
for u in range(n):
    for v in range(n):
        if u != v and r.random() < p:
            G.add_edge(u, v, weight=round(r.uniform(.5, 1), 2))
t = time.time(); c, rem, _ = select_cycles(G, 4, log=lambda *a: None)
print(json.dumps({{"t": time.time() - t, "users": n - len(rem)}}))
"""


def run_old(n, d, seed):
    try:
        out = subprocess.run([sys.executable, "-I", "-c", OLD_SNIPPET.format(old=OLD_DIR, n=n, d=d, seed=seed)],
                             capture_output=True, text=True, timeout=OLD_TIMEOUT)
        return json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    sizes = [100, 200, 500, 1000] if a.quick else [100, 200, 500, 1000, 2000, 5000]
    degs = [6, 12]
    rows = []
    for d in degs:
        for n in sizes:
            for seed in range(1 if a.quick else 2):
                G = random_graph(n, d, seed)
                t = time.time(); st = {}
                c, rem, _ = select_cycles(G, 4, log=lambda *x: None, max_out_degree=12, stats=st)
                t_new = time.time() - t
                w_new = sum(cycle_weight(G, x) for x in c)
                row = dict(n=n, avg_degree=d, seed=seed, new_time_s=round(t_new, 4),
                           pool=st["cycles_enumerated"], truncated=st["truncated"],
                           new_matched_users=n - len(rem), new_weight=round(w_new, 3),
                           old_time_s="", ilp_time_s="", ilp_weight="", gap_pct="")
                if seed == 0 and n <= 1000:
                    old = run_old(n, d, seed)
                    row["old_time_s"] = round(old["t"], 3) if old else f">{OLD_TIMEOUT}"
                pool = enumerate_cycles_capped(prune_graph(G, 12), 4)[0]
                t = time.time(); packed = _ilp_pack(G, pool) if len(pool) <= 5000 else None; t_ilp = time.time() - t
                if packed is not None:
                    w_ilp = sum(cycle_weight(G, x) for x in packed)
                    row.update(ilp_time_s=round(t_ilp, 3), ilp_weight=round(w_ilp, 3),
                               gap_pct=round(100 * (w_ilp - w_new) / w_ilp, 2) if w_ilp else 0)
                rows.append(row); print(row, flush=True)
    out = ROOT / "results" / "scale_benchmark.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
    plot(rows)


def plot(rows):
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
    for d, mk in [(6, "o-"), (12, "s-")]:
        pts = {}
        for r in rows:
            if r["avg_degree"] == d: pts.setdefault(r["n"], []).append(r["new_time_s"])
        xs = sorted(pts); ax[0].plot(xs, [sum(pts[x]) / len(pts[x]) for x in xs], mk, label=f"new greedy, avg degree {d}")
        old = [(r["n"], r["old_time_s"]) for r in rows if r["avg_degree"] == d and r["old_time_s"] not in ("",)]
        ox = [n for n, t in old if not str(t).startswith(">")]; oy = [t for n, t in old if not str(t).startswith(">")]
        ax[0].plot(ox, oy, mk.replace("-", "--"), alpha=.6, label=f"original greedy, avg degree {d}")
        for n, t in old:
            if str(t).startswith(">"): ax[0].plot([n], [OLD_TIMEOUT], "x", color="red")
    ax[0].set_xscale("log"); ax[0].set_yscale("log"); ax[0].set_xlabel("users"); ax[0].set_ylabel("seconds")
    ax[0].set_title("Selection runtime (red x = original timed out)"); ax[0].legend(fontsize=7)
    gaps = {}
    for r in rows:
        if r["gap_pct"] != "": gaps.setdefault(r["n"], []).append(r["gap_pct"])
    xs = sorted(gaps); ax[1].bar([str(x) for x in xs], [sum(gaps[x]) / len(gaps[x]) for x in xs])
    ax[1].set_xlabel("users"); ax[1].set_ylabel("greedy gap to exact ILP (%)")
    ax[1].set_title("Solution quality (where ILP was tractable)")
    plt.tight_layout(); plt.savefig(ROOT / "results" / "scale_benchmark.png", dpi=150)


if __name__ == "__main__":
    main()
