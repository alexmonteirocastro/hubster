# Product Vision

*Status: Accepted — companion to `docs/adr/`; see [ADR-0001](adr/0001-llm-provider-strategy.md) and [ADR-0002](adr/0002-retrieval-filtering-strategy.md) for the technical decisions this vision motivates.*

## 1. Problem

The Hub is, on its own terms, a strong job board — clean layout, well-structured listings, clearly a cut above the general-purpose boards (LinkedIn chief among them). But like every job board, it is fundamentally a **filtering** interface: country, role, remote/on-site, seniority. Filters can only ever answer the questions the UI anticipated in advance.

That's a real ceiling. A candidate has to already know the right keyword to find the right job — and most of the value in a listing (the specific tech stack, what's a hard requirement vs. a nice-to-have, what the team actually does day to day, whether the role is a good stepping stone toward a longer-term goal) is locked inside free text that no filter can reach. The result: relevant opportunities get missed not because they don't exist, but because the candidate didn't know to search for them, and candidates wade through listings that don't fit them at all because filters are coarse.

## 2. Who this is for

The job seeker — specifically, someone applying to Nordic/European startups who wants to search by what they actually want ("interesting," "in-demand," "a good fit for my background") rather than by the handful of dimensions a filter form exposes. This is deliberately the candidate side of the marketplace, not the startup/recruiter side — The Hub already serves that side well, and it's a different product with a different set of problems.

## 3. Differentiation thesis

**Reasoning over the corpus, not just matching against it.**

The tempting, smaller version of this product is "the same filters, but as a chat window" — e.g. "show me frontend jobs in Sweden." That's a real improvement in ergonomics, but it's not the point. The point is questions a filter can never be phrased to answer, because the answer requires connecting information *across* listings, or connecting listings to something specific about the candidate:

* "What skills are most in-demand for a founding engineer in the Nordics?"
* "I'm an engineer with 5 years of Python experience — what's potentially interesting for me in Finland?"
* "If I want to become a designer at a Swedish startup, what should I learn?"
* "Based on what company XYZ is looking for, how should I structure my cover letter?"

None of these map onto a filter. All of them are answerable, in principle, by an LLM that can both retrieve the right listings and reason over what it retrieves — which is the actual bet this project is making.

## 4. Capability tiers

This is the most important section for engineering purposes: these four questions are not one feature, they're at least three or four, and they don't all need the same architecture. Treating them as one undifferentiated "reasoning RAG" feature is how a roadmap gets vague. Naming the tiers is what turns the vision into a sequenced set of ADRs and tickets.

| Tier | Example | What it needs | Status |
| -- | -- | -- | -- |
| **1. Filtered lookup** | "Frontend jobs in Sweden" | Top-k dense retrieval + structured payload filter | Built ([ADR-0002](adr/0002-retrieval-filtering-strategy.md)) |
| **2. Single-listing grounded Q&A** | "What does this team do?" | Top-k retrieval, answer grounded in one/few docs, decline if unsupported | Built ([ADR-0001](adr/0001-llm-provider-strategy.md)) |
| **3. Corpus-level aggregation** | "What skills are most in-demand for a founding engineer in the Nordics?" | Reasoning across *many or most* listings, not a top-5 window — likely needs a pre-aggregated layer (e.g. skill/keyword frequency computed at ingestion time) that the LLM reasons over, rather than raw retrieval over `document_text` | **Not built — current retrieval architecture cannot see enough of the corpus at once to answer this class of question at all** |
| **4. Personalized matching + advice** | "5 years Python, what's interesting in Finland?" | A candidate profile (experience, stack, preferences) held across turns and matched against many listings | Not built — `/chat` is deliberately single-turn/stateless today ([ADR-0001](adr/0001-llm-provider-strategy.md) Decision 4) |
| **5. Generative drafting from one job + one candidate** | "Help me write a cover letter for company XYZ" | Grounded generation from a specific listing *plus* candidate-supplied material (CV) | Not built — needs CV ingestion |

Tier 3 deserves its own callout: it is not "tier 1 with a bigger `limit`." Five nearest-neighbor jobs cannot tell you what's most in-demand across the Nordics — the honest answer requires either a much wider retrieval window with real aggregation, or a separate pre-computed structure built during ingestion (e.g. extracted-skill frequency counts). This needs its own architectural decision (its own ADR) when it's scheduled — it should not be quietly bolted onto the existing single-document RAG path.

For role-shaped concepts like "founding engineer," the corpus usually surfaces them directly in titles and descriptions — keyword/title matching is the likely extraction path, not a separate NER or LLM-at-ingestion step. "In-demand skills" is a different problem: a corpus-level overview (e.g. "many companies hiring frontend engineers ask for X, Y, Z") that no top-k retrieval window can honestly answer. How to derive that reliably is still unclear and needs further discovery before tier 3 is scheduled.

## 5. Phased roadmap

**Phase 1 — Job search copilot (current focus).** Solidify tiers 1–2 (already the bulk of the work done to date, per ADR-0001/0002), and begin tier 3 (corpus-level aggregation) as the first genuinely new capability. This phase should feel like a substantially better version of searching The Hub — still anonymous, still no persistent user, but able to answer questions no filter could.

**Phase 2 — Candidate profile.** Introduce a lightweight, **session-scoped** candidate profile (experience, stack, target countries/roles) — either elicited conversationally or entered directly — enabling tier 4. The profile does not persist across sessions in this phase; cross-session persistence may come later once the privacy/retention model is explicit. This is the point at which `/chat` statelessness (ADR-0001 Decision 4) needs to be revisited; that decision was correct for phase 1 and explicitly flagged its own revisit trigger ("if `/chat` gains multi-turn/session support").

**Phase 3 — Application materials.** CV file ingestion (PDF/DOCX upload and parsing — not structured form input) and tier 5: grounded, job-specific drafting (cover letters, CV tailoring suggestions) that combines a specific listing with the candidate's own material. This is the most sensitive tier from a trust standpoint — see Section 7.

## 6. Non-goals (for the current prototype stage)

Explicitly out of scope right now, so scope creep has something to point at:

* Multi-turn conversational memory (tier 4/5 prerequisite, not yet built)
* CV/resume ingestion or storage
* Any corpus-level aggregation feature (tier 3) beyond the initial spike
* Notifications, alerts, or any proactive/async behavior
* Recruiter/startup-facing features of any kind
* Multi-language generation (the corpus already includes non-English listings, see ADR-0002's negative/accepted risks; out of scope for now)

## 7. Trust bar — what makes an answer "good enough to act on"

The existing anti-hallucination stance ([ADR-0001](adr/0001-llm-provider-strategy.md) Decision 3: decline rather than fabricate) is the right foundation and should extend to every tier, not just tier 1–2:

* A tier-1/2 answer must never state a match that isn't actually grounded in a retrieved listing (already the case).
* A tier-3 aggregation answer must be honest about *how many* listings it's actually drawing from, not imply corpus-wide authority from a small sample.
* A tier-4/5 answer must never invent a qualification, skill, or experience the candidate didn't actually provide — the failure mode here is more personal and higher-stakes than a bad job match: fabricated advice about a real person's career.

The bar throughout: it's fine for the system to say "I don't have enough information to answer that well," and it is never fine for it to sound confident while being wrong.

## 8. Scaling posture

This project is explicitly built to survive going from a personal learning project to something with real users — the same framing already used to justify paying small costs early ([ADR-0002](adr/0002-retrieval-filtering-strategy.md)'s proactive payload indexing, [ADR-0005](adr/0005-visual-design-tokens-for-the-chat-ui.md)'s token system). Things to keep in mind as this scales past prototype:

* Real users means real Gemini API costs and rate limits at volume (already flagged in ADR-0001's risk section, partially addressed by ALE-87).
* A candidate profile (Phase 2) introduces the project's first real personal data, which changes the privacy/retention conversation entirely.
* A tier-3 aggregation layer, once built, becomes a second thing that needs to stay in sync with ingestion, not just the vector index.

## Open questions

* **Corpus-level "in-demand skills" (tier 3):** How to derive a trustworthy high-level overview — e.g. "many companies hiring frontend engineers in the Nordics ask for X, Y, Z" — from the full listing corpus. Pre-aggregated skill frequencies at ingestion, wider retrieval plus summarization, or something else entirely: unclear until a dedicated discovery pass. Schedule tier 3 only after that.
