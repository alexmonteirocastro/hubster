# Standalone eval scripts

Developer-facing comparison tooling for embedding models, generation models, and
`CHAT_SOURCE_MIN_SCORE` sweeps. Logic lives in the importable [`evals/`](../evals/)
package (structured dataclass returns); scripts here are thin CLI wrappers so
the [`evals_system/`](../evals_system/) Streamlit UI can call the same functions
without re-implementing sweeps (see [`evals_system/GUIDE.md`](../evals_system/GUIDE.md)).

These complement (but do not replace) the automated `@pytest.mark.retrieval` /
`@pytest.mark.generation` tests.

Use them when you need to:

- Compare candidate embedding models side-by-side (scores, noise margins, missed hits)
- Compare generation providers/models on `golden_generation.json` (answers + grounding checks)
- Derive / re-check a candidate `CHAT_SOURCE_MIN_SCORE` against the golden set
- Sanity-check E5-style query/passage prefix handling before a model switch

Comparison runs are safe against a production Qdrant Cloud cluster: they create
disposable `JOBS_COMPARE_*` collections and delete them when done (unless a
`--keep-collection(s)` flag is passed).

## Importable API (`evals/`)

```python
from evals import (
    compare_embedding_models,
    compare_generators,
    build_generator,
    sweep_chat_source_min_score,
)

embedding = compare_embedding_models(["model-a", "model-b"])
generation = compare_generators({
    "gemini": build_generator("gemini"),
    "qwen": build_generator("ollama:qwen3:8b"),
})
sweep = sweep_chat_source_min_score([0.80, 0.85, 0.90])
```

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

The comparison client enables `cloud_inference=True` on `QdrantClient` so `models.Document(...)` embedding runs server-side. This is required for `intfloat/multilingual-e5-small`.

## 1. Prefix metadata check (no Qdrant calls)

Fast first-pass on whether local FastEmbed exposes query/passage prefix metadata for candidate models:

```bash
uv run python scripts/check_fastembed_prefix_support.py
```

Inspects `TextEmbedding.list_supported_models()` for prefix-related fields. **Caveat:** this only covers local FastEmbed. Cloud Inference may behave differently — treat the embedding comparison script (below) as authoritative for production.

## 2. Golden-set embedding model comparison

Seeds throwaway collections (one per model) with `tests/fixtures/golden_jobs.json`, runs every query in `tests/fixtures/golden_queries.json`, and prints a side-by-side score table plus per-model summary (missed hits, min expected score, max noise, separation margin).

Library: `evals.embeddings.compare_embedding_models`.

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

**What "good" looks like:** positive separation margin. The current production floor (`0.85` for `intfloat/multilingual-e5-small` in `db/settings.py`) is the reference point.

### Model availability

| Model | Qdrant Cloud Inference |
|---|---|
| `BAAI/bge-small-en-v1.5` | Yes |
| `sentence-transformers/all-MiniLM-L6-v2` | Yes |
| `intfloat/multilingual-e5-small` | Yes |

Local FastEmbed is not used for Hubster embedding under ADR-0014 — compare models against Qdrant Cloud.

## 3. Generation model comparison

Runs each case in `tests/fixtures/golden_generation.json` through one or more
`Generator` implementations (Gemini, Ollama, stub), after retrieving context from
a disposable `JOBS_COMPARE_GENERATION` collection.

Library: `evals.generation.compare_generators` / `build_generator`.

```bash
uv run python scripts/compare_generators.py --providers stub
uv run python scripts/compare_generators.py --providers gemini ollama:qwen3:8b
# Lower top-k for Ollama (CPU-bound); mirrors CONTRIBUTING.md local-dev guidance
uv run python scripts/compare_generators.py --providers ollama:qwen3:8b --top-k 3
```

Per answer the harness records:

- raw answer text
- retrieved `source_job_ids` vs `expected_source_job_ids`
- ungrounded markdown link URLs (`find_ungrounded_link_urls`)
- ungrounded link-label phrases (`find_ungrounded_job_detail_phrases`)
- per-call `error` when generation fails (rate-limit / unavailable / config) — other cases/providers continue

Context truncation matches `POST /chat`: Ollama gets `OLLAMA_MAX_CHARS_PER_JOB` (default 1200) per job; Gemini/stub do not truncate.

**`mock_answer_substring` is not checked.** That fixture field only applies to
`ScriptedGenerator` in `tests/db/test_generation.py`; it has no meaningful
relationship to live Gemini/Ollama output. Do not wire it into this comparison.

Labels: `gemini`, `gemini:<model>`, `ollama`, `ollama:<model>`, `stub`.
Constructors copy `LLMSettings` with overrides — they do **not** mutate the
cached `get_generator()` singleton.

Useful flags: `--top-k N`, `--min-score T`, `--keep-collection` (singular — this script seeds one collection).

**Keep-collection flag naming:** embedding comparison uses `--keep-collections` (plural; N models → N collections). Generation and min-score sweep use `--keep-collection` (singular; one disposable collection each).

## 4. `CHAT_SOURCE_MIN_SCORE` sweep

Seeds golden jobs into `JOBS_COMPARE_MIN_SCORE_SWEEP`, queries once, then
evaluates each candidate floor the same way `/chat` filters hits
(`score >= threshold`).

Library: `evals.hyperparameters.sweep_chat_source_min_score`.

```bash
uv run python scripts/sweep_chat_source_min_score.py
uv run python scripts/sweep_chat_source_min_score.py --thresholds 0.80 0.85 0.90
```

Uses **`queries` and `role_confusion_cases`** from `golden_queries.json` only.
Does **not** include `tech_stack_adversarial_cases` (ALE-145) — those are
rank-order-only and do not have a score-floor semantic.

Output columns: expected survivors / misses, confuser survivors (from role-confusion
cases). Suggests the maximum threshold where every expected hit still survives.

## Relationship to pytest retrieval tests

| | `pytest -m retrieval` | These scripts / `evals/` |
|---|---|---|
| Corpus | `golden_jobs.json` | `golden_jobs.json` |
| Queries | `golden_queries.json` | `golden_queries.json` |
| Assertion | Pass/fail (expected job in top-k) | Per-query scores + noise margins / floor grid |
| Model | Single (`EMBEDDING_MODEL` from `.env`) | Multiple models or providers compared |
| Collection | `QDRANT_DEV_COLLECTION_NAME` | Disposable `JOBS_COMPARE_*` |

Update `tests/fixtures/golden_jobs.json` and `tests/fixtures/golden_queries.json` in one place — both pytest and these tools read the same files.

## Spike history

Embedding comparison originated in ALE-138 (`feat/ALE-138-compare-embedding-models`).
Generalized importable harness: ALE-147.

## 5. E5 evaluation against the real production corpus

For score distributions and manual relevance review at production scale (full `JOBS_ON_THE_HUB` collection — 1,015 points at time of ALE-138), without fixture ground truth:

```bash
# Fast smoke test (first 100 production jobs)
uv run python scripts/evaluate_e5_against_production.py --limit 100

# Full run (all production points)
uv run python scripts/evaluate_e5_against_production.py
```

**What it does:**

1. **Read-only scroll** of `QDRANT_COLLECTION_NAME` (production) — pulls `document_text` + metadata. Never writes to production.
2. **Re-embeds** the same texts under `intfloat/multilingual-e5-small` into a throwaway collection (`JOBS_COMPARE_E5_PROD` — fixed name, not produced by `evals.collections.collection_name_for_model`).
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
