# ADR-0003: Structured Job Title/Company Metadata

* **Status:** Proposed
* **Date:** 2026-07-07
* **Related:** ADR-0002 (retrieval filtering strategy — same underlying pattern), ALE-81 (implementation)

## Context

`load_jobs_into_qdrant` (`db/database.py`) builds the embedded `document_text` from job title, company, company description, and job description. Of these, `Country`, `location`, and `Remote` are *also* stored as standalone Qdrant payload metadata (see README "Stored data"), but `job_title` and `company` are not — they exist only inside the `document_text` blob.

This is not a missing-data problem at ingestion time: `JobOpportunity` (`the_hub_client/models.py`) already carries `job_title` and `company` as discrete, typed fields at the moment a job is scraped, before `load_jobs_into_qdrant` ever concatenates them into `document_text`. The structured value is available and then discarded in favor of only its text-embedded form. This is the same root pattern ADR-0002 identified for `Country`/`location`/`Remote` — a structured attribute collapsed into free text, recoverable downstream only by re-parsing — extended here to two fields that haven't yet caused an observed retrieval bug, but would reintroduce the exact anti-pattern ADR-0002 removed if the natural-seeming fix ("just parse `document_text`") were shipped instead.

**Note on JobSearchHit/ChatSource:** neither currently exposes `job_title`/`company` as fields — callers of `/jobs/search` and `/chat` today can only get them by reading the free-text `document_text` embedded in `ChatSource`, or not at all from `JobSearchHit`. This ADR's payload change is what makes exposing them as first-class response fields possible without a second migration later (see Decision 1's last bullet).

## Decision 1: Add `job_title` and `company` as payload metadata fields — do not parse them from `document_text` on every read

**Decision:** Extend the `jobs_metadata` dict built in `load_jobs_into_qdrant` to include `"job_title": job.job_title` and `"company": job.company`, sourced directly from the `JobOpportunity` object already in hand — the same object `document_text` itself is built from.

**Rationale:**

- **The data was never missing at ingestion time.** `job.job_title` and `job.company` exist as typed fields before `document_text` is built. Parsing them back out of the resulting string on every future read would mean repeatedly reconstructing, less reliably, something the code already had a moment earlier.
- **Parsing on every read is brittle in a way a payload field is not.** Extracting `job_title`/`company` from `document_text` per request would couple every consumer of that data to the exact wording of the f-string template in `load_jobs_into_qdrant`. Reordering, renaming, or restructuring that template — for reasons entirely unrelated to `job_title`/`company` — would silently break extraction everywhere it's used. A payload field has no such coupling.
- **Read-path performance.** A payload field is written once at ingestion and read in O(1) per query thereafter (a plain dict lookup, same cost as the existing `job_role`/`Country` lookups in `_payload_to_hit`/`_payload_to_source`). Parsing `document_text` — even a cheap split — is paid on *every* `/jobs/search` hit and every `/chat` source, for the lifetime of the system. At prototype scale this is unmeasurable; it is exactly the kind of recurring per-request cost that stops being unmeasurable once traffic grows, and there is no reason to accept it when the alternative is free.
- **Consistency with the existing schema.** `Country`, `location`, and `Remote` already follow this exact pattern (structured field → payload metadata, per ADR-0002). Treating `job_title`/`company` differently — leaving them embedded-text-only — is an accidental inconsistency in the schema, not a deliberate one.
- **Keeps the retrieval-filtering door open without a second migration.** `query_jobs_in_qdrant` already builds `Filter`/`FieldCondition` objects against payload fields (ADR-0002 Decision 1), evaluated by Qdrant during HNSW traversal in a single pass. If a future feature needs to filter or group by company, having `company` already in the payload means only the filter/index needs adding (see Decision 3) — not first resurrecting the field from text.

This mirrors ADR-0002's own rejection of "re-embedding `document_text` to include country/location inline" as strictly worse than a structured field for categorical data — the reasoning applies here even more directly, since `job_title`/`company` were never lost in the first place, only under-utilized.

## Decision 2: Backfilling existing points — deterministic extraction from `document_text` as the primary path, Hub API re-fetch only as a bounded fallback

**Decision:** Points already ingested before this change do not have a persisted `JobOpportunity` object to re-read `job_title`/`company` from — only `document_text` and the current payload survive ingestion. The backfill therefore:

1. **Primary path:** deterministically splits the known, fixed-format first two lines of `document_text` (`"Job Title: {x}\n"`, `"Company: {y}\n"`) to recover `job_title`/`company`, for every point that has non-empty `document_text`.
2. **Fallback path, only when `document_text` is missing or malformed:** re-fetch the job via `scrape_job_offer_by_id` (`the_hub_client`) to get a live `JobOpportunity`, accepting the Hub API cost only for this narrow edge case, and skip (with a logged warning) if the job has since been delisted (404).

**Rationale for why this is not a contradiction of Decision 1:**

This looks superficially like the "parse `document_text`" approach Decision 1 rejects, but differs on every property that made that approach wrong there:

| | Decision 1 rejects (ongoing reads) | Decision 2's backfill (one-time migration) |
|---|---|---|
| Frequency | Every future `/jobs/search`/`/chat` request, forever | Once, for the current backlog of already-ingested points |
| Format ownership | N/A — format could change for unrelated reasons and silently break every read | The two-line prefix is written by this same codebase's own `load_jobs_into_qdrant`, at a specific, known point in its history — a controlled, versioned format, not third-party free text |
| Failure mode | Silent, distributed, hard to notice (a subtly wrong title on some fraction of responses) | Contained to a single, testable migration function; a parse failure is caught and routed to the fallback path, not silently swallowed |

This is the same distinction a database migration script that backfills a new column from an old free-text field would rely on — acceptable as a bounded, one-time operation against data in a known, historical format; not acceptable as a permanent runtime code path. Treating a legacy-data migration and a live read path as the same problem would have led to either wrongly rejecting a reasonable migration technique, or wrongly accepting an unbounded runtime dependency — this ADR keeps them distinct on purpose.

**Rationale for preferring the parse path over always re-fetching from Hub:**

- The project's own roadmap (README "Roadmap / known limitations") already flags *"Backoff jitter and retry metrics for outbound Hub API calls (before parallel ingestion)"* as unresolved. Adding a full re-scrape of every already-indexed job as the default backfill path would mean routing a bulk, migration-triggered burst of calls through outbound infrastructure the project has already flagged as not yet hardened for heavier use — exactly the kind of load this ADR should not introduce for a payload-only schema change.
- `the_hub_client/http.py`'s documented client-side pacing (`HUB_CLIENT_REQUEST_DELAY`, default 0.25s) exists specifically to be a considerate default caller of a third-party API. A full re-fetch of N already-known-good jobs, at 0.25s/request minimum, costs real wall-clock time (minutes, for a collection of even a few hundred jobs) and Hub API quota for data that fundamentally hasn't changed — for a change that doesn't need the network at all if the data can be recovered locally.
- The parse path has none of these costs: it runs entirely against data already in Qdrant, with no external network dependency, and completes in the time it takes to scroll the collection and rewrite payloads.
- The fallback path is intentionally narrow and self-documenting: if it fires often in practice, that's a signal of a *different*, pre-existing problem (points with missing/malformed `document_text` — see `llm_client/context.py`'s existing handling of empty `document_text`, which already anticipates this can happen) worth investigating on its own, not something this ADR should silently paper over by always re-fetching.

## Decision 3: No payload index on `job_title`/`company` for now

**Decision:** Unlike `Country`/`Remote` (ADR-0002 Decision 2), `job_title` and `company` do not get a `PayloadSchemaType.KEYWORD` index at this time.

**Rationale:**

- ADR-0002 indexed `Country`/`Remote` proactively because they satisfy two conditions together: small, closed cardinality (6 countries, 2 booleans), *and* an immediate, concrete consumer — the filtering mechanism built in the same ADR. `job_title` and `company` are open, high-cardinality free text, and no current feature filters or groups on them; indexing now would be optimizing for an access pattern that doesn't exist yet, on a guess about its shape.
- This is the same standard ADR-0001 already applies to model/provider choices and ADR-0002 Decision 3 applies to filter derivation: don't pay for capability current evidence doesn't call for. Recorded as a revisit trigger instead of built speculatively — the trigger condition is concrete and checkable (see below), not a vague "if it seems useful later."

## Decision 4: Batch the backfill writes — don't issue one network round trip per point

**Decision:** The backfill scrolls the collection in pages (mirroring `get_indexed_job_ids`'s existing `db_client.scroll(..., limit=100, ...)` pattern) and applies payload updates in batches via `db_client.batch_update_points` with one `models.SetPayloadOperation` per point per batch, rather than calling `set_payload` once per point sequentially. Batch size reuses the project's existing `INGEST_BATCH_SIZE` convention (`db/db_utils.py`) rather than introducing a new, uncoordinated constant.

**Rationale:**

- A naive per-point loop issues one network round trip per job — for a collection of N points, that's N sequential round trips to Qdrant, each paying full request/response overhead for a tiny payload change. Batched updates amortize that overhead across many points per call.
- This mirrors a pattern the project already uses for a different reason (`INGEST_BATCH_SIZE` bounds *Hub API* call bursts in `sync_qdrant_db`/`seed_qdrant_db`); applying the same discipline to *Qdrant* writes here is the same "batch bounded, sequential work" principle applied to a different backend, not a new idea introduced ad hoc.
- Cost of getting this right now is small (use an existing client method with a list argument instead of a loop); cost of not doing it is a migration that gets slower, linearly, as the collection grows — precisely the kind of cheap-now-vs-expensive-later trade-off ADR-0002 Decision 2 already used to justify proactive indexing, applied here to write batching instead.

## Performance considerations (summary)

- **Read path:** O(1) payload lookup per field per request, replacing what would otherwise be a per-request string parse repeated indefinitely — the single biggest reason this is a schema change and not a query-time utility function.
- **Backfill path:** no re-embedding (the vector and `document_text` are untouched — FastEmbed/`bge-small-en-v1.5` never runs), no default network dependency (parse path runs entirely against already-local Qdrant data), and batched writes bound the number of round trips instead of scaling 1:1 with collection size.
- **Fallback path cost is intentionally bounded and rare**, not the default — it exists for correctness on malformed/missing data, not as the primary mechanism, so it doesn't reintroduce the Hub-load problem the primary path was designed to avoid.

## Consequences

**Positive:**

- `job_title`/`company` become available as reliable, direct payload fields for future filtering, grouping, or structured display (e.g. adding them to `JobSearchHit`/`ChatSource`) — no text-parsing dependency in any live code path.
- Closes a schema inconsistency: all job attributes that exist as discrete source fields (`Country`, `location`, `Remote`, and now `job_title`, `company`) are consistently promoted to payload metadata.
- No re-embedding or (in the common case) Hub API re-scraping cost — the backfill is payload-only and network-free by default.
- The batching approach means the migration's cost scales sub-linearly with round trips as the collection grows, consistent with the project's stated expectation of possibly scaling beyond prototype.

**Negative / accepted risks:**

- Existing points need a one-time backfill before the new fields are available; until it runs, older points lack `job_title`/`company` (callers must treat them as optional on `ChatSource`, same as `country`/`location` already are).
- The backfill's parse path depends on `document_text`'s first-two-lines format having been stable since ingestion. This is true for every point ever written by the current `load_jobs_into_qdrant`, but would need re-evaluating if that function's template is ever restructured *before* the backfill runs — a narrow, one-time coupling accepted deliberately (see Decision 2's table), not the ongoing coupling Decision 1 rejects.
- `document_text` still duplicates `job_title`/`company` as part of the embedded string — intentional, since semantic search still needs them in prose form; the payload field is additive, not a replacement.
- Pre-existing payload key-casing inconsistency (`Country`, `Salary Type`, `Remote` are capitalized; `location`, `job_role` are not) is not addressed here. `job_title`/`company` are added in lowercase, consistent with the newer fields; a full normalization pass is out of scope — see Revisit triggers.

## Revisit triggers

- If a feature requiring exact-match filtering or grouping by `company` or `job_title` is proposed (e.g. "jobs at Acme", "group results by company"), add a `KEYWORD` payload index per the reasoning in ADR-0002 Decision 2.
- If the backfill's fallback path (Hub API re-fetch) fires for more than a small fraction of points, treat that as a signal of a separate, pre-existing data-quality issue (points with missing/malformed `document_text`) worth its own investigation — do not respond by just making the fallback the default.
- If payload key-casing inconsistency becomes a real maintenance cost — e.g. a bug caused by guessing the wrong case — do a dedicated normalization pass across all payload keys as its own ticket, not folded into this one.

## Alternatives considered and rejected

- **Parse `job_title`/`company` from `document_text` on every read** (in `_payload_to_hit`/`_payload_to_source` or similar) — rejected: pays a per-request cost forever for data that's free at ingestion time, and couples every reader to the ingestion template's exact wording. See Decision 1.
- **LLM-based extraction of `job_title`/`company` from `document_text`** — rejected more decisively than the equivalent option in ADR-0002 Decision 3: that ADR at least weighed LLM extraction against a real gap (free-text country mentions in a question). Here there is no gap for *new* ingestion — `job.job_title`/`job.company` are already structured data before `document_text` is built — so paying inference cost and latency to reconstruct data that already exists has no offsetting benefit.
- **Always re-fetch from the Hub API for the backfill, skip the deterministic parse** — rejected as the default path (though kept as the fallback): unnecessary load on an outbound dependency the project's own roadmap already flags as not yet hardened for heavier/parallel use, for data recoverable locally at zero network cost. See Decision 2.
- **Full `drop_db` + `seed_qdrant_db` re-ingest** to get the new fields onto existing points — rejected as unnecessarily expensive (full Hub API re-scrape *and* re-embedding) for a payload-only addition; the targeted backfill (Decisions 2 and 4) achieves the same outcome without either cost.
- **Per-point sequential `set_payload` calls for the backfill** — rejected in favor of batched `batch_update_points` (Decision 4): correct but needlessly slow at scale, one network round trip per point instead of per batch.
