# ADR-0014: Embedding Model Migration — `multilingual-e5-small` via Qdrant Cloud Inference

* **Status:** Proposed
* **Date:** 2026-07-14
* **Related:** ALE-132 (spike — Cloud Inference feasibility, memory-crash root cause), ALE-138 (spike — model comparison, fixture and production-scale validation), ADR-0013 (deployment strategy — this ADR closes the memory-footprint gap it left open), ADR-0002 Decision 4 (`CHAT_SOURCE_MIN_SCORE` — recalibrated here), ADR-0010 (planned sparse/BM25 hybrid search, not yet accepted — explicitly not resolved by this ADR)

## Context

ALE-126 (Render deployment) crashed with an "exceeded its memory limit" error on the first real `/chat`/`/jobs/search` request. Root cause, confirmed via Render logs: `get_qdrant_client()` loads `BAAI/bge-small-en-v1.5` via FastEmbed/ONNX **inside the Render process itself**, and the model download + ONNX session exceeds the 512MB free-tier container's memory. ADR-0013 priced in Render's compute/cold-start limits but not FastEmbed's in-process footprint — a real planning gap, not a regression.

ALE-132 (spike) confirmed `bge-small-en-v1.5` is not available via Qdrant Cloud Inference (server-side embedding) on any tier, checked across all three model categories (dense/sparse/multi-vector) directly on the cluster's Inference tab. Free dense alternatives are `sentence-transformers/all-MiniLM-L6-v2` and `intfloat/multilingual-e5-small`, both 384-dim (schema-compatible, no reindex-shape change).

ALE-138 (spike) then evidence-tested both candidates: first against a 7-job fixture set, then against the full production corpus (1,015 real `JOBS_ON_THE_HUB` points, re-embedded read-only into a throwaway collection — production untouched). Findings:

- **MiniLM is not viable.** Expected-hit scores collapse to 0.40–0.65 on the fixture set — far below any reasonable cutoff, and incompatible with Hubster's hard-cutoff `CHAT_SOURCE_MIN_SCORE` filtering strategy without a fundamental rework.
- **E5-small is viable and stable at scale.** Full production corpus: top-1 scores 0.838–0.879 (mean 0.866), rank-5 scores 0.832–0.874 (mean 0.852) — a tight, consistent band, changing only ~0.01–0.02 from a 100-job smoke test, which validates the smoke test rather than overturning it.
- **E5-small is not available in local FastEmbed's registry** (`TextEmbedding.list_supported_models()`), only via Qdrant Cloud Inference. This has a direct implementation consequence: ingestion, not just query-time, must also use Cloud Inference for this model — there is no local fallback.
- **Manual relevance review** (10 queries, real corpus, no automated ground truth — same methodology ALE-92 used when no golden set existed) found ~5/10 good-or-excellent, ~2/10 mixed, ~3/10 clear misses at top-1. Failure modes are role confusion (frontend↔backend) and country/geo imprecision (Stockholm→Spain, Germany→Netherlands) — **the same class of gap ALE-92 already documented for `bge-small-en-v1.5`** (~37.5% keyword-precision failure rate), not a new problem introduced by this migration.

This ADR's scope is narrow and deliberate: **unblock deployment without regressing retrieval quality below its current (already-imperfect) baseline.** Fixing the retrieval-precision gap itself is out of scope — that work is already tracked under ADR-0010 (sparse/BM25 hybrid search) and ADR-0002's revisit triggers, and remains prioritized separately from MVP deployment.

## Decision 1: Adopt `intfloat/multilingual-e5-small` via Qdrant Cloud Inference — not `all-MiniLM-L6-v2`, not staying on `bge-small-en-v1.5` + Render Standard

**Decision:** Switch Hubster's embedding model from `BAAI/bge-small-en-v1.5` to `intfloat/multilingual-e5-small`, served via Qdrant Cloud Inference rather than in-process FastEmbed.

**Rationale:**

- Directly resolves the Render memory crash: embedding compute moves out of the 512MB container entirely, onto Qdrant's own cluster network.
- `all-MiniLM-L6-v2` is ruled out on evidence, not preference — its score distribution is fundamentally incompatible with a hard-cutoff filtering strategy at any reasonable threshold (see ALE-138 findings above).
- Staying on Render Standard (paid tier) with `bge-small-en-v1.5` unchanged remains a valid alternative in principle — it trades dollar cost for zero engineering cost — but was not chosen because E5-small's retrieval quality is empirically comparable to (not worse than) the current model, meaning the switch achieves the $0/month goal (ADR-0013) at no meaningful quality cost. See Alternatives, below, for the fuller tradeoff framing.
- E5-small's 512-token context window (vs. MiniLM's 256) better fits `document_text`'s length (title + company + company description + job description), reducing truncation risk independent of the memory-crash fix.

## Decision 2: Enable `cloud_inference=True` for both query-time AND ingestion-time — not query-time only

**Decision:** Both the query path (`query_jobs_in_qdrant`) and the ingestion path (`load_jobs_into_qdrant`, `db/db_utils.py`) construct the `QdrantClient` with `cloud_inference=True` and use `models.Document(text=..., model="intfloat/multilingual-e5-small")`.

**Rationale:**

- ALE-132 originally scoped this as an open question ("does ingestion need the same change, or can it keep using local FastEmbed since ingestion doesn't run inside the memory-constrained Render process?"). ALE-138's findings resolve it: `intfloat/multilingual-e5-small` **does not appear in local FastEmbed's model registry at all** — there is no local fallback to keep. Ingestion must use Cloud Inference for this model regardless of where it runs.
- This is a simpler outcome than the original question anticipated (one embedding path, not two divergent ones for query vs. ingestion), and removes a class of "did ingestion and query-time actually use the same model consistently" bugs before they could exist.

## Decision 3: Recalibrate `CHAT_SOURCE_MIN_SCORE` to `0.85` (starting value) — do not carry over `0.70`

**Decision:** Set `DEFAULT_CHAT_SOURCE_MIN_SCORE = 0.85` in `db/settings.py`, replacing the `bge-small-en-v1.5`-calibrated `0.70`.

**Rationale:**

- `0.70` was explicitly calibrated against `bge-small-en-v1.5`'s score distribution (golden hits ≥~0.71, noise ~0.55–0.63). E5-small's distribution sits entirely above that (top-1 mean 0.866, rank-5 mean 0.852) — the old value would admit essentially all E5 results indiscriminately, defeating the floor's purpose.
- `0.85` is derived from the full 1,015-job production run: it sits between the observed rank-5 median (0.853) and mean (0.852), trimming the weakest tail without targeting the lowest legitimate top-1 score seen (0.838, on the thinnest-margin query).
- **Named explicitly, not hidden:** the signal/noise separation margin remains negative (−0.036) at this threshold, same structural pattern as the current `bge-small-en-v1.5` calibration (also negative, −0.049). A single hard cutoff will still be lossy in both directions — this is an accepted continuation of an existing limitation, not a new one introduced by the migration.
- Treat `0.85` as a starting point, not a final value: the implementation ticket must re-run `test_golden_queries_expected_jobs_survive_chat_source_min_score`-equivalent regression coverage under the new model before merging, and adjust up (toward ~0.86–0.87) or down (toward ~0.84) based on real observed leakage/drop rates once live.

## Decision 4: Bump `qdrant-client` to `>=1.18.x`

**Decision:** Update the pinned `qdrant-client` dependency from `1.16.2` to `>=1.18.0` (matching the Qdrant Cloud server version, currently 1.18.2).

**Rationale:**

- Closes the version-skew warning already visible in Render logs.
- `cloud_inference=True` already exists as a constructor parameter in the currently pinned version, so this bump isn't a hard prerequisite for the feature — but recent client releases have specifically touched cloud-inference behavior (e.g. `#1024`, "do not inspect models when cloud inference is enabled"), so running an unpatched client against a feature under active refinement is an avoidable risk.
- This mirrors a decision already made and accepted for the (separate, not-yet-implemented) ADR-0010 hybrid-search work, which also called for the same version bump — doing it here first means ADR-0010's implementation later doesn't have to repeat this step.

## Decision 5: Retrieval-precision gaps (role/country confusion) are explicitly out of scope for this ADR

**Decision:** This ADR does not attempt to fix the role-confusion or country/geo-imprecision failure modes surfaced during ALE-138's manual relevance review. Those are pre-existing gaps (documented by ALE-92 for the current production model) that this migration neither introduces nor resolves.

**Rationale:**

- Conflating "unblock deployment" with "fix retrieval quality" would turn a narrow, evidence-bounded infrastructure decision into an open-ended one, against this project's established practice of quantifying and scoping problems individually rather than bundling them.
- The correct venue for this work already exists: ADR-0010 (sparse/BM25 hybrid search, drafted from ALE-92/ALE-116's findings) and ADR-0002's own revisit triggers. This ADR changes nothing about their priority — it neither accelerates nor defers that work, it just doesn't duplicate it here.

## Alternatives considered and rejected (for now)

- **`sentence-transformers/all-MiniLM-L6-v2`** — rejected on hard evidence: score distribution incompatible with hard-cutoff filtering at any reasonable threshold (see Context).
- **Stay on `bge-small-en-v1.5`, move Render to a paid Standard tier** — a real, valid alternative that trades dollar cost for zero engineering/re-seed cost. Not chosen because E5-small's retrieval quality is empirically comparable (not worse) to `bge-small-en-v1.5` on the same real corpus, so the $0/month deployment goal (ADR-0013) is achievable without a quality tradeoff. Revisit if the E5 migration's actual implementation cost (re-seed, recalibration, testing) proves materially higher than currently estimated, or if production monitoring later shows E5 underperforming BGE in ways this spike's fixture/production sampling didn't catch.
- **Fixing the underlying retrieval-precision gap as part of this decision** — rejected per Decision 5: correctly scoped as separate, already-tracked work (ADR-0010), not something to fold into an infrastructure-unblocking ADR.

## Consequences

**Positive:**

- Resolves the Render memory-crash root cause directly and durably — embedding compute is removed from the constrained container entirely, not worked around.
- Keeps the $0/month deployment cost from ADR-0013 intact — no Render tier upgrade needed.
- Retrieval quality is empirically no worse than the current production model on the same real corpus — this migration is quality-neutral, evidenced rather than assumed.
- Ingestion and query-time now share one embedding path (Decision 2) — simpler than the two-path outcome ALE-132 originally anticipated, and removes a class of model-consistency bugs before they could occur.
- `CHAT_SOURCE_MIN_SCORE` recalibration is grounded in real production score distributions (1,015 jobs), not a 7-job fixture set or guesswork — a stronger basis than the original `0.70` calibration had available at the time.

**Negative / accepted risks:**

- The signal/noise separation margin remains negative at the recommended threshold — a hard `CHAT_SOURCE_MIN_SCORE` cutoff will still admit some noise or drop some legitimate thin-margin hits. Accepted as a continuation of an existing limitation (BGE's margin was also negative), not a regression.
- Full re-seed of `JOBS_ON_THE_HUB` (~1,015 points) is required — a real one-time cost, not free, though bounded and well-understood (mirrors the cost profile of prior full-seed operations in this project).
- Retrieval-precision failure modes (role/geo confusion) persist unchanged — explicitly accepted per Decision 5, tracked separately under ADR-0010/ADR-0002, not resolved here.
- `0.85` is a starting value, not a fully validated production number — real-traffic monitoring (once ALE-127/ALE-128's observability spikes land) is needed to confirm or adjust it.

## Revisit triggers

- If production monitoring shows `CHAT_SOURCE_MIN_SCORE=0.85` dropping too many legitimate hits or admitting too much noise, adjust within the ~0.84–0.87 range identified by ALE-138's findings before considering a more structural fix.
- If role/geo confusion complaints become frequent enough to affect product usability materially, treat that as evidence to prioritize ADR-0010 (hybrid search) sooner — this ADR doesn't change that priority on its own, but real usage evidence should.
- If Qdrant Cloud Inference's free-tier token allowance (per-model, monthly) is approached or exceeded under real traffic, revisit whether the Render Standard alternative (Decision Alternatives, above) becomes the better tradeoff after all.
- If `intfloat/multilingual-e5-small` is later added to local FastEmbed's registry, revisit whether ingestion should move off Cloud Inference back to local embedding (removing Cloud Inference token cost for the ingestion path specifically) — not urgent, but worth a cheap re-check if it happens.
