# ADR-0010: Sparse/BM25 Hybrid Search

* **Status:** Proposed
* **Date:** 2026-07-11
* **Related:** ADR-0002 (retrieval filtering strategy — this ADR's own revisit trigger), ALE-92 (spike), docs/findings/0001-keyword-tech-stack-retrieval-gap-findings.md (evidence), ALE-116 (lands the findings doc)

## Context

ADR-0002 explicitly deferred keyword/tech-stack precision as a distinct problem from country/remote filtering, and named its own revisit trigger: evaluate a sparse/BM25 vector addition as its own ADR if evidence emerges that this is a real, separate retrieval-quality issue — not folded back into ADR-0002, since it requires a full reindex and is a materially bigger decision.

ALE-92 quantified this. Running 8 tagged tech-stack queries against the production Qdrant collection and manually verifying relevance via `document_text` inspection (not just score proximity), 3 of 8 (37.5%) showed a confirmed keyword-precision failure — the correct or most-relevant job scoring at or below a semantically-similar but tech-stack-irrelevant competitor, margin under 0.05. Full evidence is in `docs/findings/0001-keyword-tech-stack-retrieval-gap-findings.md`. This clears the ≥25% go/no-go threshold set when the spike was scoped.

One case in that evidence (Kubernetes/Six Robotics vs. Framna) carries a confound: the losing job's posting is largely non-English, and the winner's title is a near-verbatim lexical match to the query. This looks like title-lexical-overlap dominating the score rather than pure keyword-density blindness, and a sparse/BM25 addition may not cleanly fix it — addressed explicitly below rather than implied away.

## Decision 1: Add a sparse vector — GO

**Decision:** Proceed with adding a sparse vector alongside the existing dense vector, per ADR-0002's revisit trigger.

**Rationale:**

- The evidence clears the pre-registered 25% threshold (37.5% observed), and the three clean cases (Python/FastAPI, Go, Terraform) share a consistent, unconfounded mechanism: a job that names a technology once in passing outranks a job that names it as an explicit, framework-qualified requirement. That's a real gap dense embeddings alone won't close, since embedding similarity is fundamentally a topical/semantic measure, not a term-frequency one.
- This does not replace dense retrieval or ADR-0002's structured filtering — it's additive. Country/remote filtering (ADR-0002 Decision 1) and the similarity floor (ADR-0002 Decision 4) continue to run unchanged; this only changes how the *ranking* within a filtered candidate set is computed.

## Decision 2: Qdrant's built-in BM25 sparse embedding (FastEmbed), not SPLADE or a custom `rank_bm25` script

**Decision:** Use FastEmbed's BM25 sparse model (`Qdrant/bm25`) via `qdrant-client[fastembed]` — already a project dependency — rather than a neural sparse model (SPLADE) or a hand-rolled `rank_bm25` scoring pass.

**Rationale:**

- Same reasoning ADR-0001 used for dense embeddings and ADR-0002 used for filter extraction: don't add a component whose cost or complexity the current evidence doesn't call for. SPLADE requires downloading and running a second neural model in-process — real compute/memory cost on the same CPU-only dev hardware (ADR-0007's constraint) for a precision gain the evidence doesn't yet show BM25 can't already close (all three confirmed cases are plain term-frequency/specificity gaps, not the kind of learned-term-expansion problem SPLADE targets).
- `qdrant-client[fastembed]` already ships FastEmbed's sparse BM25 support — no new dependency, no new model download infrastructure beyond what ingestion already does for the dense model.
- A hand-rolled `rank_bm25` script would mean maintaining a second scoring path outside Qdrant entirely (fetch candidates, score in Python, re-sort) — more code to own, and loses Qdrant's native fused-query execution (Decision 3).

## Decision 3: Reciprocal Rank Fusion via Qdrant's native `Query` API — not a Python-side merge

**Decision:** Use Qdrant's `query_points` with `prefetch` (dense) and a `FusionQuery(fusion=Fusion.RRF)` to combine dense and sparse results server-side, rather than running two separate queries and merging/re-ranking in Python.

**Rationale:**

- Mirrors ADR-0002 Decision 1's own precedent: filtering and vector search happen together during Qdrant's own traversal, not as sequential application-side passes. Fusion is a solved, native Qdrant capability; reimplementing RRF in Python would be redundant code solving an already-solved problem.
- Country/remote payload filtering (ADR-0002) applies identically inside this fused query — no interaction effect to design around; the `query_filter` narrows candidates before or during traversal for both the dense and sparse prefetch legs.

## Decision 4: Add the sparse vector in-place via `qdrant-client` ≥1.18.0 — not a new collection

**Decision:** Bump `qdrant-client[fastembed]` from the currently pinned `1.16.2` to `>=1.18.0`, then add the sparse vector to the *existing* collection in place via the client's named-vector API (`create_vector_name`, backed by `PUT /collections/{collection_name}/vectors/{vector_name}`) — not a new collection with a migration/cutover.

**Rationale:**

- Qdrant added exactly this capability — adding/removing named vectors on an existing collection without recreation — as of server v1.18.0, with matching client support landing in `qdrant-client` 1.18.0 (released May 11, 2026). The "materially bigger decision" ADR-0002 flagged when it named this revisit trigger assumed the older recreate-only behavior; that constraint no longer holds.
- Dense vectors, payload, and point IDs are untouched entirely — only the sparse vector field is added to the collection schema, then computed and upserted for existing points. No new collection name, no `QDRANT_COLLECTION_NAME_V2`, no dual-collection rollback window.
- **What still needs doing:** every existing point still needs its BM25 sparse vector computed once and upserted (points don't retroactively gain a vector just because the collection schema changed) — via a `--backfill`-style script mirroring ALE-81's pattern, not a from-scratch reindex.
- **Named risk, explicitly:** bumping `qdrant-client` two minor versions (1.16.2 → 1.18.0) is a real dependency change, not a no-op. The 1.17.0 release changed the gRPC vector response format, and recent releases removed several already-deprecated methods (`search`, `recommend`, `discovery`, `upload_records`, and others). This needs explicit re-verification against the actual codebase before merging the bump, plus a full run of the unit + retrieval golden-set suite (ALE-68) against the upgraded client. **Left as an open item for the implementation ticket, not resolved here.**
- **Rollout plan:** bump the dependency → add the sparse vector field to the collection (schema-only, instant) → run the backfill script for existing points → deploy the fusion-query code last. Because no second collection exists, the collection stays fully queryable on dense-only retrieval throughout — if the backfill fails partway, nothing regresses, since existing code paths don't reference the new vector until the fusion query itself ships. This is incremental, not an all-or-nothing cutover.

## Decision 5: Extend the golden set with the three confirmed adversarial pairs before shipping

**Decision:** Before merging the hybrid-search implementation, codify the three confirmed-problematic cases from `docs/findings/0001-...md` (Python/FastAPI, Go, Terraform) as adversarial pairs in `tests/fixtures/golden_queries.json` — query, expected winner, and the known wrong winner — so the fix's impact is measured against a concrete before/after baseline rather than judged anecdotally again.

**Rationale:**

- ALE-92's own "Related finding" flagged this directly: there is currently no repeatable way to check whether a specific job outranks a confusable competitor, only ad hoc manual `document_text` inspection. Shipping a ranking change without a regression guard for the exact cases that motivated it repeats the same evidentiary gap ADR-0001 Decision 5 was designed to close for generation quality.
- Deliberately scoped as a small, targeted addition (3 pairs) — not the full adversarial eval framework ALE-92 recommends as a separate future effort. That stays out of scope here.

## Decision 6: The Kubernetes/multilingual confound is an explicit revisit trigger, not solved by this ADR

**Decision:** This ADR does not attempt to fix the title-lexical-overlap / non-English-body confound found in the Kubernetes/Six Robotics case. Named here so it isn't silently dropped.

**Rationale:**

- A sparse BM25 term-match can favor an exact title-phrase match just as easily as the dense embedding did — hybrid search doesn't structurally solve "the wrong job's title happens to repeat the query verbatim." Claiming it does would overstate what this change delivers.
- The fix for that specific sub-case (e.g., normalizing/flagging non-English postings, or weighting title vs. body differently) is a distinct problem deserving its own evidence-gathering, not a bundled fix here.

## Consequences

**Positive:**

- Directly addresses a confirmed, evidence-backed retrieval gap (37.5% failure rate on tagged queries) using infrastructure already in the dependency tree (FastEmbed), no new model to host.
- Reuses Qdrant's native fused-query execution rather than adding a parallel Python-side ranking layer — keeps retrieval logic in one place, consistent with ADR-0002 Decision 1's precedent.
- Leaves ADR-0002's country/remote filtering and similarity floor untouched — additive, not a rewrite.
- No new collection or migration/cutover needed — the in-place named-vector API (`qdrant-client` ≥1.18.0) means this is an additive schema change, not a full reindex, substantially lowering the risk ADR-0002 anticipated when it flagged this as a "materially bigger decision."
- Adds a permanent regression guard (Decision 5) for the exact failure cases that motivated this change.

**Negative / accepted risks:**

- Requires bumping `qdrant-client` two minor versions (1.16.2 → 1.18.0) — needs explicit verification that no code paths use methods removed in that span, and that behavior is unchanged (e.g., the 1.17.0 gRPC vector response format change). Left open for the implementation ticket.
- Does not address the multilingual/title-overlap confound (Decision 6) — a known, named gap, not silently dropped.
- BM25 sparse matching can itself be gamed by keyword-stuffed postings in a way dense embeddings partially resist. Not observed in current data, but worth naming as a new failure mode this change could introduce.

## Revisit triggers

- If BM25 keyword-stuffing (postings padding a technology list to game sparse-match scores) is observed in real transcripts, revisit fusion weighting or add a stuffing-detection heuristic.
- If the Kubernetes/multilingual confound recurs across multiple queries (not just the one observed case), scope a dedicated ADR for non-English/title-overlap handling rather than folding it in here.
- If the 3-pair adversarial golden set proves insufficient, expand it — this is explicitly the lighter-weight version of the fuller adversarial eval ALE-92 recommends as future work.
