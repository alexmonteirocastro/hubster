# ADR-0001: LLM Provider Strategy for the RAG Generation Layer

* **Status:** Accepted
* **Date:** 2026-07-05
* **Related:** ALE-73 (spike), ALE-76 (implementation), ALE-68 (retrieval golden-set tests), ALE-72 (Settings pattern)

## Context

Hubster's stated purpose is a RAG layer on top of The Hub — better candidate experience when job searching. Retrieval (Qdrant + FastEmbed) is built and verified (ALE-68). Generation is not. ALE-73 scoped the open questions; this ADR records the answers and, more importantly, *why*, so the reasoning survives independently of any one ticket.

Two decisions are bundled here because they were originally proposed together and needed to be pulled apart:

1. Which model(s) to use for **embeddings** (turning text into vectors).
2. Which model to use for **generation** (turning retrieved context + a question into an answer).

### Why this needed more than "pick the free option"

The initial proposal was to use Google's Gemini API for both embeddings and generation, on the strength of its free tier. Two things surfaced during evaluation that made "just use the free tier" insufficient as a decision on its own:

- **The free tier is not stable.** Gemini's free-tier quotas changed shape multiple times through 2026 (a sharp cut in December 2025, further rebalancing in April and May 2026), and published rate limits disagree by source and month at the time of writing.
- **Vendor churn is not hypothetical here.** `gemini-2.0-flash` and `text-embedding-004` — the exact embedding model named in the original proposal — were both fully deprecated and shut down within the past year (`text-embedding-004` on January 14, 2026). A decision made without accounting for this would likely need to be redone within the project's own lifetime.

Given that, the goal of this ADR is not just "pick a model" but "pick a model *and* an architecture that keeps the cost of being wrong, or of the vendor changing, low."

## Decision 1: Embeddings stay on local FastEmbed — not moved to Gemini

**Decision:** Keep the existing embedding pipeline (`qdrant-client[fastembed]`, model `BAAI/bge-small-en-v1.5`, running in-process) unchanged.

**Rationale:**

- Embedding vectors from two different models are not comparable. Switching models is not a drop-in change — it requires re-embedding every point already stored in Qdrant, a breaking migration.
- The current pipeline is free, has no rate limit, and has no network dependency — ingestion works offline and cannot be rate-limited by a third party.
- It is already verified end-to-end by the retrieval golden-set tests (ALE-68).
- No quality problem exists today that would justify the migration cost above.

**Note for the record:** the specific model named in the original proposal, `text-embedding-004`, was deprecated by Google on January 14, 2026; its replacement is `gemini-embedding-001`. This is not the reason embeddings are staying put — the architectural reasons above are — but it's worth recording so a future revisit doesn't reference a dead model name.

This decision keeps retrieval and generation independently swappable, which matters more as this moves past prototype stage: a generation-layer vendor change should never require touching ingestion.

## Decision 2: Generation uses Gemini 2.5 Flash — behind a provider-agnostic interface

**Decision:** Use `gemini-2.5-flash` (pinned to the stable model name, not a `-preview` alias) as the generation model for the prototype stage, accessed exclusively through a `Generator` interface that the rest of the application depends on — never through the Gemini SDK directly.

### 2a. Why Gemini 2.5 Flash, specifically

Options evaluated (pricing as of July 2026, per 1M tokens):

| Model | Input / Output | Free tier | Notes |
|---|---|---|---|
| **Gemini 2.5 Flash** | $0.30 / $2.50 (paid) | Yes — volatile, ~10–15 RPM / ~1,000–1,500 RPD, has shifted repeatedly in 2026 | Large context window, fast, official Python SDK |
| Gemini 2.5 Flash-Lite | $0.10 / $0.40 | Yes — higher free-tier RPD than Flash | Optimized for throughput over reasoning quality |
| GPT-4.1 Nano | $0.10 / $0.40 | No | Cheapest paid option evaluated |
| GPT-5 Nano | $0.05 / $0.40 | No | Cheapest input cost evaluated |
| Claude Haiku 4.5 | $1.00 / $5.00 | No | Reported strong instruction-following; no unstable free tier to migrate off later |

Gemini 2.5 Flash was chosen over Flash-Lite specifically on a quality basis, not a cost basis: Flash-Lite trades reasoning quality for more free-tier throughput, but throughput was never going to be the bottleneck for a low-traffic prototype. The property that actually matters for this system is reliably following the "answer only from the supplied jobs" instruction (see Decision 3) — that favors the stronger model.

Claude Haiku 4.5 and the OpenAI Nano-tier models were set aside for this stage on cost grounds only, not quality — none of them are free, and nothing about this workload (short, template-shaped answers over a handful of retrieved job listings) currently demands paying for generation. See "Revisit triggers" below for when that calculus should be redone.

**Known trade-offs accepted with this choice:**

- Free-tier prompts and outputs may be used by Google to improve their products (the paid tier disables this). Acceptable for a prototype; worth surfacing to users if this ever handles real candidate data at scale.
- Google's API terms require EEA/UK/Switzerland users to be on a paid tier — not a blocker today, but relevant if this project ever has non-US users depending on the free tier.
- The free-tier rate limit is not something to hardcode anywhere in the codebase or its comments — verify the live limit in Google AI Studio at implementation time, and design for graceful degradation regardless of the actual number.

### 2b. Why a provider-agnostic interface, not a direct integration

This is the more important part of this decision. Given the deprecation history above, wiring the Gemini SDK directly into `api/main.py` would mean the next vendor change (a deprecation, a pricing change, a decision to move to a paid tier or a different provider) requires a rewrite of the endpoint itself.

Hubster already has a working pattern for exactly this problem: `the_hub_client` package isolates every Hub-API-specific detail (HTTP calls, response shapes, retry/backoff) behind typed functions and models (`JobOpportunity`, `get_full_jobs_picture_by_country`, etc.), so `db/` and `api/` never touch raw Hub JSON. The generation layer gets the same treatment:

```
llm_client/
├── base.py       # Generator protocol/ABC: generate(context: str, question: str) -> str
├── gemini.py     # concrete implementation for Gemini 2.5 Flash
└── settings.py   # model name + API key from env, via the Settings pattern (ALE-72)
```

`api/main.py`'s `/chat` endpoint depends on `llm_client.base.Generator`, never on `llm_client.gemini` directly. Swapping providers later — to a paid tier, to Claude, to OpenAI, to a self-hosted model — becomes a new module implementing `Generator` plus a config value, not a rewrite of endpoint, prompt, or test code.

## Decision 3: Anti-hallucination guardrail is structural, not just a prompt instruction

**Decision:** If retrieval returns zero results, or results judged clearly insufficient, the `/chat` endpoint skips generation entirely and returns a deterministic "no matching jobs found" response. The LLM is never invoked with empty or near-empty context.

**Rationale:** ALE-73 specifically flagged the risk of the system describing a job that was never actually retrieved. Prompting the model not to hallucinate helps, but is not a guarantee. Removing the opportunity — never sending an empty context in the first place — is a stronger and simpler guarantee, and is straightforward to unit test deterministically (mocked retrieval → empty results → assert the fallback path, no call to the `Generator` at all).

## Decision 4: `/chat` is single-turn and stateless for v1

**Decision:** No server-side conversation history or session management in the initial implementation. Each request to `/chat` is self-contained.

**Rationale:** Multi-turn conversation is a legitimate future need, but it introduces session storage and state-security questions (where is history kept, how long, scoped to whom) that nothing about the current product justifies solving yet. Scoping it out explicitly, rather than building a partial version of it, keeps the v1 surface small and testable. Revisit as a dedicated follow-up ticket if/when it's actually needed.

## Decision 5: Generation-quality evaluation is separate from retrieval evaluation

**Decision:** A small, separate, hand-curated eval set (query → expected behavior) will be added for generation, gated behind its own pytest marker (mirroring the existing `retrieval` marker), distinct from the retrieval golden-set (ALE-68).

**Rationale:** This preserves the retrieval/generation separation the project already committed to. If `/chat` gives a bad answer, the two evaluation suites let you determine independently whether retrieval fetched the wrong jobs or generation reasoned about the right jobs poorly — rather than debugging both layers at once.

## Consequences

**Positive:**

- Zero incremental cost for generation at current traffic levels.
- The one component most exposed to vendor churn (generation) is isolated behind an interface; the rest of the codebase (retrieval, ingestion, API contract) is unaffected by a future provider change.
- The anti-hallucination guarantee is structural and independently testable, not dependent on prompt-engineering discipline holding up over time.

**Negative / accepted risks:**

- Free-tier rate limits may be hit under any real concurrent usage; the system will need to degrade gracefully (clear error, not a crash) rather than silently succeed at higher traffic. This is explicit scope in ALE-76, not deferred.
- The pinned model (`gemini-2.5-flash`) may itself be deprecated in the future, consistent with the pattern already observed twice in this same vendor's lineup. The `Generator` interface exists specifically to make that a contained change.
- This ADR's pricing table will go stale. Treat the numbers here as "true as of July 2026, verify before acting on them," not as a permanent reference.

## Revisit triggers

Reconsider this decision (not necessarily change it) if any of the following occur:

- Free-tier daily request limits are hit regularly under real usage.
- The generation-quality eval set (Decision 5) surfaces grounding failures that seem specific to Gemini 2.5 Flash's behavior rather than to prompt design.
- `gemini-2.5-flash` receives a deprecation notice.
- The project moves from "personal prototype" to something with real users, at which point the free-tier data-use and regional-availability terms (see Decision 2a) become a real constraint rather than an accepted trade-off.
- A cheaper-per-quality option becomes available (worth periodically re-checking the pricing table above against current vendor pricing pages, not this ADR).

## Alternatives considered and rejected (for now)

- **Claude Haiku 4.5** — no free tier, 3–20x the per-token cost of the cheapest options evaluated; nothing about current workload complexity justifies the cost yet. Strongest candidate if/when the "no unstable free tier" property becomes more valuable than raw cost (see Revisit triggers).
- **GPT-4.1 Nano / GPT-5 Nano** — cheapest paid options, no free tier. Viable alternative to Gemini's paid tier if that migration ever happens; not chosen over Gemini specifically because Gemini's free tier removes the cost question entirely for now.
- **Self-hosted open-weight model** — would remove all vendor/rate-limit risk entirely, but adds real operational complexity (GPU/CPU provisioning, model serving, ops burden) disproportionate to this project's current scope. Not evaluated in depth; would be worth revisiting only if a specific concrete need (e.g. full data privacy) emerged.