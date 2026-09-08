# SwapCycle Architecture

## Pipeline

```
Flutter UI → Firestore → AI preference normalization → weighted directed exchange graph → BGCC matching engine → match result
```

## AI boundary

The AI converts natural-language preferences into structured fields (item category, acceptable brands, minimum condition, flexibility, keywords). It does **not** select partners or cycles.

BGCC (a deterministic algorithm) builds the exchange graph from those structured fields and remains the sole authority on which cycles are selected as matches.

| Component | Responsibility | Does NOT |
|---|---|---|
| AI (preference normalization) | Free text → structured preference data | Create, select, or modify exchange cycles |
| BGCC (matching engine) | Build exchange graph, find and select bounded cycles | Use an LLM; is fully deterministic |
| AI (candidate evaluation) | Explain and rank BGCC's candidate cycles | Override BGCC's selection |
