# SwapCycle

AI + graph-based multi-way bartering system — matches exchanges between 3+ people (n > 2), not just simple 1-to-1 swaps.

Uses a two-stage pipeline:
1. **AI (Gemini)** normalizes natural-language preferences into structured data
2. **BGCC (deterministic algorithm)** builds an exchange graph and finds fair, bounded exchange cycles

The AI never creates a cycle, user or item. Its only decision power is choosing between valid cycles that BGCC already found when they compete for the same user (and BGCC's choice is used if the AI errors). See `architecture.md`.

> FYP1 — Quest International University (QIU). Midsem checkpoint complete; in active development toward the FYP2 build.

## Setup

Install dependencies:
```bash
py -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and add your own key:

⚠️ **Never commit your real `.env` file or API key to source control.**

## Usage

| Command | What it does |
|---|---|
| `py bgcc_prototype.py` | Run matching + visualizations + benchmark |
| `py ai_preference.py` | Run live AI preference normalization |
| `py end_to_end_demo.py --offline` | Full pipeline demo, no API calls (deterministic fallback) |
| `py end_to_end_demo.py` | Full pipeline demo with live AI |

## Scalability, weights and experiments

| Command | What it does |
|---|---|
| `python experiments/scale_benchmark.py` | Runtime and optimality gap vs users (`results/scale_benchmark.csv/png`) |
| `python experiments/sensitivity_analysis.py` | How much the outcome depends on each edge weight, plus ablations |
| `python calibrate_weights.py survey/responses.csv` | Derive weights from the QIU survey (`survey/SURVEY.md`) |
| `python -m pytest tests --ignore=tests/rules` | Python tests |
| `python sync_functions.py --check` | Fail if `functions/` copies are stale |

Tunables live in `matching_config.py` (`SWAP_W_*`, `SWAP_MAX_OUT_DEGREE`,
`SWAP_MAX_CYCLES`, `SWAP_SOLVER`, `SWAP_LLM_WORKERS` environment variables).

## Docs

- `docs/SCALABILITY.md` — what was slow, what changed, measured results
- `docs/WEIGHTS.md` — the edge-weight constants: rationale, sensitivity, calibration plan
- `survey/SURVEY.md` — the calibration survey

- `architecture.md` — system design and component responsibilities
- `firestore_schema.md` — database schema
- `checkpoint_evidence.md` — midsem checkpoint documentation (historical record)
