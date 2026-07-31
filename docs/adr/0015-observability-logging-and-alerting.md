# ADR-0015: Structured Request/Ingestion Logging and Prompt-Injection Alerting via Grafana Cloud

* **Status:** Proposed
* **Date:** 2026-07-18
* **Related:** ALE-127 (spike), ADR-0012 (existing prompt-injection detection/logging at ingestion, and the closed-set/strip-and-log posture this ADR extends to user queries), ADR-0013 (deployment strategy, $0/month constraint, Render free-tier cold starts), ADR-0006 (chat endpoint hardening, source of `GenerationRateLimitError`), ADR-0007 (Ollama fallback generator), ALE-144 (in-house eval tooling, distinct scope)

## Context

ALE-127 scoped DevOps observability options against concrete needs surfaced ahead of MVP launch: structured logging of prompts/responses (for later eval-set mining), retrieval insights (retrieved job IDs + scores), server-side errors, request latency, Gemini rate-limit visibility, and alerting on prompt-injection attempts.

ALE-128 (the originally-planned LLMOps counterpart spike) was canceled and superseded by ALE-144, but ALE-144 is scoped to in-house eval tooling against curated fixtures, not live-traffic capture — so the prompt/response/retrieval-logging need has no other owner and is decided here.

A follow-up review of the initial draft surfaced a real scope gap: ADR-0012 only detects injection attempts embedded in scraped job content (`document_text`) at ingestion. It says nothing about a user directly typing an adversarial question into `/chat` itself — a different attacker (the user, not a third-party job poster) via a different mechanism (no sanitizer runs on the question today). Decision 6 closes this using the same posture and infrastructure already established for ingestion.

No confirmed production incidents have driven this ADR — it is proactive, MVP-launch-readiness work, evaluated for proportionality at every decision below, consistent with this project's evidence-led (not capability-ahead-of-need) posture.

## Decision 1: A single log sink — direct Loki push to Grafana Cloud's free tier, no OpenTelemetry, no Collector

**Decision:** Ship structured logs from both the backend and the ingestion workflow directly to Grafana Cloud Loki via a plain Python `logging` handler (e.g. `inuits-python-logging-loki`'s `LokiHandler`), attached in a small shared logging-setup module imported by both entry points.

**Rationale:**

- OpenTelemetry's SDK/Collector machinery was considered and rejected: the only real benefit beyond a direct Loki push is protocol-level portability *away from Grafana Cloud itself*, which isn't a live concern — Grafana/Loki is the desired proven solution, not a hedge target. A Collector would also be a new service to run and patch, cutting against ADR-0013's "no infra to babysit" reasoning for the rest of the stack.
- Self-hosting Grafana + Loki was also rejected for the same reason: free to license, but reintroduces the VM-patching burden ADR-0013 already decided against.
- Grafana Cloud's free tier (50GB logs, 14-day retention, 3 users, no credit card) has far more headroom than this project's traffic will approach.
- A direct push also fully satisfies the original motivation for looking beyond Render's own log viewer: logs never touch Render at all, so a future move away from Render hosting doesn't affect this pipeline.

## Decision 2: Structured per-request log schema for `/chat`

**Decision:** Emit one structured log entry per `/chat` request containing: `prompt`, `response`, retrieved job IDs + similarity scores, `latency_ms`, `status`, and `error_type` — with `GenerationRateLimitError` (ADR-0006) tagged as its own distinguishable `error_type` value, not folded into a generic 5xx bucket.

**Rationale:**

- This is the field set ALE-127's requirements comment named explicitly: it directly enables mining production traffic into future eval-set cases (extending ALE-144's "production-derived cases" pattern) while also serving as the error/latency/rate-limit visibility layer — one schema serving multiple stated needs rather than separate mechanisms for each.
- Distinguishing rate-limit hits by type (rather than generic error status) is what makes them visible without a dedicated error-tracking product like Sentry.

## Decision 3: No dedicated error-tracking product (Sentry) at this stage

**Decision:** Server errors, including rate-limit hits, surface as structured log fields (Decision 2) queryable in Grafana, not through a separate error-tracking product.

**Rationale:**

- At this traffic volume, plain structured logs are sufficient to distinguish "broken" from "expected" without needing Sentry's stack-trace grouping/deduplication.
- Keeps the observability surface to a single vendor (Grafana Cloud) rather than two.

**Accepted risk:** no automatic issue grouping/deduplication — if the same underlying error recurs, it appears as N separate log lines, not one grouped issue. Acceptable at current traffic; see Revisit triggers.

## Decision 4: Uptime monitoring is deferred, not selected

**Decision:** No external uptime/liveness check (not UptimeRobot, not Better Stack, not Grafana Cloud Synthetic Monitoring) is adopted at this time.

**Rationale:**

- The backend runs on Render's free tier, which spins down after 15 minutes of inactivity (cold starts, ~30–60s, already an accepted limitation per ADR-0013). Any external check interacts with that spin-down in a way that needs an explicit choice, not a default: a check frequent enough to detect downtime promptly (<15 min interval) would incidentally keep the service permanently warm, consuming nearly all of Render's 750 free instance-hours/month and silently reversing ADR-0013's already-accepted cold-start trade-off without a deliberate decision to do so; a check infrequent enough to preserve the spin-down behavior needs a timeout comfortably longer than a cold start to avoid false "down" alerts on ordinary wake-ups.
- Rather than resolve that fork by default, uptime monitoring is explicitly deferred until there's real evidence it's needed.

## Decision 5: Reuse the existing ADR-0012 injection-detection log; add alerting on top of it, not new detection

**Decision:** Route the existing ingestion-time prompt-injection detection log (ADR-0012 Decision 4 — job ID + stripped pattern) into the same Loki sink as Decision 1, and add a Grafana Alerting rule (included free in Grafana Cloud) matching a structured `event=injection_detected` field, firing to an email contact point.

**Rationale:**

- Detection already exists and already logs — the gap was that nothing surfaced it. This makes an existing signal actionable rather than building new detection.
- The alert only needs to evaluate on the ingestion workflow's own cadence (daily), since that is the only place this detection currently runs.

## Decision 6: Detect and log prompt-injection attempts in user-submitted `/chat` questions

**Decision:** Apply the same closed-set, deterministic pattern-matching approach ADR-0012 Decision 3 uses for `document_text` (e.g. "ignore previous instructions", role-token-like strings such as `"system:"`, `"###"`) to the user's question text at `/chat` request time. On a match: log it via the shared Loki sink (Decision 1) with a structured field distinguishing it from ingestion-time detections (e.g. `event=injection_detected`, `source=user_query` vs. `source=ingestion`), and feed it into the same Grafana Alerting rule from Decision 5. **Do not block, reject, or alter the response for a matched request — continue processing normally**, same strip-and-log-and-continue posture as ADR-0012 Decision 4.

**Rationale:**

- Closes the gap named in Context: this is a different attacker (the user, not a third-party job poster) than ADR-0012 addresses, and needed its own decision rather than being silently assumed as covered.
- **Why not block:** the same false-positive argument ADR-0012 Decision 4 already made applies here, arguably more strongly — a legitimate question can easily contain flagged phrasing (e.g. "what jobs mention ignoring probation-period clauses?") without any malicious intent, and blocking a real user's real question on a keyword match is a worse product experience than a job posting sitting stripped-but-included in the corpus.
- **Why this is proportionate despite no structural defense existing for this vector** (unlike job content, which ADR-0012 Decision 1 also defends structurally via delimiters — a user's question is intentionally treated as the primary instruction, not sandboxed data, so there is no equivalent structural mitigation here): the system's actual capabilities bound the damage a successful attempt can do. `/chat` is read-only RAG Q&A with no tool use, no side-effecting actions, and no access to secrets beyond the system prompt's own phrasing — at worst, a successful jailbreak yields an off-topic or leaked-system-prompt-style answer, not data exfiltration or an unauthorized action. That severity ceiling is what makes log-and-continue proportionate here too, not recklessness.
- Reuses the exact infrastructure Decisions 1 and 5 already establish — no new sink, no new alerting mechanism, just a second call site for the same pattern-matching logic and a distinguishing field.

**Explicit non-goal:** this is closed-set pattern matching for known common phrasings, not a comprehensive jailbreak-defense or "prompt firewall" system — matching ADR-0012's own deliberately proportionate stance toward a hypothetical-but-plausible, not confirmed, threat.

## Out of scope

* Blocking, rejecting, or altering the response for any request that trips pattern matching (ingestion or user-query) — explicit non-goal; see Decisions 4 and 6's strip-and-log-and-continue posture.
* A comprehensive jailbreak-defense or "prompt firewall" system — out of scope; both ADR-0012 and Decision 6 here are closed-set pattern matching against known phrasings, not exhaustive defense.
* Uptime/liveness monitoring — deferred per Decision 4, not designed here.
* A Grafana dashboard — no metrics pipeline exists yet to justify one; may follow naturally once the structured logs above are in place, not designed here.
* Sentry or any other dedicated error-tracking product — see Decision 3.
* OpenTelemetry SDK, Collector, or self-hosted Grafana/Loki — see Decision 1.
* Any implementation: logging setup, handler wiring, pattern-matching code, or alert rule configuration — separate implementation ticket.

## Consequences

**Positive:**

- Single vendor (Grafana Cloud), single mechanism (structured logs + alerting) covers all six of ALE-127's stated MVP requirements except uptime, which is deliberately deferred.
- No new infrastructure to run or patch — consistent with ADR-0013's hosting philosophy extended to observability.
- Logs are immediately useful for eval-set mining (ALE-144), not just point-in-time debugging.
- Makes an existing detection mechanism (ADR-0012) actionable at negligible additional cost, and closes the previously-unowned user-query injection gap using the same mechanism and posture, at similarly negligible cost.

**Negative / accepted risks:**

- No error grouping/deduplication (Decision 3) — noisier triage than Sentry would offer at higher error volumes.
- No uptime visibility (Decision 4) — downtime is only discovered when someone notices, or a user reports it.
- Closed-set pattern matching (Decision 6, inheriting ADR-0012's same limitation) — sophisticated or paraphrased injection phrasing in a user's question will not be caught. Accepted because severity is bounded by the system's actual capabilities (read-only RAG Q&A, no tool use), not because the detection itself is comprehensive.
- Direct Loki push (no Collector) has lower delivery reliability under transient network issues than a Collector-buffered pipeline — accepted at this traffic volume.

## Revisit triggers

- If plain-log error triage becomes too noisy to work through by hand, reconsider Sentry.
- If cold starts or undetected downtime become an actual problem in practice, revisit uptime monitoring — starting with Grafana Cloud Synthetic Monitoring given the single-vendor preference already established here.
- If traces/metrics become genuinely needed, or a move off Grafana Cloud is ever actually on the table, revisit adopting OpenTelemetry.
- If alerting shows genuine, frequent user-query injection attempts (not just benign keyword coincidences), consider blocking or short-circuiting matched requests — mirroring ADR-0012's own revisit trigger for its ingestion-time detection.
