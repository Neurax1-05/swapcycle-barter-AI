# Scalability: what was wrong, what changed, what is measured

## Findings in the original code (measured before changing anything)
Original `select_cycles` on random graphs, L=4:

| Users | Avg degree | Time |
|---|---|---|
| 500 | 6 | 12 s |
| 1000 | 3 | 10 s |
| 1000 | 6 | over 60 s (timed out) |

Root causes:
1. Cycles were re-enumerated from scratch **every round** (rounds x full search).
2. `run_matching` enumerated all cycles **a second time** only to print them.
3. Every buyer got an edge to every plausible seller, so degree grew with the
   user count (cycle count grows ~ d^L).
4. `build_graph` compared every preference with every listing (O(P x L)) and
   printed every edge.
5. LLM normalisation was serial (one 60 s-timeout call at a time) inside a
   300 s Cloud Function; one bad preference was retried forever.
6. No atomic write: two overlapping runs (Cloud Function + `local_listener.py`,
   or a redelivered trigger) could put one user in two open matches.

## Changes (all covered by tests)
| Change | Where |
|---|---|
| Enumerate once; retire cycles via a user->cycles index | `cycle_arbitration.select_cycles` |
| Own bounded DFS enumerator (rooted at lowest node, O(n*d^(L-1))), verified equal to networkx on 72 random cases | `enumerate_cycles_capped` |
| Drop edges outside strongly connected components, keep top-k edges per user (`max_out_degree`, default 12), hard cap on cycles (`max_cycles`) with a warning | `prune_graph`, `trim_to_sccs` |
| Hash tie-break for equal weights (id order created hubs) | `edge_tiebreak` |
| Inverted index so a preference only scores listings that can reach the threshold (identical output to full scan, tested) | `build_graph`, `_candidate_listing_ids` |
| Early top-k cap while building the graph | `build_graph(max_edges_per_buyer=)` |
| Optional exact selection (ILP over the already-enumerated pool), never worse than greedy | `solver="auto"|"ilp"` |
| No second enumeration; log only selected cycles | `run_matching` |
| Thread-pool LLM calls, time budget, attempt counter -> `failed` | `normalize_pending` |
| Atomic claim: per-user locks inside one Firestore transaction; locks self-expire when the match closes | `claim_and_write_match` |
| Single-flight run lock with lease and re-run flag | `run_matching`, `acquire_run_lock` |
| Preference `create` rule: only `userId/rawText/submittedAt/status`, status `pending`, text <= 500 chars (a client could previously submit `status: processed` with its own `normalized`, bypassing the AI) | `firestore.rules` |

## Results
`python experiments/scale_benchmark.py` -> `results/scale_benchmark.csv/png`
(random directed graphs, L=4, selection step only):

| Users | Avg deg 6: original | Avg deg 6: new | Avg deg 12: original | Avg deg 12: new |
|---|---|---|---|---|
| 100 | 0.54 s | 0.007 s | 0.75 s | 0.04 s |
| 200 | 1.9 s | 0.010 s | 3.7 s | 0.06 s |
| 500 | 15 s | 0.02 s | >30 s | 0.10 s |
| 1000 | >30 s | 0.04 s | >30 s | 0.16 s |
| 5000 | not run | 0.2 s | not run | 0.85 s |

`python experiments/pipeline_benchmark.py --big` -> `results/pipeline_benchmark.csv`
(realistic clustered marketplace; graph build + selection, `max_out_degree`=12):

| Users | Edges | build_graph | Cycles enumerated | Selection (greedy) | Users matched |
|---|---|---|---|---|---|
| 200 | 1,913 | 0.05 s | 2,315 | 0.03 s | 124 |
| 1000 | 11,854 | 0.98 s | 5,396 | 0.19 s | 573 |
| 2000 | 23,748 | 4.0 s | 5,628 | 0.36 s | 1,143 |
| 5000 | 59,556 | 26 s | 5,695 | 0.98 s | 2,461 |

## What is still limited (be upfront about these)
* **Graph building is still quadratic-ish in dense categories**: 26 s at 5,000
  users. Next steps: build per category shard, cache normalised listing text,
  and update the graph incrementally instead of rebuilding per run.
* **Every run re-reads all active listings, preferences and matches** from
  Firestore. Needs per-category queries and an incremental design for real
  campus-wide scale.
* **Top-k pruning trades completeness for bounded cost.** On the 500-user
  synthetic market, k=6 / 12 / 24 matched 225 / 300 / 357 users (pool 386 /
  5.5k / 54k cycles). `max_out_degree` is a dial, not a free win.
* **Greedy is a heuristic**: 4-23% below exact (mean about 14% on the random
  graphs; ILP incumbent is time-limited to 10 s, so the true gap is at least
  what is shown). On a 300-user marketplace the exact packing matched 276
  users versus 195 for greedy. `solver="auto"` therefore uses ILP when no AI
  arbitration is involved. CBC can take ~10 s on pools of several thousand
  cycles; above 20,000 cycles it is skipped.
* **AI arbitration is greedy-only** (it needs a sequence of decisions), so
  runs with qualitative context use greedy + arbitration.
* **Random sparse graphs flatter any algorithm**: expected cycle count there
  does not grow with n. Rely on the pipeline benchmark, not the first table.
* The Firestore transaction and rules code is tested against fakes only. It
  has not been run against the Firestore emulator or a live project (the
  emulator could not be downloaded in the build environment).
* The scale benchmark was produced before the SCC trimming was added to
  `prune_graph`; the effect on those random graphs is negligible, but re-run
  it before putting the numbers in a report.
