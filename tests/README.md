# Hubster tests

## Unit tests

Mock The Hub API responses and verify parsing, settings, and sync diff logic. No Qdrant or network required.

```bash
uv sync --group dev
uv run pytest -v -m "not retrieval and not generation"
```

CI runs unit tests on every pull request and on every push to `main`. Retrieval golden-set and generation eval tests also run in CI against **Qdrant Cloud** (`JOBS_DEV` is dropped and re-seeded each run — see [ADR-0014](../docs/adr/0014-embedding-model-migration.md) and `.github/workflows/ci.yml`).

**Docker:**

```bash
docker compose --profile test run --rm test
```

`seed_dev_qdrant_db` reset and batching behavior is covered by unit tests in `tests/db/test_seed_dev.py` (no Qdrant or network). That is separate from the `@pytest.mark.retrieval` golden-set tests below, which exercise semantic search quality only.

## Retrieval golden-set tests

Evaluate semantic search quality in isolation via `query_jobs_in_qdrant`, using a dedicated dev Qdrant collection (`JOBS_DEV` by default). These tests never touch the production collection (`JOBS_ON_THE_HUB`).

### Prerequisites

1. `.env` pointing at **Qdrant Cloud** with `QDRANT_URL`, `QDRANT_API_KEY`, and `EMBEDDING_MODEL=intfloat/multilingual-e5-small` (required — E5 has no local FastEmbed path; see [ADR-0014](../docs/adr/0014-embedding-model-migration.md)).
2. Distinct values for `QDRANT_COLLECTION_NAME` and `QDRANT_DEV_COLLECTION_NAME`.

### Run retrieval tests

**Local (host — recommended):**

```bash
uv run pytest -v -m retrieval
```

If Qdrant Cloud is not reachable or `.env` is misconfigured, retrieval tests are skipped automatically.

The test session seeds `tests/fixtures/golden_jobs.json` into the dev collection, runs each query in `tests/fixtures/golden_queries.json`, and asserts every expected `job_id` appears in the configured top-k.

> **Note:** `docker compose --profile test run --rm test-retrieval` still targets a local `qdrant` service and does **not** work with the current embedding model. Use host-side pytest with Cloud credentials instead.

### Seed the dev collection from live Hub data

For manual exploration or regenerating the golden set against real listings:

```bash
uv run python main.py --seed-dev
```

This drops and reloads `QDRANT_DEV_COLLECTION_NAME` with the first two pages of Denmark listings via the normal ingestion path. Requires Qdrant Cloud `.env` (same as retrieval tests). Avoid running while CI is re-seeding the same `JOBS_DEV` collection.

### Update the golden set

1. Edit `tests/fixtures/golden_jobs.json` if you change the fixed evaluation corpus (keep `job_id` values stable).
2. Edit `tests/fixtures/golden_queries.json`:
   - `query` — natural-language search text
   - `expected_job_ids` — Hub job IDs that must appear in top-k
   - `top_k` — how many results to inspect (default `8`)
   - `fixture_chat_source_min_score` — score floor for the dev corpus (production default is `0.85` in `db/settings.py`)
3. Optional `role_confusion_cases` — adversarial role/topic pairs (ALE-151):
   - `query` — natural-language search text
   - `expected_job_ids` — the correct role match that must rank highest and survive the floor
   - `confuser_job_ids` — semantically similar but wrong-role jobs that must not outrank the expected match or pass `min_score` (checked only if returned in top-k; absence from top-k is fine). If an expected job itself is missing from top-k, the separate `missing` assertion fails first — confuser ranking/floor checks are not reached that run.
   - `min_score` — production floor to assert against (default `0.85`)
   - Covered by `test_role_confusion_cases` (currently `xfail` until ALE-143 is verified)
4. Optional `tech_stack_adversarial_cases` — keyword/tech-stack precision pairs (ALE-145 / ADR-0010 Decision 5):
   - Same `query` / `expected_job_ids` / `confuser_job_ids` fields as role-confusion cases (reuse `confuser_job_ids` for the "known wrong winner"; no separate schema field)
   - Assertions are **rank-order only** (expected must outrank each confuser in top-k) — no `min_score` floor check; tech-stack failures are ranking precision, not noise above the `/chat` floor
   - Covered by `test_tech_stack_adversarial_cases` (currently `xfail` until ALE-143 ships)
5. Run `uv run pytest -v -m retrieval` and adjust queries or expectations until all non-xfail cases pass.

If you reseed from live data with `--seed-dev`, pick real `job_id` values from that collection when updating `expected_job_ids`.

### Promoting a production observation into a golden-set case

Lightweight loop (mirrors ALE-92 → findings → ADR-0010, and ALE-151):

1. **Capture** — note the query, observed ranking (job titles / IDs / scores), and why it is wrong. Prefer a short `docs/findings/NNNN-….md` entry over chat-only notes.
2. **Classify** — role/topic confusion → `role_confusion_cases`; keyword/tech-stack precision (expected vs known-wrong competitor) → `tech_stack_adversarial_cases`; otherwise extend `queries` if it is a simple hit/miss regression.
3. **Fixture** — add anonymized jobs to `golden_jobs.json` that reproduce the failure mode under the current embedder (keep `job_id`s stable). Point `expected_job_ids` / `confuser_job_ids` at those fixtures.
4. **Guard** — add or extend the matching `@pytest.mark.retrieval` test. If the fix is not landed yet, mark `xfail(strict=True)` with a ticket reference (same pattern as ALE-151 / ALE-145 awaiting ALE-143).
5. **Verify** — after the fix ships, re-run without `xfail` and record pass/fail in the findings doc.

## Generation eval tests

Evaluate `/chat` orchestration (retrieval → context assembly → `Generator` invocation) using the same dev Qdrant collection as the retrieval golden-set. These tests use a scripted `Generator` — no live Gemini API calls.

### Prerequisites

Same as retrieval tests: Qdrant Cloud `.env` with distinct production/dev collection names.

### Run generation eval tests

**Local (host):**

```bash
uv run pytest -v -m generation
```

Or combined with retrieval:

```bash
uv run pytest -v -m "retrieval or generation"
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

## Manual embedding-model comparison (scripts)

For eval work not covered by pytest:

- **Fixture comparison** — side-by-side scores for two models against `golden_jobs.json` / `golden_queries.json`
- **Production-scale E5 eval** — read-only scroll of `JOBS_ON_THE_HUB`, re-embed under E5, manual top-5 review + score distributions for `CHAT_SOURCE_MIN_SCORE` calibration
- **Token-length check** — read-only scroll of production `document_text`, E5 tokenizer stats vs the 512-token window

See **[`scripts/README.md`](../scripts/README.md)** for prerequisites, commands, and how to read the output.
