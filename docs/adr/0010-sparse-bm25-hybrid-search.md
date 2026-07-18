# ADR-0010: Sparse/BM25 Hybrid Search

* **Status:** Accepted
* **Date:** 2026-07-11 (Decision 7 landed 2026-07-16 with ALE-143; Decision 7 continuation folded 2026-07-18 via ALE-157)
* **Related:** ADR-0002 (retrieval filtering strategy — this ADR's own revisit trigger), ADR-0014 (E5 + Cloud Inference — dense path this ADR builds on), ALE-92 (spike), ALE-143 (implementation), ALE-157 (folds Decision 7 continuation into this file), ALE-158 (raw-vector reuse for dense query embedding), docs/findings/0001-keyword-tech-stack-retrieval-gap-findings.md (evidence), ALE-116 (lands the findings doc)

## Context

ADR-0002 explicitly deferred keyword/tech-stack precision as a distinct problem from country/remote filtering, and named its own revisit trigger: evaluate a sparse/BM25 vector addition as its own ADR if evidence emerges that this is a real, separate retrieval-quality issue — not folded back into ADR-0002, since it requires a full reindex and is a materially bigger decision.

ALE-92 quantified this. Running 8 tagged tech-stack queries against the production Qdrant collection and manually verifying relevance via `document_text` inspection (not just score proximity), 3 of 8 (37.5%) showed a confirmed keyword-precision failure — the correct or most-relevant job scoring at or below a semantically-similar but tech-stack-irrelevant competitor, margin under 0.05. Full evidence is in `docs/findings/0001-keyword-tech-stack-retrieval-gap-findings.md`. This clears the ≥25% go/no-go threshold set when the spike was scoped.

One case in that evidence (Kubernetes/Six Robotics vs. Framna) carries a confound: the losing job's posting is largely non-English, and the winner's title is a near-verbatim lexical match to the query. This looks like title-lexical-overlap dominating the score rather than pure keyword-density blindness, and a sparse/BM25 addition may not cleanly fix it — addressed explicitly below rather than implied away.

## Decision 1: Add a sparse vector — GO

**Decision:** Proceed with adding a sparse vector alongside the existing dense vector, per ADR-0002's revisit trigger.

**Rationale:**

- The evidence clears the pre-registered 25% threshold (37.5% observed), and the three clean cases (Python/FastAPI, Go, Terraform) share a consistent, unconfounded mechanism: a job that names a technology once in passing outranks a job that names it as an explicit, framework-qualified requirement. That's a real gap dense embeddings alone won't close, since embedding similarity is fundamentally a topical/semantic measure, not a term-frequency one.
- This does not replace dense retrieval or ADR-0002's structured filtering — it's additive. Country/remote filtering (ADR-0002 Decision 1) continues to run unchanged; ranking within the filtered candidate set uses fused dense+sparse RRF. The similarity floor (ADR-0002 Decision 4) also continues, but its score semantics are resolved explicitly in Decision 7 (not assumed identical to pre-fusion `hit.score`).

## Decision 2: Qdrant's BM25 sparse embedding via Cloud Inference — not SPLADE, not a custom `rank_bm25` script, not in-process FastEmbed

**Decision:** Use Qdrant's BM25 sparse model (`qdrant/bm25`) via `models.Document` with Qdrant Cloud Inference (`cloud_inference=True`) — the same server-side embedding path ADR-0014 established for dense E5 — rather than a neural sparse model (SPLADE), a hand-rolled `rank_bm25` scoring pass, or loading FastEmbed's BM25 ONNX model in the Render process.

**Rationale:**

- Same reasoning ADR-0001 used for dense embeddings and ADR-0002 used for filter extraction: don't add a component whose cost or complexity the current evidence doesn't call for. SPLADE requires downloading and running a second neural model in-process — real compute/memory cost for a precision gain the evidence doesn't yet show BM25 can't already close.
- **ADR-0014 refinement (ALE-143):** The original draft assumed in-process FastEmbed BM25 because dense embedding also ran locally at the time. Dense now runs exclusively via Cloud Inference (E5 is not in local FastEmbed's registry). Loading any FastEmbed model on Render's free tier reintroduces the exact memory-crash failure ADR-0014 fixed. Qdrant's [Cloud Inference hybrid-search tutorial](https://qdrant.tech/documentation/tutorials-basics/cloud-inference-hybrid-search/) confirms `Document(text=..., model="qdrant/bm25")` is supported server-side alongside dense models — so BM25 stays out of the Render process entirely. Scope item 8 of ALE-143 is resolved by this path, not by hoping BM25 is "light enough."
- A hand-rolled `rank_bm25` script would mean maintaining a second scoring path outside Qdrant entirely — more code to own, and loses Qdrant's native fused-query execution (Decision 3).

## Decision 3: Reciprocal Rank Fusion via Qdrant's native `Query` API — not a Python-side merge for ranking

**Decision:** Use Qdrant's `query_points` / `query_batch_points` with `prefetch` (dense + sparse) and a `FusionQuery(fusion=Fusion.RRF)` to combine dense and sparse results server-side for **ranking**, rather than running two separate queries and merging/re-ranking in Python.

**Rationale:**

- Mirrors ADR-0002 Decision 1's own precedent: filtering and vector search happen together during Qdrant's own traversal, not as sequential application-side passes. Fusion is a solved, native Qdrant capability; reimplementing RRF in Python would be redundant code solving an already-solved problem.
- Country/remote payload filtering (ADR-0002) applies identically inside this fused query — no interaction effect to design around; the query filter narrows candidates for both the dense and sparse prefetch legs.
- **Narrow exception for scoring only:** Decision 7 introduces a companion dense query in the same `query_batch_points` request. That is a deliberate, scoring-only exception to "no second query" — ranking itself remains single-query RRF. See Decision 7.

## Decision 4: Add the sparse vector in-place via `qdrant-client` ≥1.18.0 — not a new collection

**Decision:** Add the sparse vector to the *existing* collection in place via the client's named-vector API (`create_vector_name`, backed by `PUT /collections/{collection_name}/vectors/{vector_name}`) — not a new collection with a migration/cutover. The `qdrant-client[fastembed]>=1.18.0` bump required for this API was completed under ADR-0014; ALE-143 confirms it and does not re-bump.

**Rationale:**

- Qdrant added exactly this capability — adding/removing named vectors on an existing collection without recreation — as of server v1.18.0, with matching client support landing in `qdrant-client` 1.18.0. The "materially bigger decision" ADR-0002 flagged when it named this revisit trigger assumed the older recreate-only behavior; that constraint no longer holds.
- Dense vectors, payload, and point IDs are untouched entirely — only the sparse vector field is added to the collection schema, then computed and upserted for existing points. No new collection name, no `QDRANT_COLLECTION_NAME_V2`, no dual-collection rollback window.
- **What still needs doing:** every existing point still needs its BM25 sparse vector computed once and upserted (points don't retroactively gain a vector just because the collection schema changed) — via `--backfill-sparse` mirroring ALE-81's pattern, not a from-scratch reindex.
- **Rollout plan:** add the sparse vector field to the collection (schema-only) → run the backfill script for existing points → deploy the fusion-query code last. Because no second collection exists, the collection stays fully queryable on dense-only retrieval throughout — if the backfill fails partway, nothing regresses, since existing code paths don't reference the new vector until the fusion query itself ships. This is incremental, not an all-or-nothing cutover.

## Decision 5: Extend the golden set with the three confirmed adversarial pairs before shipping

**Decision:** Before merging the hybrid-search implementation, codify the three confirmed-problematic cases from `docs/findings/0001-...md` (Python/FastAPI, Go, Terraform) as adversarial pairs in `tests/fixtures/golden_queries.json` — query, expected winner, and the known wrong winner — so the fix's impact is measured against a concrete before/after baseline rather than judged anecdotally again.

**Rationale:**

- ALE-92's own "Related finding" flagged this directly: there is currently no repeatable way to check whether a specific job outranks a confusable competitor, only ad hoc manual `document_text` inspection. Shipping a ranking change without a regression guard for the exact cases that motivated it repeats the same evidentiary gap ADR-0001 Decision 5 was designed to close for generation quality.
- Deliberately scoped as a small, targeted addition (3 pairs) — not the full adversarial eval framework ALE-92 recommends as a separate future effort. That stays out of scope here.
- **Status (ALE-145 / ALE-143):** The three pairs shipped in ALE-145 as `tech_stack_adversarial_cases` with `xfail(strict=True)`. ALE-143 removes the `xfail` once the fused query makes them pass.

## Decision 6: The Kubernetes/multilingual confound is an explicit revisit trigger, not solved by this ADR

**Decision:** This ADR does not attempt to fix the title-lexical-overlap / non-English-body confound found in the Kubernetes/Six Robotics case. Named here so it isn't silently dropped.

**Rationale:**

- A sparse BM25 term-match can favor an exact title-phrase match just as easily as the dense embedding did — hybrid search doesn't structurally solve "the wrong job's title happens to repeat the query verbatim." Claiming it does would overstate what this change delivers.
- The fix for that specific sub-case (e.g., normalizing/flagging non-English postings, or weighting title vs. body differently) is a distinct problem deserving its own evidence-gathering, not a bundled fix here.
- **Follow-up:** ALE-129 tracks language-detection / translation options for this confound.

## Decision 7: Filter `CHAT_SOURCE_MIN_SCORE` on dense cosine — not the fused RRF score

**Decision:** After RRF ranking, attach each hit's **pre-fusion dense cosine** to `hit.score` for `CHAT_SOURCE_MIN_SCORE` / `filter_chat_retrieval_points`. Keep `DEFAULT_CHAT_SOURCE_MIN_SCORE = 0.85` (ADR-0014 / ALE-138 calibration). Do **not** recalibrate the floor against the RRF rank-sum scale.

**How scores are obtained:** Qdrant's fused `query_points` response after `FusionQuery(fusion=Fusion.RRF)` exposes only the RRF rank-sum in `point.score` — not per-leg dense/sparse scores (confirmed from Qdrant hybrid-query docs; not a runtime unknown for ALE-143). Implementation therefore issues a **companion dense-only query** in the same `query_batch_points` request as the fused query. Ranking order comes from RRF; scores come from the companion map.

**Cloud Inference batch dedupe — confirmed false (2026-07-18):** Qdrant Support (Vivek, 2026-07-18) confirmed that neither the Python client nor the Qdrant server caches or deduplicates identical `Document` inference objects within a batch — each query that references a `Document` triggers its own E5 embed call, even when the same object reference appears twice. Near-identical latencies in earlier probe scripts were explained by free-tier network RTT dwarfing the ~10–20 ms second-embed compute cost, not by dedupe. The earlier "unconfirmed" wording (ALE-143 / PR #71) is corrected here from unconfirmed to **confirmed false**.

**Required mitigation — raw-vector reuse (ALE-158):** Because shared `Document` instances do not collapse to one embed, the dense query text must be embedded **once** via an explicit Cloud Inference call, then the resulting raw vector passed into both the fused prefetch leg and the companion dense-only query. Passing `Document(text=...)` to each leg is a confirmed double E5 call (double Cloud Inference cost, not just double latency) on every `/chat` request. This is required, not optional polish. Latency scaffolding for verifying the before/after lives in `scripts/verify_inference_dedupe.py`.

**Decision 3 exception (named explicitly):** The companion query reintroduces a second Qdrant query, narrowly for **floor-scoring** purposes only. Ranking itself remains single-query RRF per Decision 3. This is a deliberate, documented exception — not an unexplained contradiction.

**Missing dense score → fail the floor:** Hybrid search can (and should) surface BM25-only hits that never appear in the dense companion's top-k. Those hits have no dense cosine to attach. Treat them as failing `CHAT_SOURCE_MIN_SCORE` (implementation uses `MISSING_DENSE_SCORE = -1.0`). The companion dense query's `limit` is intentionally **not padded** to chase BM25-only hits — widening it would defeat this rule.

**Rationale:**

- Preserves the floor's existing, already-calibrated meaning (a cosine-similarity noise gate) rather than requiring a fresh calibration against an unfamiliar RRF scale (~0.01–0.03 for default `k=60`).
- Applying `0.85` to raw RRF scores would filter out every result and silently break `/chat` sources — the failure mode Decision 1's "floor continues unchanged" glossed over.

## Consequences

**Positive:**

- Directly addresses a confirmed, evidence-backed retrieval gap (37.5% failure rate on tagged queries) using Cloud Inference BM25 — no new model hosted in the Render process (ADR-0014-compatible).
- Reuses Qdrant's native fused-query execution for ranking — keeps ranking logic in one place, consistent with ADR-0002 Decision 1's precedent.
- Leaves ADR-0002's country/remote filtering and similarity-floor *semantics* intact — additive ranking change; floor still gates on dense cosine (Decision 7).
- No new collection or migration/cutover needed — the in-place named-vector API (`qdrant-client` ≥1.18.0) means this is an additive schema change, not a full reindex.
- Adds a permanent regression guard (Decision 5 / ALE-145) for the exact failure cases that motivated this change.

**Negative / accepted risks:**

- Companion dense query adds a second Qdrant query in the same `query_batch_points` batch (Decision 7 / Decision 3 exception). Batching avoids a serial round trip, but without raw-vector reuse each leg that passes `Document(text=...)` triggers a separate E5 Cloud Inference call — batch Document dedupe is **confirmed false** (Qdrant Support, 2026-07-18). Until ALE-158 lands, every `/chat` hybrid request pays a real double embed. **Magnitude:** the second free-tier small-model embed is likely single-digit to low-double-digit milliseconds of inference compute (and still drowned by ~500 ms free-tier RTT in the 2026-07-17 latency probe) — not a meaningful cost concern on the current Cloud Inference free tier, and not a Render memory concern (both dense and BM25 stay server-side). The accepted risk is the double call itself until raw-vector reuse ships; the mitigation is required, not optional.
- Does not address the multilingual/title-overlap confound (Decision 6) — a known, named gap, not silently dropped.
- BM25 sparse matching can itself be gamed by keyword-stuffed postings in a way dense embeddings partially resist. Not observed in current data, but worth naming as a new failure mode this change could introduce.
- Role/topic confusion (ALE-151) is a distinct failure mode; hybrid search is not assumed to fix it.

## Revisit triggers

- If BM25 keyword-stuffing (postings padding a technology list to game sparse-match scores) is observed in real transcripts, revisit fusion weighting or add a stuffing-detection heuristic.
- If the Kubernetes/multilingual confound recurs across multiple queries (not just the one observed case), scope a dedicated ADR for non-English/title-overlap handling rather than folding it in here (see ALE-129).
- If the 3-pair adversarial golden set proves insufficient, expand it — this is explicitly the lighter-weight version of the fuller adversarial eval ALE-92 recommends as future work.
- **Role/topic confusion (ALE-151):** The "frontend jobs in Copenhagen" case remains a distinct failure mode from keyword/tech-stack precision. **ALE-143 verification (2026-07-16):** `test_role_confusion_cases` still fails under fused RRF + dense-score floor (`cph002` ≈ 0.852 above 0.85). Documented in `docs/findings/0002-role-confusion-frontend-copenhagen-findings.md`. Follow-up directions there (role-aware payload filtering, query intent parsing, or post-retrieval role re-ranking) need a dedicated ADR/ticket — not silently dropped.
- **Cloud Inference Document dedupe (Decision 7 continuation / ALE-157):** Settled — no batch-level dedupe (Qdrant Support, 2026-07-18). The remaining action is implementing raw-vector reuse (ALE-158), not further vendor confirmation. If ALE-158's approach proves impractical in `qdrant-client`, revisit: ask Qdrant for an official embed-once API, or accept the double-call cost explicitly with monitoring.
