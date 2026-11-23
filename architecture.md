# SwapCycle Architecture

## Pipeline

```
Flutter UI → Firestore → AI preference normalization → weighted directed exchange graph → BGCC matching engine → match result
```

## AI boundary

| Component | Responsibility | Does NOT |
|---|---|---|
| AI (preference normalization) | Free text -> structured preference data | Create, select, or modify exchange cycles |
| Exchange-graph builder + BGCC (deterministic) | Build the weighted graph, enumerate bounded cycles, select a vertex-disjoint set | Use an LLM |
| AI (arbitration, optional) | When several valid cycles **compete for the same user** and someone has urgency/notes context, choose ONE of BGCC's own candidates | Invent cycles, users or items; it is only consulted for conflicts and BGCC's choice is used if it errors or answers invalidly |

Be precise about the last row: in conflicts the AI **does** decide between
candidates the algorithm found (within `top_k` and `min_weight_ratio` of the
best), so BGCC is the sole *generator and validator* of cycles, not the sole
*selector*. The model's output is stored as an advisory explanation
(`aiEvaluation`).

## Scalability design (see `docs/SCALABILITY.md`)

```
preferences x listings
   -> candidate index (inverted index on tokens/category)   avoids O(P x L)
   -> top-k edges per buyer (max_out_degree)                bounds d in d^L
   -> bounded DFS cycle enumeration, ONCE (L <= 4)          O(n * d^(L-1))
   -> selection: exact ILP over the pool (no AI needed)  |  greedy + AI arbitration
   -> atomic write: per-user locks inside a Firestore transaction
   -> single-flight run lock (Cloud Function and local_listener never overlap)
```

Edge weights are configurable heuristics (`matching_config.py`,
`docs/WEIGHTS.md`), not derived constants.
