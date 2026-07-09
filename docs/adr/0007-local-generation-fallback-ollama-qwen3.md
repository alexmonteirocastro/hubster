# ADR-0007: Local Generation Fallback via Ollama (Qwen3 8B)

* **Status:** Accepted
* **Date:** 2026-07-09
* **Related:** ALE-101 (implementation), ADR-0001 (LLM provider strategy — revisit trigger fired), ADR-0006 (chat endpoint hardening, `GenerationRateLimitError`/`GenerationUnavailableError`)

## Context

ADR-0001 explicitly named this scenario as a revisit trigger, not a hypothetical:

> "Free-tier daily request limits are hit regularly under real usage."

Load/stress-testing the prototype has now hit exactly this — Gemini's free-tier quota is being exhausted during testing, not production traffic, which is the worst way to hit it: it blocks development velocity rather than signaling a real capacity need.

Two things make this worth solving with a second `Generator` implementation rather than only tuning retries/backoff on the Gemini side:

1. **The system's grounding is structural, not model-dependent.** Per ADR-0001 Decision 3, generation is only ever invoked with retrieved, verified job context, and the prompt (`llm_client/context.py`) constrains the model to answer *only* from that context. The task asked of the LLM is narrow — grounded instruction-following over a short context — not open-domain knowledge or long-horizon reasoning. This is exactly the kind of task where a mid-size open-weight instruct model is competitive with Gemini 2.5 Flash, which changes the cost/quality trade-off from ADR-0001's original evaluation.
2. **`llm_client.base.Generator` already exists to make this cheap.** ADR-0001 Decision 2b built the provider-agnostic seam specifically so a vendor or infrastructure change would be "a new module implementing `Generator` plus a config value," not an endpoint rewrite. This ADR is the first time that seam is used for its stated purpose.

**Confirmed target hardware** (the developer machine driving this decision): MacBook Pro 16" 2019, 8-core Intel Core i9, Intel UHD Graphics 630 (integrated — no CUDA/Metal-compute-relevant GPU), 32GB RAM, macOS Tahoe. This is a **CPU-only inference** environment; the model choice below is made against that constraint, not against best-case GPU throughput.

This ADR does not propose replacing Gemini. It proposes adding a local option, selected by configuration, for use where Gemini's rate limit is actively the constraint (development, load/stress testing) while Gemini remains the default for normal use.

## Decision 1: Add `OllamaGenerator` as a second `Generator` implementation, selected via config — not a Gemini replacement

**Decision:** Implement `llm_client/ollama.py` with a class `OllamaGenerator(Generator)`. Which generator the app uses is controlled by a new `LLM_PROVIDER` setting (`gemini` | `ollama`), read by whatever factory function constructs the generator injected into `/chat` (`get_generator()` / `get_chat_generator` dependency). **Default remains `gemini`** — this is an opt-in local path, not a silent behavior change for existing deployments.

**Rationale:**

- Matches the exact pattern ADR-0001 Decision 2b anticipated: a new module implementing `Generator`, plus a config value. `api/main.py`, the prompt-building in `llm_client/context.py`, and the existing test suite (which already injects fake `Generator`s — see `tests/api/test_chat.py`, `tests/db/test_generation.py`) are untouched.
- Keeping Gemini as the default avoids conflating "we have a local fallback available" with "we've decided local is now the primary path" — that's a separate, larger decision (see Revisit triggers) that shouldn't be made implicitly as a side effect of solving a dev-environment rate-limit problem.
- A config flag (rather than, say, automatic failover from Gemini to Ollama on 429) keeps behavior deterministic and testable: which model answered a given question is never ambiguous, which matters for the generation-quality eval set ADR-0001 Decision 5 established.

## Decision 2: Model is `qwen3:8b`, served via Ollama

**Decision:** Use `qwen3:8b` (Apache 2.0, Q4_K_M quantization, Ollama's default tag) as the local model, run through Ollama rather than a raw `llama.cpp`/`vLLM` setup.

**Rationale:**

- **Instruction-following over the retrieved-context prompt is the property that matters** (same criterion ADR-0001 Decision 2a used to prefer Gemini 2.5 Flash over Flash-Lite) — not general world knowledge, which this system deliberately does not lean on. Qwen3 8B is currently a strong, well-regarded default in this size class specifically for grounded instruction-following.
- **Fits the confirmed hardware without headroom concerns.** At Q4_K_M the model needs roughly 5–6GB of RAM to load; with 32GB available and no GPU to provision for, there's no memory pressure running it alongside the existing FastAPI/Qdrant stack.
- **Apache 2.0 license** — no commercial-use ambiguity to track, unlike Llama's community license terms.
- **Ollama, not `vLLM`:** `vLLM`/production-grade serving targets throughput/batching/GPU concurrency this single-developer, CPU-only, non-production use case does not need. Ollama's setup cost (`brew install ollama`, `ollama pull qwen3:8b`) is proportionate to the actual problem being solved. This mirrors ADR-0001's own reasoning against a self-hosted model at prototype stage — the difference here is the operational complexity is now justified because it removes an active development blocker, not a hypothetical one.
- **Realistic expectations, stated explicitly so they aren't discovered mid-implementation:** CPU-only inference on this hardware is expected in the range of ~5–12 tokens/sec — noticeably slower than Gemini's API latency. Acceptable for a dev/stress-testing path; not proposed as a production substitute at this speed.

## Decision 3: Transport is Ollama's OpenAI-compatible HTTP endpoint, not the `ollama` Python package

**Decision:** `OllamaGenerator` calls `POST {OLLAMA_BASE_URL}/chat/completions` (default `OLLAMA_BASE_URL=http://localhost:11434/v1`) using the project's existing HTTP client library, rather than adding the `ollama` PyPI package as a dependency.

**Rationale:**

- Ollama exposes an OpenAI-compatible API by default; no functionality is lost by skipping the dedicated SDK, and it avoids adding a new hard dependency for what is, by Decision 1, an opt-in path — a `pip`-installed package that's only ever imported when `LLM_PROVIDER=ollama` still ships to every environment.
- Keeps `OllamaGenerator` structurally parallel to `GeminiGenerator` (both are thin adapters translating `generate(context, question) -> str` into a vendor-specific HTTP call), which keeps the `llm_client` package easy to reason about as it grows.

## Decision 4: Settings — `gemini_api_key` becomes conditionally required, not always required

**Decision:** Extend `LLMSettings` (`llm_client/settings.py`) with `llm_provider: Literal["gemini", "ollama"]` (default `"gemini"`), `ollama_base_url` (default `"http://localhost:11434/v1"`), `ollama_model` (default `"qwen3:8b"`), and `ollama_timeout_seconds` (default `60.0`, higher than Gemini's `30.0` given the CPU-inference latency profile from Decision 2). Change the existing `gemini_api_key` validator so it is only enforced when `llm_provider == "gemini"`.

**Rationale:**

- Today, `LLMSettings.must_not_be_empty` unconditionally requires `gemini_api_key`. Left as-is, a developer setting `LLM_PROVIDER=ollama` specifically to avoid touching Gemini would still be forced to supply a dummy Gemini API key for settings construction to succeed — an avoidable rough edge that undermines the point of adding a local path.
- Reuses the existing `Settings`/`lru_cache` pattern (ALE-72) rather than introducing a parallel settings mechanism for one provider.
- `ollama_timeout_seconds` is deliberately a separate field from `timeout_seconds` (Gemini's) rather than one shared value, because the two providers have materially different latency profiles on this hardware; collapsing them into one setting would force a bad default for one provider or the other.

## Decision 5: Map Ollama failure modes onto the existing exception contract

**Decision:** `OllamaGenerator` catches connection errors, timeouts, and non-2xx responses and re-raises them as the existing `GenerationUnavailableError` (`llm_client/exceptions.py`) — the same exception `GeminiGenerator` raises for upstream-down conditions. `GenerationRateLimitError` is not expected to be raised by `OllamaGenerator` under normal operation (a local daemon has no vendor-imposed request quota), but the exception class itself is not provider-specific, so no new exception type is introduced.

**Rationale:**

- ADR-0006 already wired `/chat` to translate `GenerationRateLimitError` → 429 and (per `tests/api/test_chat.py`) `GenerationUnavailableError` → 502. Reusing these means **zero changes to `api/main.py`'s error handling** when swapping providers — the entire point of Decision 2b in ADR-0001.
- "Ollama daemon not running" (a very likely local failure mode — nothing enforces `ollama serve` is up) should surface as the same clear 502 a developer already knows to expect from a Gemini outage, not a raw connection-refused traceback.

## Consequences

**Positive:**

- Removes Gemini's free-tier rate limit as a blocker for local development and load/stress testing entirely — no quota, no network dependency, no cost.
- No change to `/chat`, prompt construction, or existing tests; fully additive per the seam ADR-0001 built for this purpose.
- Establishes a real, working second `Generator` — the first proof that the "swap providers later" promise in ADR-0001 actually holds, not just an aspiration on paper.

**Negative / accepted risks:**

- CPU-only inference is measurably slower than Gemini's API (~5–12 tok/s expected) — acceptable for dev/testing, explicitly not proposed as a production path at this speed.
- Requires each contributor to install and run Ollama locally (`ollama serve` + `ollama pull qwen3:8b`, ~5–6GB download) — a new onboarding step, documented in README/CONTRIBUTING as part of ALE-101.
- Quality is expected to be close to, but not guaranteed identical to, Gemini 2.5 Flash on the grounding-fidelity criterion ADR-0001 Decision 2a prioritized. This is asserted, not yet measured — see Decision 5 in ADR-0001 (generation-quality eval set) for how this should be checked before `qwen3:8b` is trusted for anything beyond dev/testing.
- `LLM_PROVIDER=ollama` is a single-developer-machine convenience today; it is not a deployable configuration for shared/CI environments unless a containerized Ollama service is added later (out of scope here).

## Revisit triggers

- If the ADR-0001 Decision 5 generation-quality eval set is run against `qwen3:8b` and shows grounding failures beyond what's seen with Gemini, consider a larger local model (`qwen3:14b`) before abandoning the local path.
- If Ollama becomes convenient enough that there's an appetite to make it the **default** provider (not just an opt-in dev path), that is a bigger decision than this ADR makes and should be evaluated on its own, including the "no unstable free tier" property this ADR does not currently need to weigh.
- If this project needs to run in a shared/CI environment where a long-lived local Ollama daemon isn't available, revisit via a containerized Ollama service (e.g. a `docker-compose` entry) rather than assuming every environment has one running on `localhost:11434`.
- If GPU hardware becomes available to the team, the CPU-only constraint driving Decision 2's model-size choice goes away and larger/faster local models become viable — worth re-evaluating the model pick at that point, not before.

## Alternatives considered and rejected (for now)

- **`vLLM` or another production-grade serving stack** — rejected as disproportionate to a single-developer, CPU-only, non-production use case; Ollama's setup cost matches the actual problem being solved. Worth revisiting only if this becomes a shared/deployed local-inference service, not a dev convenience.
- **LM Studio** — a capable GUI-first alternative to Ollama, but Ollama's CLI/HTTP-first design fits a backend service being called programmatically better than a desktop app built around interactive chat.
- **Moving Gemini to its paid tier** — would remove the *unstable free-tier quota* problem but not the underlying goal (zero-cost, unlimited local testing), and introduces a real per-token cost during exactly the load-testing workloads that motivated this ADR in the first place. Still a valid option for *production* if/when this leaves prototype stage — see ADR-0001's own revisit triggers, which this ADR does not change.
- **`llama3.3:8b` / `phi4-mini` as the local model** — both viable; `llama3.3:8b` is a close second to `qwen3:8b` on instruction-following benchmarks, and `phi4-mini` would trade some quality for lower memory/faster CPU inference. Not chosen initially because nothing about the confirmed 32GB-RAM hardware requires the smaller/faster trade-off `phi4-mini` offers, and `qwen3:8b` is the more commonly recommended default in its class as of this writing. Easy to reconsider under Decision 1's config-driven design if evaluation says otherwise.
