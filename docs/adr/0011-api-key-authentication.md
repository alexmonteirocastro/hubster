# ADR-0011: API Key Authentication for Access Control

* **Status:** Proposed
* **Date:** 2026-07-11
* **Related:** ALE-114 (spike), ADR-0006 (chat endpoint hardening / rate limiting), ALE-72 (Settings/env-var pattern), ALE-86 (CORS configuration), ADR-0004 (frontend architecture)

## Context

ALE-114 scoped three low-effort access-control options for a small, pre-approved user list (a handful of named people, not a self-serve product): a shared bearer token/API key, an OAuth allowlist, or HTTP Basic Auth at the proxy layer. This becomes urgent once the hosting spike (ALE-107) turns `/chat` and `/jobs/*` into a publicly reachable URL rather than `localhost`.

Given the user base is small, known in advance, and doesn't need per-user session management or a real IAM system, a shared API key is the proportionate choice — the same reasoning ADR-0001 and ADR-0002 have applied elsewhere: don't build capability the current evidence and scale don't call for.

## Decision 1: Shared bearer API key, checked via a FastAPI dependency — not OAuth, not proxy-layer Basic Auth

**Decision:** Protect `/chat` and `/jobs/*` with a FastAPI dependency that checks an `Authorization: Bearer <token>` header against valid keys stored in an environment variable. `/health` remains open (hosting providers' healthchecks won't send a key).

**Rationale:**

- OAuth allowlist would add a real auth dependency to both backend and frontend, plus session handling that doesn't exist today — disproportionate for a handful of named people.
- HTTP Basic Auth at the nginx/proxy layer is cheap to bolt on, but auth state doesn't flow naturally into the SPA's `fetch` calls, and offers no per-user identity for the app itself — worse UX for no real gain at this scale.
- A FastAPI dependency keeps the check in application code, consistent with the existing `Settings`/`pydantic-settings` pattern (ALE-72) — valid keys live in `.env`, not hardcoded, and require no code change to rotate.

## Decision 2: A small set of static keys via `HUBSTER_API_KEYS`, not one shared secret

**Decision:** Store a comma-separated set of valid keys in a single env var (`HUBSTER_API_KEYS=abc123,def456,ghi789`), parsed into a set in `Settings` (ALE-72 pattern). The FastAPI dependency checks `token in settings.hubster_api_keys` instead of an exact-match comparison against one value.

**Rationale:**

- Costs essentially nothing extra over a single key — same `.env`-based config, same dependency shape, just a `.split(",")` and a set-membership check instead of a string comparison. No user table, no database, no session handling — still well inside the scope boundary ALE-114 drew (not a self-serve product, not real IAM).
- **What it buys:** independent revocation. If one collaborator's key leaks or they no longer need access, remove their entry and redeploy — everyone else's key keeps working. A single shared secret means any rotation locks out the entire group until it's redistributed to everyone at once.
- **What it does *not* buy, explicitly:** still no per-request audit trail (can't tell which key was used unless request logging is added separately — out of scope here), and still no independent expiry/TTL per key. This is deliberately an MVP-level improvement, not a step toward real IAM — if the user base or auditability needs grow, that's a revisit trigger, not something to half-solve now.

## Decision 3: `sessionStorage` on the frontend — not `localStorage`, not in-memory-only

**Decision:** Once entered, the API key is stored in the browser's `sessionStorage`.

**Rationale:**

- `/chat` renders LLM-generated markdown. ADR-0004 already excludes `rehype-raw` (no raw HTML) and ALE-112 closes the remaining image/tracking-pixel gap, so XSS surface is low — but not zero, since arbitrary web content (job postings) still flows through the generation pipeline (this is exactly what ALE-115's prompt-injection spike is scoping).
- `localStorage` would let a stolen key persist indefinitely across browser restarts — worse exposure for a security-sensitive value with no corresponding benefit at this usage pattern (the app isn't used so infrequently that re-entering per session is a real burden).
- In-memory-only (React state, lost on refresh) is the safest option but meaningfully worse UX — users would re-enter the key on every page refresh, not just every new session.
- `sessionStorage` is the middle ground named explicitly: survives refresh within a session, cleared when the tab closes, so a stolen key has a bounded lifetime tied to the browser session rather than indefinite persistence.

## Decision 4: Frontend UX — lock icon, modal entry, explicit success/failure states

**Decision:** A lock icon in the UI opens a modal for key entry. On submission:

- **Failure (401):** the modal stays open and shows a meaningful error message (not a silent failure or generic toast) — the user should immediately understand the key was rejected and can retry without re-triggering the modal from scratch.
- **Success:** the modal shows a meaningful confirmation message and a button to close it — not an auto-close, so the user has clear positive confirmation before the modal disappears.

**Rationale:**

- Auth failure is exactly the kind of state that shouldn't fail silently — per the project's general error-handling posture (e.g. `Settings` raising clear validation errors rather than defaulting silently, ALE-72), the user should always know unambiguously whether the key worked.
- Keeping the modal open on failure (rather than closing and requiring the user to reopen it) avoids a confusing extra step exactly when the user is already correcting a mistake.

## Decision 5: CORS must explicitly allow the `Authorization` header

**Decision:** Extend the `CORSMiddleware` configuration added in ALE-86 to include `Authorization` in `allow_headers`.

**Rationale:**

- ALE-86 configured CORS before this requirement existed. Without this, the browser strips the `Authorization` header on preflight, and every authenticated request would silently fail cross-origin — worth calling out explicitly since it's an easy gap to miss (the same class of "worth documenting explicitly rather than rediscovering by trial and error" the project has flagged before, e.g. ADR-0004 Decision 5's browser-vs-container URL distinction).

## Consequences

**Positive:**

- Minimal new surface area — one env var, one FastAPI dependency, one frontend modal component. No new auth infrastructure, no session/cookie handling.
- Consistent with existing patterns: `Settings`/`pydantic-settings` for the keys, `CORSMiddleware` extension for the header, explicit success/failure UX matching the project's general error-handling posture.
- `sessionStorage` bounds the exposure window of a leaked key without forcing re-entry on every page refresh.
- Independent per-key revocation (Decision 2) — removing one compromised or no-longer-needed key doesn't require redistributing a new key to everyone else.

**Negative / accepted risks:**

- No per-user audit trail — can't tell which approved person made a given request without adding separate logging. Revocation is independent per key, but this is still not a full per-user identity system.
- `sessionStorage` is still readable by any JS executing on the page — if a genuine XSS vector is found (ALE-115's prompt-injection spike is the relevant follow-up), the key is exposed for the remainder of that session.
- Static keys have no expiry/TTL — a leaked key remains valid until manually removed from the env var and redeployed.

## Revisit triggers

- If the approved user list grows enough that managing the comma-separated key set becomes unwieldy, or per-user audit trail becomes genuinely needed, revisit a real per-user store (DB table) or the OAuth allowlist option this ADR rejected — rather than continuing to grow the env var indefinitely.
- If ALE-115's prompt-injection spike surfaces a credible XSS vector through generated content, revisit `sessionStorage` specifically — that finding would directly undermine this decision's risk assessment.
- If key rotation needs to happen frequently (e.g. repeated leaks, frequent collaborator turnover), revisit moving key management out of a static env var into something more dynamic.
