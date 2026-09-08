# SwapCycle

AI + graph-based multi-way bartering system — matches exchanges between 3+ people (n > 2), not just simple 1-to-1 swaps.

Uses a two-stage pipeline:
1. **AI (Gemini)** normalizes natural-language preferences into structured data
2. **BGCC (deterministic algorithm)** builds an exchange graph and finds fair, bounded exchange cycles

The AI never creates, modifies, or overrides a match — it only evaluates and explains BGCC's output. See `architecture.md` for full pipeline details.

> FYP1 prototype — Quest International University (QIU)

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

## Docs

- `architecture.md` — system design and component responsibilities
- `firestore_schema.md` — database schema
- `checkpoint_evidence.md` — FYP checkpoint documentation
