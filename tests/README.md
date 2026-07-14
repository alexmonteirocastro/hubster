# Hubster tests

## Unit tests

Mock The Hub API responses and verify parsing, settings, and sync diff logic. No Qdrant or network required.

```bash
uv sync --group dev
uv run pytest -v -m "not retrieval and not generation"
```

CI runs unit tests on every pull request and on every push to `main`. Retrieval golden-set and generation eval tests also run in CI against a Qdrant service container (see `.github/workflows/ci.yml`, invoked by `test.yml` and `deploy.yml`).

**Docker:**

```bash
docker compose --profile test run --rm test
```

`seed_dev_qdrant_db` reset and batching behavior is covered by unit tests in `tests/db/test_seed_dev.py` (no Qdrant or network). That is separate from the `@pytest.mark.retrieval` golden-set tests below, which exercise semantic search quality only.

## Retrieval golden-set tests

Evaluate semantic search quality in isolation via `query_jobs_in_qdrant`, using a dedicated dev Qdrant collection (`JOBS_DEV` by default). These tests never touch the production collection (`JOBS_ON_THE_HUB`).

### Prerequisites

1. Qdrant running locally (e.g. `docker compose up qdrant` or the standalone `docker run` from the root README).
2. `.env` configured with `QDRANT_URL`, `EMBEDDING_MODEL`, and distinct values for `QDRANT_COLLECTION_NAME` and `QDRANT_DEV_COLLECTION_NAME`.

### Run retrieval tests

**Local (host):**

```bash
uv run pytest -v -m retrieval
```

**Docker:**

```bash
docker compose --profile test run --rm test-retrieval
```

The `test-retrieval` service waits for Qdrant to be healthy and sets `QDRANT_URL=http://qdrant:6333` inside the container. Qdrant is started automatically via `depends_on`; you can also bring it up first with `docker compose up -d qdrant`.

If Qdrant is not reachable (host runs only), retrieval tests are skipped automatically.

The test session seeds `tests/fixtures/golden_jobs.json` into the dev collection, runs each query in `tests/fixtures/golden_queries.json`, and asserts every expected `job_id` appears in the configured top-k.

### Seed the dev collection from live Hub data

For manual exploration or regenerating the golden set against real listings:

```bash
uv run python main.py --seed-dev
```

This drops and reloads `QDRANT_DEV_COLLECTION_NAME` with the first two pages of Denmark listings via the normal ingestion path.

### Update the golden set

1. Edit `tests/fixtures/golden_jobs.json` if you change the fixed evaluation corpus (keep `job_id` values stable).
2. Edit `tests/fixtures/golden_queries.json`:
   - `query` — natural-language search text
   - `expected_job_ids` — Hub job IDs that must appear in top-k
   - `top_k` — how many results to inspect (default `5`)
3. Run `uv run pytest -v -m retrieval` and adjust queries or expectations until all cases pass.

If you reseed from live data with `--seed-dev`, pick real `job_id` values from that collection when updating `expected_job_ids`.

## Generation eval tests

Evaluate `/chat` orchestration (retrieval → context assembly → `Generator` invocation) using the same dev Qdrant collection as the retrieval golden-set. These tests use a scripted `Generator` — no live Gemini API calls.

### Prerequisites

Same as retrieval tests: local Qdrant, `.env` with distinct production/dev collection names.

### Run generation eval tests

**Local (host):**

```bash
uv run pytest -v -m generation
```

**Docker (combined with retrieval):**

```bash
docker compose --profile test run --rm test-retrieval
```

### Update the generation eval set

1. Keep `tests/fixtures/golden_jobs.json` aligned with the retrieval corpus.
2. Edit `tests/fixtures/golden_generation.json`:
   - `query` — natural-language question passed to `/chat`
   - `expected_source_job_ids` — Hub job IDs that must appear in the response `sources`
   - `mock_answer_substring` — substring expected in the scripted generator's answer
3. Run `uv run pytest -v -m generation` and adjust until all cases pass.

Generation eval tests live in `tests/db/test_generation.py` alongside the retrieval golden-set (shared `retrieval_qdrant` fixture).

Zero-retrieval fallback behavior (no LLM call when context is empty) is covered by unit tests in `tests/api/test_chat.py`, not by this eval set — Qdrant semantic search always returns top-k hits when the collection is non-empty.
