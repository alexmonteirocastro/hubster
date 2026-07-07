# ADR-0004: Frontend Architecture for the Chat Interface

* **Status:** Proposed
* **Date:** 2026-07-07
* **Related:** ALE-74 (implementation), ALE-69 (FastAPI contract), ALE-76 (`/chat` + `Generator` layer), ADR-0001 Decision 3 & 4 (anti-hallucination guardrail, statelessness), ADR-0002 (retrieval filtering, accepted risks), ADR-0005 (visual design tokens), ALE-84 (applied-filter visibility on `ChatResponse`)

## Context

`ALE-74` has existed since the FastAPI ticket was scoped, intentionally left as a placeholder: "cannot be meaningfully scoped until [the FastAPI backend] exists." That contract now exists twice over — `/jobs/search` (ALE-69) and `/chat` (ALE-76) both ship a typed Pydantic request/response schema (`api/schemas.py`). This ADR replaces the placeholder scope with real decisions now that there's a real contract to design against, following the same pattern already used for the retrieval and generation layers (spike/evidence -> ADR -> implementation ticket).

Two example `/chat` transcripts were reviewed while scoping this ADR (questions: "backend engineer, 5 years, Denmark" and "frontend engineer, Sweden, in-demand skills"). Both match, almost verbatim, the motivating failure transcripts cited in ADR-0002's own Context section ("frontend roles in Sweden", "backend roles in Denmark"). This is very likely the same evidence that produced ALE-77/78, reviewed before that fix shipped — worth re-running against the current API before treating it as still-open, since a `must`-filter on `Country` (as implemented in `query_jobs_in_qdrant`, `db/database.py`) would now return zero points, not the wrong-country jobs shown in those transcripts, for a country the ALE-78 alias table recognizes.

What *is* still open, confirmed by reading `db/query_filters.py` and ADR-0002's own "Negative / accepted risks" section directly rather than assuming: if `extract_filters_from_question` misses a phrasing, no filter is passed to `query_jobs_in_qdrant` at all — retrieval is genuinely unfiltered, returns a non-empty top-k (Qdrant always returns *some* result on a non-empty collection), generation proceeds per ADR-0001 Decision 3 and correctly declines to answer from irrelevant context, but `ChatResponse.sources` still carries those irrelevant hits. Nothing in the response today distinguishes this from a genuinely-filtered, genuinely-empty result — that gap is `ALE-84`, filed alongside this ADR, and directly shapes Decision 4 below.

## Decision 1: React + Vite + TypeScript — not Next.js, not an extension of Streamlit

**Decision:** Build a new, minimal single-page app: React, Vite, TypeScript, calling the FastAPI backend exclusively (never Qdrant or The Hub directly, matching ALE-74's original constraint).

**Rationale:**

- The demo surface is one view — a chat window. Next.js's value (SSR, file-based routing, API routes) has no current use case here; adopting it now would be paying build/deploy complexity for capability this ADR has no evidence is needed yet.
- TypeScript over plain JS keeps the same "structured contract over stringly-typed data" discipline the backend already applies (`the_hub_client.models`, `api/schemas.py`) — the API client's request/response types can be hand-mirrored from the Pydantic models directly, so a backend schema change is a visible type error in the frontend, not a silent runtime mismatch.
- Streamlit's chat tab was always documented as a placeholder (README: "chat UI is a work in progress"); its role was proving Qdrant/API wiring worked at all, not serving as the demo surface. Continuing to invest in it would mean building the real UI inside a tool chosen for internal dashboards, not user-facing chat.

## Decision 2: Direct request/response against `POST /chat` through a typed API client module — no streaming for v1

**Decision:** A single client module (e.g. `src/api/client.ts`) owns all `fetch` calls and response typing; components never call `fetch` directly. Responses are awaited in full; no Server-Sent Events or streaming UI for v1.

**Rationale:**

- Mirrors the existing project pattern of isolating an external dependency behind one module (`the_hub_client` for Hub HTTP, `llm_client.base.Generator` for the LLM provider) — the frontend's equivalent boundary is "everything that knows the API's URL and shape lives in one place," so a backend contract change touches one file, not every component.
- The `Generator` interface (ADR-0001) makes a single blocking call per request; there is no streaming token source to consume even if the frontend wanted to. Building streaming UI ahead of backend support would be speculative complexity with nothing to connect it to.

## Decision 3: Conversation history is client-side display state only — never sent back to `/chat`

**Decision:** The UI keeps a local, in-memory list of prior question/answer turns for display (so the chat reads as a conversation), but each new request to `/chat` sends only the current question — no history payload — consistent with `/chat` being single-turn and stateless server-side (ADR-0001 Decision 4).

**Rationale:**

- `ChatRequest` has no history field; inventing a client-side history parameter the API silently ignores would be worse than not sending one — it would look like a feature that doesn't exist.
- This is an accepted, visible limitation, not a hidden one: the UI should not imply memory the system doesn't have (e.g. a follow-up like "any others?" has no access to what "others" refers to). Copy in the UI should make this explicit rather than let a user discover it by confusion.

## Decision 4: Render whatever `sources` the API returns, as-is, without a client-side relevance heuristic

**Decision:** For v1, the UI renders `ChatResponse.sources` (with each source's `score`) whenever the array is non-empty, regardless of the `generated` flag. It does **not** attempt to infer relevance or suppress sources client-side based on the answer text or any local heuristic.

**Rationale:**

- The tempting fix — "hide sources when the answer sounds like a decline" or "hide sources when `generated` is false" — doesn't actually address the gap found in Context: the reviewed transcripts have `generated: true` (the LLM was invoked and correctly declined), so a `generated`-based rule wouldn't have hidden the misleading sources in the one case actually observed.
- The frontend does not currently have the information needed to do this correctly — the API doesn't say whether a filter was applied (that's exactly `ALE-84`). Building a client-side heuristic now would mean guessing at relevance with less information than the backend has, and relocating ADR-0002's accepted gap into the frontend instead of closing it. That runs against the project's established preference (ADR-0001, ADR-0002) for structural guarantees over probabilistic patching.
- Showing the score alongside each source is cheap, honest, and gives a demo viewer a real signal to judge relevance by, without the frontend pretending to know something it doesn't.

**Revisit condition:** once `ALE-84` ships (`applied_country`/`applied_remote` on `ChatResponse`), revisit this decision — it would then be correct to visually distinguish "sources matched your requested filter" from "no filter was resolved, treat these as loosely-related only," or to suppress sources entirely in the latter case.

## Decision 5: Configuration via `VITE_API_BASE_URL`; browser-reachable URL, not a Docker-internal service name

**Decision:** The API base URL is read from a build-time env var (`VITE_API_BASE_URL`, e.g. `http://localhost:8000`), never hardcoded. A `frontend` service is added to `docker-compose.yml` per ALE-74's original scope.

**Rationale:**

- This is the mirror image of the lesson already recorded for the backend (Dockerization, ALE-66): containers reach each other by service name, but the *browser* — which is what actually executes the frontend's `fetch` calls, not the frontend container — runs on the host and must reach the API via a host-published port (`localhost:8000`), not the Docker-internal name (`http://api:8000`) the `api` container would use to reach `qdrant`. Getting this backwards is a common and confusing failure mode worth documenting explicitly rather than rediscovering by trial and error.
- An env var (not a hardcoded constant) keeps local dev, Docker Compose, and any future deployment target configurable without a code change — same reasoning as the `Settings` pattern (ALE-72) already applied on the backend.

## Alternatives considered and rejected

- **Next.js** — rejected for now; no SSR/routing/multi-page requirement exists yet. Revisit if the app grows a second real view (e.g. a stats dashboard beyond the existing Streamlit one) where routing has genuine value.
- **Continuing to build out Streamlit's chat tab** — rejected: harder to hold to the same typed-contract discipline as the rest of the codebase, and the README already frames it as a placeholder, not a target.
- **Streaming (SSE) responses** — rejected for v1: no backend streaming source exists (`Generator.generate` returns a complete string), and single-turn answers over a handful of jobs are short enough that the UX cost of waiting is low. Revisit if `Generator` grows streaming support or answer latency becomes a real demo problem.
- **A global state library (Redux/Zustand/Context)** — rejected: one view, one message list; `useState`/`useReducer` is sufficient. Revisit only if the app grows enough shared state across views to justify it.
- **Client-side relevance filtering of `sources`** (score threshold, keyword match against the question, etc.) — rejected per Decision 4: the frontend lacks the information to do this correctly today, and a heuristic here would mask rather than fix the underlying gap tracked in ALE-84.

## Consequences

**Positive:**

- Builds directly against a contract that already exists and is already tested (ALE-69, ALE-76), rather than guessing at one.
- Keeps the frontend's one external dependency (the API) isolated behind a single typed client module, consistent with the project's existing isolation pattern for external dependencies.
- Decision 4 avoids quietly re-introducing a probabilistic/heuristic patch in the one place (the UI) that wouldn't be covered by any of the project's existing retrieval or generation test suites.

**Negative / accepted risks:**

- No multi-turn memory: a real limitation for a "chat" demo, and one a viewer may notice. Mitigated only by clear UI copy, not solved here.
- Sources may still appear alongside a correct "no match" answer until `ALE-84` ships and Decision 4 is revisited — an accepted, temporary rough edge for the demo, not a silent one.
- No streaming means the UI shows a loading state for the full duration of retrieval + generation, not incremental output.

## Revisit triggers

- If `ALE-84` ships, revisit Decision 4 (source suppression/labeling by applied-filter status).
- If `/chat` gains multi-turn/session support, revisit Decision 3.
- If `Generator` gains streaming support, revisit Decision 2.
- If a second real view is needed (dashboard, history, settings), revisit Decision 1 (routing/Next.js) and decide Streamlit's long-term fate explicitly rather than by default.
