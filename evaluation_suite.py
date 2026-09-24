"""
SwapCycle - formal matching-engine evaluation (checklist section I).

Produces the three measurements the ILP benchmark does not cover:

  1. Match Rate Ratio (MRR)   users matched at bound L  vs  pairwise-only (L=2)
  2. Fairness distribution    egalitarian scores of matched cycles (not just
                              the average)
  3. Runtime scaling          BGCC wall-clock time as n grows (50 -> 500)

(The optimality gap vs the exact ILP is produced by bgcc_prototype.py.)

Usage:
    python evaluation_suite.py                # full run
    python evaluation_suite.py --quick        # fewer seeds, for a smoke test
    python evaluation_suite.py --out results  # choose the output folder

Outputs (CSV + PNG) go to ./evaluation_results by default.

Synthetic instances use a fixed MEAN OUT-DEGREE d (edge probability d/(n-1)),
because that is what a real community looks like: each person is willing to
take a handful of items, not a fixed fraction of everything on the platform.
"""

import argparse
import csv
import math
import statistics
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no display needed
import matplotlib.pyplot as plt  # noqa: E402

from bgcc_prototype import (  # noqa: E402
    bounded_greedy_cycle_cover,
    cycle_weight,
    egalitarian_score,
    make_synthetic_instance,
)

FAIRNESS_THRESHOLD = 0.5  # same as EDGE_WEIGHT_THRESHOLD in the bridge


def instance(n, degree, seed):
    return make_synthetic_instance(n, degree / (n - 1), seed)


def users_matched(cycles):
    return sum(len(c) for c in cycles)


def quantile(sorted_values, q):
    if not sorted_values:
        return float("nan")
    k = (len(sorted_values) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return sorted_values[lo]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (k - lo)


def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


# ------------------------------------------------------------------
# 1. Match Rate Ratio
# ------------------------------------------------------------------

def run_mrr(out, seeds):
    print("\n=== 1. MATCH RATE RATIO (users matched at bound L vs L = 2) ===")
    configs = [(n, d) for n in (20, 50, 100) for d in (1.5, 2.0, 3.0)]
    per_instance, summary = [], []

    for n, d in configs:
        totals = {2: 0, 3: 0, 4: 0}
        ratios = {3: [], 4: []}
        for seed in range(seeds):
            G = instance(n, d, 5000 + seed)
            matched = {}
            for L in (2, 3, 4):
                cycles, _ = bounded_greedy_cycle_cover(G, L)
                matched[L] = users_matched(cycles)
                totals[L] += matched[L]
            per_instance.append(
                {"n": n, "degree": d, "seed": 5000 + seed,
                 "matched_L2": matched[2], "matched_L3": matched[3],
                 "matched_L4": matched[4]}
            )
            if matched[2] > 0:
                ratios[3].append(matched[3] / matched[2])
                ratios[4].append(matched[4] / matched[2])

        def ratio(L):
            return totals[L] / totals[2] if totals[2] else float("nan")

        users_total = n * seeds
        summary.append(
            {
                "n": n,
                "mean_degree": d,
                "instances": seeds,
                "matched_L2": totals[2],
                "matched_L3": totals[3],
                "matched_L4": totals[4],
                "pct_matched_L2": round(100 * totals[2] / users_total, 1),
                "pct_matched_L4": round(100 * totals[4] / users_total, 1),
                "MRR_L3": round(ratio(3), 2),
                "MRR_L4": round(ratio(4), 2),
                "mean_instance_MRR_L4": (
                    round(statistics.mean(ratios[4]), 2) if ratios[4] else ""
                ),
            }
        )

    write_csv(out / "evaluation_mrr_instances.csv", per_instance)
    write_csv(out / "evaluation_mrr_summary.csv", summary)

    print(f"{'n':>4} {'deg':>4} | {'L=2':>6} {'L=3':>6} {'L=4':>6} | "
          f"{'%L2':>5} {'%L4':>5} | {'MRR3':>5} {'MRR4':>5}")
    for r in summary:
        print(f"{r['n']:>4} {r['mean_degree']:>4} | {r['matched_L2']:>6} "
              f"{r['matched_L3']:>6} {r['matched_L4']:>6} | "
              f"{r['pct_matched_L2']:>5} {r['pct_matched_L4']:>5} | "
              f"{r['MRR_L3']:>5} {r['MRR_L4']:>5}")
    return summary


# ------------------------------------------------------------------
# 2. Fairness distribution
# ------------------------------------------------------------------

def run_fairness(out, seeds):
    print("\n=== 2. FAIRNESS DISTRIBUTION (egalitarian score of matched cycles, L = 4) ===")
    cycle_rows, egal, user_utils = [], [], []

    for n in (50, 100):
        for d in (2.0, 3.0):
            for seed in range(seeds):
                G = instance(n, d, 7000 + seed)
                cycles, _ = bounded_greedy_cycle_cover(G, 4)
                for c in cycles:
                    e = egalitarian_score(G, c)
                    egal.append(e)
                    cycle_rows.append(
                        {"n": n, "degree": d, "seed": 7000 + seed,
                         "cycle_length": len(c),
                         "utilitarian": round(cycle_weight(G, c), 3),
                         "egalitarian": round(e, 3)}
                    )
                    for u, v in zip(c, c[1:] + c[:1]):
                        user_utils.append(G[u][v]["weight"])

    write_csv(out / "evaluation_fairness_cycles.csv", cycle_rows)

    def describe(values):
        s = sorted(values)
        return {
            "count": len(s),
            "mean": round(statistics.mean(s), 3),
            "std": round(statistics.pstdev(s), 3),
            "min": round(s[0], 3),
            "p10": round(quantile(s, 0.10), 3),
            "p25": round(quantile(s, 0.25), 3),
            "median": round(quantile(s, 0.50), 3),
            "p75": round(quantile(s, 0.75), 3),
            "p90": round(quantile(s, 0.90), 3),
            "max": round(s[-1], 3),
        }

    summary = []
    for label, values in (("cycle egalitarian score", egal),
                          ("per-user utility", user_utils)):
        if values:
            row = {"metric": label, **describe(values)}
            row["share_below_0.5"] = round(
                sum(v < FAIRNESS_THRESHOLD for v in values) / len(values), 3)
            summary.append(row)

    write_csv(out / "evaluation_fairness_summary.csv", summary)
    for r in summary:
        print(r)

    if egal:
        fig, ax = plt.subplots(figsize=(6, 3.8))
        ax.hist(egal, bins=15, color="#2a9d8f", edgecolor="white")
        ax.axvline(statistics.mean(egal), color="#e76f51", linestyle="--",
                   label=f"mean = {statistics.mean(egal):.2f}")
        ax.axvline(statistics.median(egal), color="#264653", linestyle=":",
                   label=f"median = {statistics.median(egal):.2f}")
        ax.set_xlabel("Egalitarian score (least-satisfied participant)")
        ax.set_ylabel("Matched cycles")
        ax.set_title("Fairness distribution of BGCC cycles (L = 4)")
        ax.legend()
        fig.tight_layout()
        fig.savefig(out / "evaluation_fairness.png", dpi=160)
        plt.close(fig)
    return summary


# ------------------------------------------------------------------
# 3. Runtime scaling
# ------------------------------------------------------------------

def run_scaling(out, seeds, degree=3.0, sizes=(50, 100, 250, 500),
                time_limit_s=60.0):
    print(f"\n=== 3. RUNTIME SCALING (BGCC, L = 4, mean out-degree {degree}) ===")
    rows, medians = [], []

    for n in sizes:
        times, edges = [], []
        for seed in range(seeds):
            G = instance(n, degree, 9000 + seed)
            t0 = time.perf_counter()
            bounded_greedy_cycle_cover(G, 4)
            times.append(time.perf_counter() - t0)
            edges.append(G.number_of_edges())
            rows.append({"n": n, "edges": G.number_of_edges(),
                         "seed": 9000 + seed,
                         "bgcc_time_s": round(times[-1], 5)})
            if times[-1] > time_limit_s:
                break
        med = statistics.median(times)
        medians.append((n, med))
        print(f"  n={n:>4}  edges~{int(statistics.mean(edges)):>5}  "
              f"median={med:.4f}s  max={max(times):.4f}s")
        if med > time_limit_s:
            print("  (stopping: exceeded time limit)")
            break

    write_csv(out / "evaluation_scaling.csv", rows)

    slope = None
    usable = [(n, t) for n, t in medians if t > 0]
    if len(usable) >= 2:
        xs = [math.log(n) for n, _ in usable]
        ys = [math.log(t) for _, t in usable]
        mx, my = statistics.mean(xs), statistics.mean(ys)
        slope = (sum((x - mx) * (y - my) for x, y in zip(xs, ys))
                 / sum((x - mx) ** 2 for x in xs))
        print(f"  Empirical growth: time ~ n^{slope:.2f} "
              f"(polynomial; slope = log-log fit)")

        fig, ax = plt.subplots(figsize=(6, 3.8))
        ax.loglog([n for n, _ in usable], [t for _, t in usable],
                  "o-", color="#264653")
        ax.set_xlabel("Users (n)")
        ax.set_ylabel("Median BGCC time (s)")
        ax.set_title(f"BGCC runtime scaling (L = 4), time ~ n^{slope:.2f}")
        ax.grid(True, which="both", alpha=0.3)
        fig.tight_layout()
        fig.savefig(out / "evaluation_scaling.png", dpi=160)
        plt.close(fig)
    return medians, slope


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--quick", action="store_true",
                        help="fewer seeds (smoke test)")
    parser.add_argument("--out", default="evaluation_results",
                        help="output folder")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    seeds = 5 if args.quick else 30
    scaling_seeds = 2 if args.quick else 5

    run_mrr(out, seeds)
    run_fairness(out, seeds)
    run_scaling(out, scaling_seeds)

    print(f"\nDone. CSV + PNG files are in: {out.resolve()}")


if __name__ == "__main__":
    main()
