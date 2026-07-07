# ADR-0002: Retrieval Filtering Strategy

* **Status:** Accepted
* **Date:** 2026-07-06
* **Related:** ALE-76 (generation layer), ALE-77 (filter mechanism), ALE-78 (filter derivation), ADR-0001 (LLM provider strategy)

## Context

After merging ALE-76, real `/chat` transcripts were reviewed against production data. For country-scoped questions ("frontend roles in Sweden", "backend roles in Denmark"), the retrieved top-k results were frequently from the wrong country — in one transcript, 4 of 5 retrieved jobs were outside the requested country entirely. The generator behaved correctly per ADR-0001 Decision 3 (it declined to fabricate a match rather than answer from irrelevant context), but a correct answer was never retrievable in the first place. This is a retrieval-quality problem, not a generation problem, and ADR-0001 Decision 5's retrieval/generation eval separation is what made that attribution possible.

**Root cause.** `load_jobs_into_qdrant` (`db/database.py`) builds the embedded `document_text` from job title, company, company description, and job description only. `Country`, `location`, and `Remote` are stored as Qdrant payload metadata (see README "Stored data") but are never part of the vectorized text. A query naming a country has no reliable signal to match against unless that country happens to be mentioned incidentally in the job description — confirmed directly against a live payload (a Copenhagen, Denmark job whose `document_text` contains neither word).

This ADR covers three related but distinct decisions: how to combine structured constraints with semantic search, whether to index for it, and where filter values come from when the caller doesn't supply them explicitly.

## Decision 1: Combine dense semantic search with structured payload filtering — not a sparse/BM25 "hybrid search"

**Decision:** Extend `query_jobs_in_qdrant` to accept an optional `country` (and later `remote`) parameter, translated into a Qdrant `Filter`/`FieldCondition` passed as `query_filter` alongside the existing dense `query` in the same `query_points` call.

**Rationale:**

- Qdrant applies `query_filter` and the vector search together, during HNSW traversal — not as two sequential passes. This is a query-time parameter addition to an existing call, not a new retrieval stage.
- `Country`/`Remote` are exact categorical fields already stored on every point. Filtering on them is deterministic and free of the embedding model's uncertainty about whether "Denmark" is semantically "close enough."
- **This is explicitly not "hybrid search" in the stricter sense** (combining a dense vector with a sparse/BM25 keyword vector for text-precision matching). That technique targets a different failure mode — poor ranking of specific keywords/terms within the embedded text (e.g. "FastAPI" vs. "Django") — and would require a collection schema change (a new named sparse vector) and a full reindex of the existing collection. Given the confirmed root cause here is a missing categorical signal, not degraded keyword ranking, payload filtering is the correct, much cheaper fix. Conflating the two would have meant paying reindexing cost for a problem that isn't the one observed.

## Decision 2: Add payload indexes proactively, ahead of demonstrated need

**Decision:** `create_collection` will create payload indexes at collection-creation time, not only when filtering performance becomes a measured problem: `PayloadSchemaType.KEYWORD` on `Country` (string) and `PayloadSchemaType.BOOL` on `Remote` (boolean).

**Rationale:**

- Without an index, Qdrant can still filter, but does so less efficiently at larger collection sizes (no index to prune candidates before the more expensive check).
- The cost of adding this now is one function call inside `create_collection`; the cost of adding it later is a migration against a populated collection. Given this project is explicitly expected to possibly scale beyond prototype, paying the near-zero cost now is preferable to a forced migration later. This mirrors the general project stance (see ADR-0001's dedicated cost/vendor-risk analysis) of taking cheap precautions against known future costs rather than only reacting after the fact.

## Decision 3: Filter values come from an explicit API parameter first; deterministic text extraction second; no LLM-based extraction for now

**Decision:** `ChatRequest` (and `/jobs/search`) gain an explicit, optional `country: CountryCode` field (ALE-77). Separately, when the caller does not supply it, a dependency-free function `extract_filters_from_question(question: str)` derives `country`/`remote` from the question text using a deterministic alias/keyword lookup table — not an LLM call (ALE-78).

**Rationale for splitting these into two tickets/decisions rather than one:**

They differ on every axis that matters for how carefully each should be designed:

| | Explicit param (ALE-77) | Text extraction (ALE-78) |
|---|---|---|
| Determinism | Full | Depends on chosen approach |
| Added cost/latency | None | Zero (lookup) or a full model call (LLM) |
| Failure mode | N/A | Silent misfire, harder to attribute than a bad explicit value |

**Rationale for deterministic lookup over LLM-based extraction, specifically:**

- `CountryCode` is a small, closed enum (`DK`, `SE`, `NO`, `FI`, `IS`, `EU` — see README "Multi-country support"). A lookup table of country names, adjectives, and major cities is a complete, exhaustively-testable solution for the actual observed failure mode (both real transcripts named the country literally).
- An LLM-based extraction step would add latency and cost to every `/chat` request for a problem a static table already solves, and — more importantly — introduces a second place where the system can silently get something wrong, in a system whose entire generation-layer design (ADR-0001 Decision 3) exists specifically to make wrongness structurally impossible rather than merely unlikely. Adding a probabilistic component to the retrieval-scoping step undermines that property for a gain (robustness to unusual phrasing like "Scandinavia") that hasn't yet been shown to matter in practice.
- This is the same reasoning ADR-0001 itself used when comparing Gemini against a self-hosted model or a paid tier: don't pay for capability the current evidence doesn't call for; record the trigger that would justify revisiting instead of guessing at it now.

**Precedence rule:** an explicitly supplied `ChatRequest.country`/`remote` always overrides anything derived from the question text. Inference must never silently override stated caller intent.

**Implementation (ALE-78):** Option A shipped as `db/query_filters.py` — a dependency-free alias/keyword lookup (`extract_filters_from_question`) wired into `/chat` via `resolve_chat_filters`. Option B (LLM-based extraction) remains a revisit trigger only. The module lives under `db/` (not a top-level package) because it sits on the retrieval path between the API and `query_jobs_in_qdrant`, even though it has no Qdrant dependency. Extraction rules: remote handling uses false phrases (`remote=False`), neutral idioms (`remote=None`, no filter), then positive phrases/keywords with a negation-window check; when multiple distinct countries appear in one question, no country filter is applied rather than picking the earliest match.

## Consequences

**Positive:**

- Directly fixes the two confirmed failure transcripts using only data already stored on every point — no re-embedding, no new infrastructure.
- Payload indexing paid for up front removes a future migration cost.
- Keeps the retrieval-scoping step fully deterministic, preserving the anti-hallucination property ADR-0001 established for the generation layer — the same "don't add probabilistic surface without evidence it's needed" principle now applies one layer upstream, to retrieval scoping, not just generation.
- The retrieval/generation eval separation from ADR-0001 Decision 5 is what allowed this problem to be correctly attributed to retrieval in the first place — validating that split's design rather than adding overhead we don't use.

**Negative / accepted risks:**

- The alias/lookup table (ALE-78) is inherently incomplete — unusual phrasings ("Scandinavia", "the Nordics", misspellings) will not be caught and will silently fall back to unfiltered semantic search rather than erroring. This is an accepted, bounded gap: a missed filter degrades gracefully to today's (already-shipped) behavior, it doesn't produce a wrong answer.
- Remote negation detection uses a fixed phrase list and a small negation-window heuristic (not general NLP). Phrasings outside the closed sets may be missed entirely (falls back to no filter). Phrases listed in `REMOTE_NEUTRAL_PHRASES` degrade safely to no filter (`remote=None`); phrases not yet in that table may still be misread as `remote=False` by the negation window — the same kind of closed-set gap as alias completeness above, not a different failure mode.
- Filtering only on `Country`/`Remote` for now; other potentially useful filters (salary range, seniority) are not addressed and aren't motivated by current evidence.
- Keyword-precision issues within the embedded text (e.g. specific tech-stack terms) are *not* addressed by this ADR and may still exist — see Revisit triggers.

## Revisit triggers

- If the ALE-78 alias table's real-world miss rate (queries with an obvious location/remote intent that aren't caught) turns out to be high enough to matter, revisit LLM-based extraction (Option B, rejected above) — with its own cost/latency/determinism tradeoff re-evaluated against real data at that time, not assumed.
- If evidence emerges that keyword/tech-stack precision (as distinct from the country-matching problem this ADR addresses) is a real, separate retrieval-quality issue, evaluate a sparse/BM25 vector addition as its own ADR — do not retroactively fold it into this one, since it requires a full reindex and is a materially bigger decision.
- If additional structured filters beyond `Country`/`Remote` become clearly motivated by real usage (e.g. salary range, seniority), extend Decision 1's mechanism rather than building a parallel one.
- If `CountryCode.EUROPE` (`EU`) does not map to a real per-job `location.country` value in Hub's API (see ALE-82), revisit whether EU filtering should be supported, removed, or implemented differently — silent zero-result behavior is indistinguishable from "no jobs found."

## Alternatives considered and rejected (for now)

- **Sparse/BM25 hybrid vector search** — rejected as the primary fix because it targets keyword-ranking precision, not the confirmed root cause (missing categorical signal), and carries a full-reindex cost the confirmed problem doesn't justify paying. Not rejected permanently — see Revisit triggers.
- **LLM-based filter extraction from question text** — rejected as the starting approach for ALE-78 on cost, latency, and determinism grounds; a closed-set lookup table fully covers the evidence in hand. Not rejected permanently — see Revisit triggers.
- **Re-embedding `document_text` to include country/location inline** — would let plain semantic search pick up location signal without a separate filter mechanism, but requires reindexing the entire collection for a problem structured filtering solves with zero reindexing and full determinism. Rejected as strictly worse than Decision 1 for this specific field, since `Country`/`Remote` are categorical, not prose the embedding model needs to reason about.
