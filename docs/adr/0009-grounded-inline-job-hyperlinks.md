# ADR-0009: Grounded Inline Job Hyperlinks in Generated Answers

* **Status:** Accepted
* **Date:** 2026-07-09
* **Related:** ALE-105 (implementation), ALE-104 (markdown rendering — direct dependency), ADR-0001 Decision 2b/3/5 (`Generator` interface, anti-hallucination guardrail, generation-quality eval set), ADR-0004 Decision 4 (sources rendering), ADR-0005 (visual tokens), ADR-0007 (`LLM_PROVIDER=stub` for local UI testing)

## Context

`/chat` today produces two disconnected things: a generated answer (`ChatResponse.answer`, plain prose — soon markdown per ALE-104) and a separate `sources` list, each already carrying a computed `job_url` (`ChatSource.job_url`, via `the_hub_client.utils.build_job_url`), rendered as a card block below the answer (per ADR-0004 Decision 4, ADR-0005 Decision 5). A real transcript makes the gap visible: the answer reads *"Senior Backend Engineer at Lunar (Aarhus)"* with no link at all — the only way to actually reach that listing is to scroll to the separate card below and match it up manually. This reads as a plain search-results aggregator rather than an assistant giving a real answer, and doesn't differentiate the product from The Hub's own search.

**Confirmed root cause, not an assumption:** `llm_client/context.py`'s `format_job_context` builds each job block as `--- Job N (id: {job_url_identifier}) ---` followed by `document_text` — it never includes the actual clickable URL. The model has no way to emit a correct link even if it wanted to, because it was never given one.

**Why this isn't solvable purely client-side:** matching freeform model prose ("GoWish is looking for a backend engineer") against a list of job titles to insert a link after the fact is a fuzzy-text-matching problem — paraphrasing, multiple similarly-worded sources, or partial title overlap can all produce a link to the *wrong* job, which is worse than no link. This is the same category of probabilistic patch ADR-0002 and ADR-0004 Decision 4 already rejected in favor of structural guarantees; the same reasoning applies here.

## Decision 1: Pass the real job URL into the generation context, per listing

**Decision:** Extend `format_job_context` (`llm_client/context.py`) to include each job's actual URL — computed via the existing `build_job_url(job_id)` utility (`the_hub_client/utils.py`), the same function `ChatSource.job_url` already uses — alongside the existing `id` label in each job block.

**Rationale:**

- Reuses the single existing source of truth for job-URL formatting (`build_job_url`) rather than introducing a second way to construct the same URL. Matches the project's established "isolate the thing that will change behind one seam" pattern, already applied to Hub API interaction (`the_hub_client`) and LLM provider selection (`llm_client.base.Generator`).
- This is additive to the existing block format — no change to what `document_text` contains, no re-embedding, no Qdrant schema change.

## Decision 2: The system instruction requires markdown links to the exact given URLs — never invented

**Decision:** Extend `_SYSTEM_INSTRUCTION` (`llm_client/context.py`) to instruct the model: when referencing a specific job in the answer, format it as a markdown link using the exact URL provided for that listing; never invent, alter, or guess a URL; only link jobs that appear in the current context.

**Rationale:**

- This is a direct extension of ADR-0001 Decision 3's anti-hallucination guardrail — that guardrail already established "never state a match that isn't grounded in retrieved context"; this adds "never emit a URL that wasn't actually given," the same category of guarantee applied to a new output shape (links instead of just job facts).
- Prompting alone is a strong signal but — per ADR-0001 Decision 3's own reasoning — "helps, but is not a guarantee." This decision pairs with Decision 4 below rather than resting on prompt compliance alone.

## Decision 3: The change lives in shared, provider-agnostic prompt-building code

**Decision:** Both changes (Decisions 1 and 2) live entirely in `llm_client/context.py` (`format_job_context`, `build_generation_prompt`, `_SYSTEM_INSTRUCTION`) — code shared by every `Generator` implementation, upstream of `Generator.generate(context, question)`. No per-provider special-casing.

**Rationale:**

- Matches ADR-0001 Decision 2b's provider-agnostic seam directly: `GeminiGenerator` today, and `OllamaGenerator` per ALE-101 tomorrow, both receive the same already-augmented `context` string and the same instruction — link-grounding behavior isn't something either `Generator` implementation needs to know about or duplicate.
- Keeps this decision fully independent of ALE-101 (Ollama) — same reasoning ALE-103's conversation-memory spike used to explicitly decouple itself from the provider choice.

## Decision 4: Extend the generation-quality eval set with a structural link-fidelity check

**Decision:** Add a check to the generation-quality eval set (ADR-0001 Decision 5): for each evaluated answer, extract all markdown-link URLs and assert every one exactly matches a `job_url` present in that turn's retrieved sources. No URL outside that set is acceptable.

**Rationale:**

- Same logic as ADR-0001 Decision 3 applied one layer further: a structural, deterministically-testable guarantee is stronger than trusting prompt compliance to hold indefinitely across model or provider changes (including a future Ollama/`qwen3:8b` path, per ALE-101/ADR-0007, where instruction-following fidelity is an explicitly open, unmeasured question).
- Cheap to implement: markdown link extraction is a simple regex/parse over the model's own output, no new infrastructure.

## Decision 5: Restyle — don't remove — the existing sources list

**Decision:** `ChatResponse.sources` and its computed `job_url` are unchanged — the backend contract stays exactly as-is. Client-side, restyle the existing sources block (`SourceList`/`ChatMessage`) from the current full-size card list into a smaller, secondary reference strip (e.g. compact chips: title + score, still linking out), rendered below the now-inline-linked answer rather than competing with it visually.

**Debug sources presentation:** When `VITE_SHOW_DEBUG_SOURCES=true` (frontend build-time env var, documented in `frontend/.env.example`), render the **current full-size** `SourceList` card layout — title, metadata, and **similarity score per source** — instead of the compact production strip. Default is off (`false` or unset): the compact strip is the normal UX. This flag is explicit and opt-in; the UI does **not** infer debug mode from `import.meta.env.DEV`, `LLM_PROVIDER=stub`, or any other ambient signal — avoiding accidental verbose UI in a dev build pointed at production, or a production build that happens to use stub locally.

**Rationale:**

- Directly answers the ask: keep the backend response (and its transparency/debuggability value — full metadata, scores) exactly as it is; only the client-side presentation changes.
- Necessary as a safety net, not just a stylistic choice: Decision 2's instruction depends on model compliance, which isn't guaranteed to be perfect (see Consequences). The sources list remains the complete, guaranteed-accurate reference even on a turn where the model's prose under-links or paraphrases past a job without linking it.
- Consistent with ADR-0004 Decision 4's principle (render what the API returns, don't invent client-side relevance logic) and ADR-0005's token system (reuses `--shadow-card`, just a smaller footprint) — a restyle, not a new rendering philosophy.
- An explicit `VITE_SHOW_DEBUG_SOURCES` flag preserves the retrieval-debugging workflow ADR-0001 Decision 5 depends on (scores and full source metadata visible when you need them) without coupling presentation to environment heuristics. Pair with `LLM_PROVIDER=stub` (ADR-0007) when iterating on UI — stub for instant answers, debug sources for retrieval inspection — but each concern stays independently configurable.

## Consequences

**Positive:**

- Answers read as a differentiated, human-feeling assistant response instead of a search-aggregator dump — the stated product goal.
- The link-grounding guarantee is structural and testable (Decision 4), consistent with how every other correctness property in this system is handled, not a one-off trust-the-prompt fix.
- No backend/API contract change — `ChatResponse` shape is untouched, so this is fully additive from the frontend's perspective once ALE-104 lands.
- Dev/test workflow: set `VITE_SHOW_DEBUG_SOURCES=true` to keep the full scored sources list when inspecting retrieval quality, score floors (ADR-0002 Decision 4), or link-fidelity (Decision 4) — without shipping that verbose UI by default.

**Negative / accepted risks:**

- Model instruction-following isn't perfect: a given answer may still mention a job without linking it, or link some jobs but not others. This is a UX shortfall, not a correctness bug — Decision 4's eval check only catches a *wrong or fabricated* URL, not an *under-linked* answer, and Decision 5's retained sources list is the accepted mitigation.
- Slightly longer prompts (one URL per job block) — negligible token-cost impact given current job-count-per-request (`ChatRequest.limit`, default 5, max 50).
- This decision's assumed reliability needs separate re-validation once ALE-101 (Ollama/`qwen3:8b`) actually ships — the same "measure, don't assume, instruction-following quality" caveat ADR-0007 already flagged for that provider applies here too, for this specific behavior.

## Revisit triggers

- If real usage shows the model frequently omitting or misapplying links despite Decision 2's instruction, consider a structured-output approach (model returns explicit text-span/job-ID pairs, client renders links from confirmed IDs only) — a stronger but meaningfully more complex option, not adopted now because the simpler prompt-level instruction hasn't yet been shown to be insufficient.
- If ALE-101's Ollama path shows materially worse link fidelity than Gemini, feed that into ADR-0007's own revisit trigger (generation-quality eval set results) rather than treating it as a new, separate problem.
- If user feedback (once this ships) shows the retained sources strip (Decision 5) is redundant rather than a useful safety net, that's a separate follow-up decision to remove it entirely — not assumed here.

## Alternatives considered and rejected (for now)

- **Client-side fuzzy text-matching of job titles within the answer** — rejected: no reliable anchor between free-form model prose and a specific source without the model itself referencing an ID/URL; risks confidently linking the wrong job, worse than no link at all.
- **Removing the sources block entirely, relying only on inline links** — rejected for now: inline-link coverage depends on imperfect model compliance (see Consequences); the sources list is the accepted safety net until link fidelity is actually measured in practice.
- **Structured output (model returns JSON spans + job_id, links rendered purely from confirmed IDs)** — more robust in principle, but real added complexity (schema per provider, structured-output parsing) for a benefit not yet shown necessary. A markdown-link instruction is the proportionate first attempt, consistent with ADR-0001's repeated "don't pay for capability the current evidence doesn't call for" reasoning.
