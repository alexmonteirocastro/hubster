# ADR-0013: Deployment Strategy — Managed Free-Tier Hosting

* **Status:** Proposed
* **Date:** 2026-07-12
* **Related:** ALE-107 (spike), ADR-0004 Decision 5 (`VITE_API_BASE_URL`, browser-reachable URL requirement), ADR-0006 (chat endpoint hardening — single-instance rate-limiting assumption), ALE-86 (CORS configuration), ALE-72 (Settings/env-var pattern), ALE-113 (proxy timeout revisit trigger — activated, not resolved, by this ADR), ALE-108 (Ollama containerization — explicitly not needed for this deployment), ALE-119 / ALE-122 (API key auth / prompt-injection guardrails — related follow-ups, not blocking)

## Context

ALE-107 shortlisted three realistic combinations for hosting Hubster's three components (frontend, backend, Qdrant) plus ingestion, explicitly deferring the final choice to a follow-up ADR. This is that ADR. The constraint carried over unchanged from the spike: prioritize free/budget-friendly options over capability, since this is still a prototype, not a funded product.

## Decision 1: Adopt Option A (all-managed) over Option B (self-hosted VM) and Option C (Cloud Run)

**Decision:** Cloudflare Pages (frontend) + Render free web service (backend) + Qdrant Cloud free tier (Qdrant) + GitHub Actions scheduled workflow (ingestion). Realistic cost: $0/month.

**Rationale:**

- This is the fastest reliable path to a real public URL — which both ALE-114/ALE-119 (auth) and the prompt-injection guardrail work (ALE-122) are already gated on being reachable at all. Standing up the URL is itself on the critical path for other planned work, not just a nice-to-have.
- Option B (self-hosted Oracle Always Free VM) pushes OS patching and security ownership onto the project, and Oracle's own Ampere allocation was halved in June 2026 with no advance notice — a real operational risk for a solo-maintained project, on top of inconsistent account approval reports.
- Option C (Cloud Run) requires a card on file and defaults to multi-instance scaling, which would silently multiply ADR-0006's in-memory rate limit unless `--max-instances=1` is set explicitly — solvable, but avoidable complexity Option A doesn't have.
- Each of Option A's three services was independently the clear pick for its component in ALE-107's own findings (Cloudflare Pages "the clear pick, regardless of backend choice"; Render "single instance by default, matches ADR-0006... without any extra config"). Option A isn't a compromise — it's the pointwise-best choice on every axis except two explicitly named accepted risks (Decisions 3 and 4).

## Decision 2: Frontend — Cloudflare Pages, existing Vite build unchanged

**Decision:** Deploy the existing Vite static build to Cloudflare Pages. `VITE_API_BASE_URL` (ADR-0004 Decision 5) is set at build time to the Render backend's public URL.

**Rationale:** Unlimited bandwidth on the free plan, no credit card, custom domain + HTTPS included, and the existing build output deploys with no rework — confirmed in ALE-107's findings.

## Decision 3: Backend — Render free web service; cold-start latency is an accepted, documented risk, not fixed now

**Decision:** Deploy the FastAPI backend to a Render free web service. The ~30–60s cold start after 15 minutes of inactivity is accepted and documented (README/PRODUCT_VISION known-limitations section) rather than worked around.

**Rationale:**

- Genuinely $0, no card required, and Render defaults to a single instance — matching ADR-0006's in-memory rate-limiter assumption with zero extra configuration, unlike Cloud Run.
- A keep-alive ping to defeat Render's own spin-down was considered and rejected: ALE-107's findings already characterized this as "fighting the free tier rather than accepting it honestly." This project already has a stated pattern of naming accepted risks explicitly (e.g. ADR-0002's post-retrieval filtering trade-off) rather than papering over them with a workaround — the same reasoning applies here.

## Decision 4: Qdrant — Qdrant Cloud free tier; suspend risk resolved as a side effect of the ingestion cadence, not a dedicated keep-alive

**Decision:** Provision a Qdrant Cloud free-tier cluster (0.5 vCPU / 1GB RAM / 4GB disk). No separate keep-alive mechanism is added.

**Rationale:**

- Free-tier capacity comfortably covers the current collection size at 384-dim embeddings (`BAAI/bge-small-en-v1.5`), per ALE-107's findings.
- The named risk is real: free clusters auto-suspend after 1 week of inactivity and delete after 4 weeks. But the README's existing ingestion cron example (every 6 hours) already touches Qdrant far more frequently than the 1-week suspend window. If that cadence is preserved in production via Decision 5's GitHub Actions workflow, the suspend risk is resolved as a natural side effect of a mechanism the project needs anyway — not a bolted-on ping whose only purpose is to keep a free tier alive. This is a materially different situation from Decision 3's Render cold start, which has no equivalent natural mitigation and is instead accepted as-is.

## Decision 5: Ingestion — GitHub Actions scheduled workflow, no Docker Compose in production

**Decision:** Run the existing sync command (`docker compose --profile ingestion run --rm ingestion`'s underlying command, invoked directly rather than via Compose) on a GitHub Actions scheduled workflow, targeting the production Qdrant Cloud cluster.

**Rationale:** Maps directly onto the cron cadence already documented in the README — no new infrastructure concept. Public repos get unlimited free Actions minutes; this repo's usage is well within a private repo's ~2,000 free minutes/month regardless.

**Coupling to watch:** this schedule must stay under 1 week, or Decision 4's suspend-risk mitigation silently stops holding. If the cadence is ever loosened (e.g. daily → weekly), that assumption needs re-checking explicitly, not assumed to still be safe.

## Decision 6: CORS — add the Cloudflare Pages origin, no other change

**Decision:** Add the deployed Cloudflare Pages URL to the existing `CORSMiddleware` `allow_origins` list (ALE-86) via the existing env-var-driven configuration.

**Rationale:** Small, known change flagged in ALE-107's own findings. No new CORS concept — the frontend simply gains a real origin instead of only `localhost`.

## Decision 7: Proxy/read timeouts — this ADR activates ALE-113, it does not resolve it

**Decision:** ALE-113 ("Revisit /api proxy long timeouts before any non-local deployment") is explicitly triggered by this ADR landing. The current 600s timeout was sized for local CPU-bound Ollama inference (ALE-111); production defaults to `LLM_PROVIDER=gemini`, which returns in low single-digit seconds. Tuning the timeout down is scoped entirely to ALE-113, not duplicated here.

**Rationale:** Keeps this ADR about *where* things are hosted, not *how* the existing proxy is configured — ALE-113 already exists specifically for this and just needed its trigger condition to actually occur.

## Consequences

**Positive:**

- $0/month realistic total cost, matching the explicit "prototype, not funded product" constraint that framed ALE-107 from the start.
- Each component is independently the strongest free option for its role, not a bundle of compromises.
- The ingestion cadence pulls double duty — data freshness and Qdrant Cloud keep-alive — instead of adding dedicated keep-alive infrastructure.
- No Docker Compose or VM patching burden in production; all three services are managed.

**Negative / accepted risks:**

- Render's cold start (~30–60s after 15 min idle) is a real, user-facing latency cost on the first `/chat` or `/jobs/*` request after a quiet period. Accepted, not fixed.
- Moving Qdrant off self-managed persistence onto Qdrant Cloud's free tier is a trust-boundary shift onto a third party's SLA, in exchange for zero storage/backup ownership.
- **This deployment has no authentication in front of it yet.** ALE-114 (spike) is done, but ALE-119 (the ADR landing the API key design) is still in Backlog and unimplemented. Once this ADR lands and the URL is live, `/chat` — the endpoint with real Gemini API cost — is reachable by anyone who has the link. This ADR does not block on ALE-119, but broadly sharing the deployed URL before ALE-119 ships is a real, avoidable cost-exposure risk worth flagging plainly rather than assuming away.

## Revisit triggers

- If Render's cold start proves to be a genuine deal-breaker in real demos, revisit Option C (Cloud Run) specifically for the backend — accepting its card requirement and explicit `--max-instances=1` fix.
- If the GitHub Actions ingestion cadence is ever loosened beyond 1 week, revisit Decision 4's suspend-risk mitigation explicitly — it would no longer hold automatically.
- If real usage outgrows Qdrant Cloud's free-tier capacity, revisit Option B (self-hosted VM).
- Once ALE-119 ships, the "no auth yet" accepted risk above is closed — no ADR action needed, just a note that the gap is resolved.

## Alternatives considered and rejected (for now)

- **Option B — self-hosted Oracle Always Free VM running the existing Docker Compose file as-is.** Smallest actual behavior change of the three shortlisted options and worth revisiting if Render/Qdrant Cloud prove unreliable in practice — rejected for now due to Oracle's recently halved Ampere allocation, inconsistent account approval, and the patching/security burden of a real VM.
- **Option C — Cloud Run backend, Qdrant Cloud or Compute Engine for Qdrant.** More generous free compute in principle — rejected for now due to the card-on-file requirement and the multi-instance default directly fighting ADR-0006's rate-limiting assumption, for no benefit this project's current scale needs.
