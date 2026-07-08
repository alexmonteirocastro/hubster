# ADR-0006: Chat Endpoint Hardening (Question Length + Rate Limiting)

* **Status:** Accepted
* **Date:** 2026-07-09
* **Related:** ALE-87 (implementation), ALE-74 (public-facing consumer), ALE-76 (generation layer), ADR-0001 (Gemini rate-limit risk)

## Context

ADR-0001 records that Gemini's free tier is fragile and that the system must degrade gracefully when upstream generation is throttled. ALE-76 delivered that degradation (`GenerationRateLimitError` → 429). It did not, however, limit how much traffic reaches Gemini in the first place.

Two gaps became relevant once ALE-74 put a browser UI in front of `/chat`:

1. `ChatRequest.question` had no upper bound — arbitrarily large prompts could be forwarded into a paid, rate-limited third-party call.
2. There was no request-rate limiting at the API layer (correctly deferred in ALE-69 while nothing consumed the API).

ALE-87 closes both gaps on `POST /chat` only — the endpoint with external generation cost.

## Decision 1: Enforce question length in the endpoint, not in the Pydantic schema

**Decision:** Check `len(chat_request.question)` against `settings.chat_question_max_length` at the start of the `chat()` handler and return **422** before retrieval or generation. `ChatRequest` remains a pure data contract (`min_length=1` only).

**Rationale:**

- The max length is configurable via `CHAT_QUESTION_MAX_LENGTH`; validating in the handler uses the same `get_settings()` the endpoint already depends on, without coupling `api/schemas.py` to global app config.
- A Pydantic `field_validator` calling `get_settings()` made schema construction depend on a fully-populated `Settings()` and caused test mocks on `api.main.get_settings` to silently not apply to validation — a layering bug, not a feature.

**Trade-off:** The generated OpenAPI schema does not show a static `maxLength` on `question`. The bound is documented in the README and `.env.example` instead.

## Decision 2: Per-client in-memory rate limiting on `/chat` via slowapi

**Decision:** Apply `slowapi` with the default in-memory backend to `POST /chat` only. Default limit: **`10/minute`** per client IP (`get_remote_address`). Configurable via `CHAT_RATE_LIMIT`. Return **429** with a clear `detail` message when exceeded.

**Rationale:**

- `/jobs/search` and `/jobs/stats` have no Gemini cost; limiting them would add friction without protecting the budget.
- In-memory limiting is sufficient for the current single-process prototype — same reasoning ADR-0001 applied to not over-provisioning infrastructure without evidence.
- **`10/minute` is intentional, not arbitrary.** It aligns with the ~10–15 RPM free-tier figure ADR-0001 cites for Gemini 2.5 Flash: the API guard should stop most bursts before they hit upstream quotas, while still allowing a realistic pace of questions from one user.
- The limit string is read via a callable (`_chat_rate_limit()` → `get_settings().chat_rate_limit`) so environment overrides and tests can change behavior without re-importing the module.

**Not in scope:** `SlowAPIMiddleware` (would add `Retry-After` headers on 429). The exception handler is sufficient for enforcement; headers are optional polish.

## Decision 3: Upstream generation rate limits also return 429

**Decision:** When `Generator.generate` raises `GenerationRateLimitError` (Gemini quota exhausted after retries), return **429** — not 503 — with `"The generation service is rate-limited. Please try again shortly."`

**Rationale:** Clients and the React UI already treat 429 as "rate-limited, try again." Using 503 for the same user-visible outcome was misleading.

## Revisit triggers

| Trigger | Action |
|---|---|
| Deploy with **multiple uvicorn workers** or **N container replicas** | Each process holds its own in-memory bucket — effective limit becomes `N × CHAT_RATE_LIMIT`. Move to Redis-backed storage via slowapi's `storage_uri`. |
| Deploy **behind a reverse proxy / load balancer** without `X-Forwarded-For` handling | `get_remote_address` sees the proxy IP; all users share one bucket. Switch key function to read the real client IP from trusted forwarded headers. |
| Leave prototype stage with **real concurrent users** | Revisit per-user auth/quotas and a distributed limiter; in-memory per-IP limiting is not a tenancy model. |
| Evidence that **500 characters** is too tight or too loose for real questions | Tune `CHAT_QUESTION_MAX_LENGTH`; no schema migration required. |
