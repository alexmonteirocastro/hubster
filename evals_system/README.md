# Hubster eval review UI (`evals_system/`)

Local Streamlit surface for human-aided retrieval/generation review and wiring the
[`evals/`](../evals/) comparison/sweep harness (ALE-146 / ALE-147). Companion to
the importable `evals/` package — not part of the FastAPI / React production stack.

**Workflow guide (what to enter, how to read metrics):** [GUIDE.md](GUIDE.md)

## Run the app

```bash
uv sync --group eval-ui
uv run --group eval-ui streamlit run evals_system/app.py
```

Requires the same `.env` / Qdrant / LLM credentials used by the CLI scripts under
`scripts/`.

Judgments are stored in `evals_system/data/judgments.db` (gitignored).

## Tests

Judgment SQLite helpers are pure stdlib and do not need Streamlit. CI installs
the `dev` group only. For a full local sync that includes both pytest and
Streamlit:

```bash
uv sync --group dev --group eval-ui
uv run pytest tests/evals_system/
```

## Tabs

| Tab | What it does |
|-----|----------------|
| Review | Query a chosen collection, view sources + answer, tag good/bad/partial, replay history |
| Embeddings | Explicit Run → `compare_embedding_models` |
| Generation | Explicit Run → `compare_generators` (surfaces `GenerationCaseResult.error`) |
| Min-score sweep | Run retrieval once (seed + cache scores); threshold slider is in-memory only |

See [GUIDE.md](GUIDE.md) for the per-tab walkthrough.
