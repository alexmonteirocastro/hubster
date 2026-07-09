# ADR-0007: Local Generation Fallback via Ollama (qwen3:8b)

* **Status:** Accepted
* **Date:** 2026-07-09
* **Related:** ALE-101 (implementation), ADR-0001 (Generator interface, provider strategy), ADR-0006 (GenerationRateLimitError / GenerationUnavailableError contract)

## Context

ADR-0001 chose Gemini 2.5 Flash as the default generation provider behind a provider-agnostic `Generator` interface, with an explicit revisit trigger: *"Free-tier daily request limits are hit regularly under real usage."* That trigger fired during local load and stress testing — Gemini's free-tier rate limit was exhausted before the tests could complete, blocking development and evaluation of `/chat` behavior under realistic request volume.

The `Generator` interface exists precisely so this does not require rewriting `/chat`, prompt assembly, or error-handling paths. The question is not *whether* to add a second provider, but *which* local option and how to wire it without disturbing the Gemini default.

### Target dev hardware

The decision was evaluated against the project's primary development machine: CPU-only (Intel UHD 630 integrated graphics, no compute-relevant GPU), 32 GB RAM. This matters because local inference latency and memory footprint are first-order constraints — not abstract "self-hosted LLM" concerns.

| Model | Quantization | Approx. RAM | CPU inference (observed range) |
|---|---|---|---|
| `qwen3:8b` | Q4_K_M | ~5–6 GB | ~5–12 tok/s |

`qwen3:8b` at Q4_K_M fits comfortably in 32 GB with headroom for Qdrant, the API process, and the OS. Slower than Gemini's cloud API, but acceptable for local dev and stress testing where the goal is exercising the RAG pipeline, not minimizing latency.

### Why Ollama

- **OpenAI-compatible HTTP API** — `POST /v1/chat/completions` can be called with the project's existing `requests` dependency; no new SDK.
- **Simple local setup** — `brew install ollama`, `ollama pull qwen3:8b`, `ollama serve`.
- **Opt-in, not a migration** — Gemini remains the default; Ollama is selected via `LLM_PROVIDER=ollama` for environments where Gemini quota is a blocker.

## Decision 1: Add `OllamaGenerator` as a second `Generator` implementation

**Decision:** Implement `llm_client/ollama.py` with `OllamaGenerator(Generator)`, calling Ollama's OpenAI-compatible endpoint at `{OLLAMA_BASE_URL}/chat/completions`. Reuse `build_generation_prompt()` from `llm_client/context.py` unchanged — the anti-hallucination prompt and structural guardrail (ADR-0001 Decision 3) apply regardless of provider.

**Rationale:**

- Provider-specific code stays in `llm_client/ollama.py`; `api/main.py` continues to depend on `Generator` only.
- No retry/backoff layer for Ollama — local connection failures are not transient rate limits; a single attempt with a clear `GenerationUnavailableError` matches ADR-0006's contract without conflating local downtime with Gemini's 429 semantics.

## Decision 2: Provider selection via `LLM_PROVIDER` config

**Decision:** `LLMSettings` gains:

| Field | Env var | Default |
|---|---|---|
| `llm_provider` | `LLM_PROVIDER` | `"gemini"` |
| `ollama_base_url` | `OLLAMA_BASE_URL` | `"http://localhost:11434/v1"` |
| `ollama_model` | `OLLAMA_MODEL` | `"qwen3:8b"` |
| `ollama_timeout_seconds` | `OLLAMA_TIMEOUT_SECONDS` | `60.0` |

`get_generator()` in `llm_client/__init__.py` branches on `llm_provider` and returns `OllamaGenerator` or `GeminiGenerator`.

**Rationale:**

- Default `"gemini"` preserves existing behavior for Docker, CI, and production-like setups.
- `GEMINI_API_KEY` is only required when `llm_provider == "gemini"` — `LLM_PROVIDER=ollama` must not fail validation for a missing Gemini key.
- `ollama_timeout_seconds` defaults to **60s** (vs Gemini's 30s) because CPU inference is slower; these are intentionally separate settings, not unified into one shared timeout.

## Decision 3: Error mapping follows ADR-0006 contract

**Decision:** `OllamaGenerator` maps connection errors, timeouts, non-2xx HTTP responses, and empty/invalid response bodies to `GenerationUnavailableError` — the same exception type `GeminiGenerator` uses for upstream unavailability. No `GenerationRateLimitError` mapping (local Ollama has no Gemini-style quota).

**Rationale:** `/chat` already maps `GenerationUnavailableError` → **502**. Clients see a consistent "generation failed" outcome without `/chat` knowing which provider was used.

## Consequences

**Positive:**

- Local dev and stress testing no longer consume Gemini free-tier quota.
- The ADR-0001 revisit trigger is addressed without changing the default provider or endpoint contract.
- Unit tests mock the HTTP layer — CI needs no live Ollama instance.

**Negative / accepted risks:**

- CPU-only inference is significantly slower than Gemini (~5–12 tok/s); acceptable for dev, not for production serving.
- Generation quality of `qwen3:8b` vs `gemini-2.5-flash` has not been evaluated against the ADR-0001 Decision 5 eval set — grounding behavior is assumed similar enough for pipeline testing, not certified equivalent.
- Ollama is not containerized for CI or shared environments in this PR.

## Revisit triggers

| Trigger | Action |
|---|---|
| Evidence that `qwen3:8b` grounding quality differs materially from Gemini on the generation eval set | Run ADR-0001 Decision 5 eval against Ollama; consider a follow-up ticket |
| Need for Ollama in CI or multi-developer shared environments | Containerize Ollama or document a shared instance; out of scope for ALE-101 |
| Production traffic moves off Gemini free tier | Re-evaluate whether local Ollama remains relevant or a paid cloud provider is preferable |
| `qwen3:8b` or Ollama's API shape changes | Update `OllamaGenerator` and defaults; contained to `llm_client/ollama.py` |

## Alternatives considered and rejected (for now)

- **Making Ollama the default provider** — rejected; Gemini remains better for anyone without Ollama running locally.
- **Adding a new SDK (e.g. `ollama` Python package)** — rejected; OpenAI-compatible HTTP via `requests` is sufficient and matches the project's existing HTTP patterns.
- **Unifying Gemini and Ollama timeouts** — rejected; CPU inference latency justifies a higher Ollama default without affecting Gemini's 30s budget.
