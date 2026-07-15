# Standalone eval scripts

Throwaway tooling for **manual embedding-model comparison** against the retrieval golden set. These scripts complement (but do not replace) the automated `@pytest.mark.retrieval` tests in `tests/db/test_retrieval.py`.

Use them when you need to:

- Compare candidate embedding models side-by-side (scores, noise margins, missed hits)
- Derive a candidate `CHAT_SOURCE_MIN_SCORE` for a new model
- Sanity-check E5-style query/passage prefix handling before a model switch

Both scripts are safe against a production Qdrant Cloud cluster: they create disposable `JOBS_COMPARE_*` collections and delete them when done (unless `--keep-collections` is passed).

## Prerequisites

```bash
uv sync   # or uv sync --group dev
```

Configure `.env` as usual — **Qdrant Cloud is required** for embedding-related scripts under the current model ([ADR-0014](../docs/adr/0014-embedding-model-migration.md)):

| Variable | Value |
|---|---|
| `QDRANT_URL` | Your Qdrant Cloud cluster URL |
| `QDRANT_API_KEY` | Required |

Run from the **repo root** (scripts add the repo to `sys.path` automatically).

The comparison script enables `cloud_inference=True` on `QdrantClient` so `models.Document(...)` embedding runs server-side. This is required for `intfloat/multilingual-e5-small`.

## 1. Prefix metadata check (no Qdrant calls)

Fast first-pass on whether local FastEmbed exposes query/passage prefix metadata for candidate models:

```bash
uv run python scripts/check_fastembed_prefix_support.py
```

Inspects `TextEmbedding.list_supported_models()` for prefix-related fields. **Caveat:** this only covers local FastEmbed. Cloud Inference may behave differently — treat the comparison script (below) as authoritative for production.

## 2. Golden-set model comparison

Seeds two throwaway collections (one per model) with `tests/fixtures/golden_jobs.json`, runs every query in `tests/fixtures/golden_queries.json`, and prints a side-by-side score table plus per-model summary (missed hits, min expected score, max noise, separation margin).

**Default models** (ALE-138 spike pair):

```bash
uv run python scripts/compare_embedding_models.py
```

Compares `all-MiniLM-L6-v2` vs `intfloat/multilingual-e5-small`. On Cloud Inference, `all-MiniLM-L6-v2` is auto-resolved to `sentence-transformers/all-MiniLM-L6-v2` (the API rejects the bare shorthand).

### Useful flags

```bash
# Keep collections for manual inspection in the Qdrant console
uv run python scripts/compare_embedding_models.py --keep-collections

# Compare a different pair — e.g. baseline vs candidate
uv run python scripts/compare_embedding_models.py \
  --models BAAI/bge-small-en-v1.5 intfloat/multilingual-e5-small
```

### Reading the output

For each golden query you will see:

- **Expected job score** per model (or `MISSING` if not in top-k — a real retrieval regression)
- **Top noise score** — highest-scoring non-expected hit in top-k

The **summary** section gives, per model:

| Metric | Meaning |
|---|---|
| Missed expected hits | Count of golden `expected_job_ids` not in top-k |
| Min expected-hit score | Candidate floor for `CHAT_SOURCE_MIN_SCORE` (same logic used to derive `0.70` for `BAAI/bge-small-en-v1.5`) |
| Max noise-hit score | Highest non-expected score — should sit below the floor |
| Separation margin | `min_expected − max_noise`; positive = clean separation |

**What "good" looks like:** positive separation margin. The current `BAAI/bge-small-en-v1.5` calibration (expected hits ≥ ~0.71, noise ~0.55–0.63) is the reference point in `db/settings.py`.

### Model availability

| Model | Qdrant Cloud Inference |
|---|---|
| `BAAI/bge-small-en-v1.5` | Yes |
| `sentence-transformers/all-MiniLM-L6-v2` | Yes |
| `intfloat/multilingual-e5-small` | Yes |

Local FastEmbed is not used for Hubster embedding under ADR-0014 — compare models against Qdrant Cloud.

## Relationship to pytest retrieval tests

| | `pytest -m retrieval` | These scripts |
|---|---|---|
| Corpus | `golden_jobs.json` | `golden_jobs.json` |
| Queries | `golden_queries.json` | `golden_queries.json` |
| Assertion | Pass/fail (expected job in top-k) | Per-query scores + noise margins |
| Model | Single (`EMBEDDING_MODEL` from `.env`) | Two models compared side-by-side |
| Collection | `QDRANT_DEV_COLLECTION_NAME` | Disposable `JOBS_COMPARE_*` |

Update `tests/fixtures/golden_jobs.json` and `tests/fixtures/golden_queries.json` in one place — both pytest and these scripts read the same files.

## Spike history

Added in ALE-138 (`feat/ALE-138-compare-embedding-models`). Findings posted on the Linear ticket.

## 3. E5 evaluation against the real production corpus

For score distributions and manual relevance review at production scale (full `JOBS_ON_THE_HUB` collection — 1,015 points at time of ALE-138), without fixture ground truth:

```bash
# Fast smoke test (first 100 production jobs)
uv run python scripts/evaluate_e5_against_production.py --limit 100

# Full run (all production points)
uv run python scripts/evaluate_e5_against_production.py
```

**What it does:**

1. **Read-only scroll** of `QDRANT_COLLECTION_NAME` (production) — pulls `document_text` + metadata. Never writes to production.
2. **Re-embeds** the same texts under `intfloat/multilingual-e5-small` into a throwaway collection (`JOBS_COMPARE_E5_PROD`).
3. **Runs 10 queries** — the 6 golden query texts from `golden_queries.json` plus 4 broader ones (remote, Norway, DevOps, Finland).
4. **Prints top-5 hits** per query with job title, company, country, and score (for manual eyeballing, ALE-92 style).
5. **Aggregate score stats** — min/max/mean/median of top-1 and rank-5 scores to inform `CHAT_SOURCE_MIN_SCORE`.

Requires **Qdrant Cloud** (`cloud_inference=True`). Use `--keep-collection` to inspect results in the Qdrant console afterward.

Run the smoke test first to confirm Cloud Inference connectivity; use the full run (no `--limit`) before locking a `CHAT_SOURCE_MIN_SCORE` for a model switch.

### ALE-138 findings (production full run, Jul 2026)

Evaluated against 1,015 real jobs under `intfloat/multilingual-e5-small`:

| Metric | Top-1 | Rank-5 |
|---|---:|---:|
| min | 0.838 | 0.832 |
| max | 0.879 | 0.874 |
| mean | 0.866 | 0.852 |
| median | 0.870 | 0.853 |

**Provisional `CHAT_SOURCE_MIN_SCORE` for E5-small: `0.85`** (tunable 0.84–0.87). The current BGE default (`0.70` in `db/settings.py`) does not transfer. Top-1 and rank-5 scores overlap (margin ≈ −0.036), so any hard cutoff is lossy — validate after re-seed with `pytest -m retrieval`.

**Spike recommendation:** standardize on `intfloat/multilingual-e5-small` via Cloud Inference over MiniLM. Full findings on Linear ticket ALE-138.
