# Hubster eval review UI (ALE-146)

Local Streamlit app for human-aided retrieval/generation review and wiring the
[`evals/`](../evals/) comparison/sweep harness (ALE-147).

Not part of the FastAPI / React production stack.

## Run the app

```bash
uv sync --group eval-ui
uv run --group eval-ui streamlit run streamlit_app/app.py
```

Requires the same `.env` / Qdrant / LLM credentials used by the CLI scripts under
`scripts/`.

Judgments are stored in `streamlit_app/data/judgments.db` (gitignored).

## Tests

Judgment SQLite helpers are pure stdlib and do not need Streamlit. CI installs
the `dev` group only. For a full local sync that includes both pytest and
Streamlit:

```bash
uv sync --group dev --group eval-ui
uv run pytest tests/streamlit_app/
```

## Tabs

| Tab | What it does |
|-----|----------------|
| Review | Query a chosen collection, view sources + answer, tag good/bad/partial, replay history |
| Embeddings | Explicit Run → `compare_embedding_models` |
| Generation | Explicit Run → `compare_generators` (surfaces `GenerationCaseResult.error`) |
| Min-score sweep | Run retrieval once (seed + cache scores); threshold slider is in-memory only |
