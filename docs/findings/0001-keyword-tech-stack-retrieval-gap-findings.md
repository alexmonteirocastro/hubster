# ALE-92 Spike Findings: Keyword/Tech-Stack Retrieval Precision Gap

* **Ticket:** ALE-92
* **Related:** ADR-0002 (Retrieval Filtering Strategy) — this spike exists because of its own documented revisit trigger; ADR-0010 (`docs/adr/0010-sparse-bm25-hybrid-search.md`) — decision record based on this evidence
* **Date:** 2026-07-11
* **Status:** Spike complete — recommendation below

## Summary

**Recommendation: GO.** Evidence supports proceeding to a new ADR evaluating sparse/BM25 hybrid search, per ADR-0002's revisit trigger. Of 8 tagged tech-stack queries tested against the production Qdrant collection, 3 (~38%) show a confirmed keyword-precision failure — the correct or most-relevant job scores at or below a semantically-similar but tech-stack-irrelevant competitor, with a score margin under 0.05. This clears the ≥25% decision-rule threshold set when this spike was scoped.

## Methodology note (deviation from planned approach)

The original spike scope called for running the existing golden-set (`tests/fixtures/golden_queries.json`) plus a scripted BM25 prototype comparison. In practice, the golden set only contains 5 queries with no adversarial/confusable job pairs, and reseeding a dev collection was avoidable since the existing populated collection could be queried read-only. What was actually done instead:

1. Ran 8 tech-stack-specific natural-language queries directly against the existing (already-populated) production Qdrant collection via `query_jobs_in_qdrant`, read-only, no reindexing.
2. For each query, inspected the top-5 results and their score margins.
3. Where a margin was tight (<0.05) or a ranking looked surprising, pulled the full `document_text` for the competing jobs via `client.scroll()` with a payload filter, and manually verified whether the top-ranked job was actually more relevant to the query than the runner-up.
4. Classified each query as **problematic** (confirmed keyword-precision failure) or **not problematic** (tight margin, but runner-up genuinely relevant, or correct job legitimately ranked highest) based on that manual read — not an automated substring/BM25 check.

This is a lighter-weight, manual version of the planned methodology. It trades reproducibility (no fixed golden-set, no automated BM25 comparison yet) for speed and realism (real production listings, not constructed fixtures). If the recommendation below leads to an ADR and implementation, that follow-up work should include building a proper repeatable eval — see "Related finding" below.

## Findings by query

| # | Query | Top result | Runner-up (or key competitor) | Margin | Verdict |
|---|---|---|---|---|---|
| 1 | Python backend developer FastAPI | 0.693 — Backend Developer @ Framna | 0.676 — Backend & Platform Engineer @ Learnster | 0.017 | **Problematic** |
| 2 | React frontend engineer | 0.828 — Frontend Developer (React) @ Framna | 0.759 — Backend engineer @ Carla | 0.069 | Not problematic |
| 3 | Kubernetes DevOps engineer | 0.750 — DevOps Engineer @ Framna | 0.747 — Platform Engineer (Kubernetes) @ Six Robotics | 0.003 | **Problematic** (with confound, see below) |
| 4 | PostgreSQL database engineer | 0.737 — AI Data Engineer @ Againta | 0.711 — Data Infrastructure Eng @ Coragrid | 0.026 | Not problematic (corrected) |
| 5 | TypeScript developer | 0.708 — Backend Dev (TS+Node) @ Framna | 0.705 — Fullstack Dev (TypeScript) @ COODY | 0.003 | Not problematic |
| 6 | Go backend engineer | 0.809 — Backend & Platform Eng @ Learnster | 0.802 — Backend engineer @ Carla | 0.007 | **Problematic** |
| 7 | Terraform infrastructure as code | 0.735 — Senior Software Engineer @ Spoor | 0.712 — Backend & Platform Eng @ Learnster (correct match) | 0.023 | **Problematic** (cleanest case) |
| 8 | SQL data analyst | 0.720 — AI Data Engineer @ Againta | 0.675 — Finance Data Analyst @ Lunar | — | Not problematic |

**3 of 8 (37.5%) confirmed problematic** — above the 25% go/no-go threshold set in ALE-92's scoping.

## Detailed cases: confirmed problematic

### Case 1 — Python/FastAPI (Learnster vs. Framna)

Query: *"Python backend developer FastAPI"*

- **Framna — Backend Developer (0.693, ranked #1):** Python appears once, in a bullet list ("PHP, Python"). The role's stated primary stack is explicitly PHP and Node.js ("You will work hands-on with PHP and Node.js").
- **Learnster — Backend & Platform Engineer (0.676, ranked #2):** Python named twice, paired with a specific framework — "Build backend services and APIs using Python and Django" and "Proven experience in backend engineering with Python, ideally Django."

By any reasonable reading, Learnster is the stronger Python match, yet it scored lower. Dense embeddings are not distinguishing "Python as one line in a broader stack list" from "Python as a stated core requirement with a named framework."

### Case 2 — Go backend engineer (Learnster vs. Carla)

Query: *"Go backend engineer"*

- **Learnster (0.809, ranked #1):** No mention of Go anywhere in the posting — its stack is Python/Django.
- **Carla — Backend engineer (0.802, ranked #2):** Explicitly Go-primary — "primarily in Go for our backend" and "Strong hands-on experience with Go."
- **Monil AS — Backend Developer (Go) (0.783, ranked #5):** Has "(Go)" literally in the job title, yet ranks below both of the above.

This is the strongest unconfounded case: the correct answer doesn't even rank first, and a title-level exact match ("(Go)") still loses to two non-Go roles.

### Case 3 — Terraform infrastructure as code (Spoor vs. Learnster)

Query: *"Terraform infrastructure as code engineer"*

- **Spoor — Senior Software Engineer (0.735, ranked #1):** No mention of Terraform, IaC, or Ansible anywhere in the posting.
- **Acembee — Full-stack developer (0.720, ranked #2):** Mentions Terraform only as a minor bonus — "Bonus points for experience with Traefik, Ansible, Terraform..."
- **Learnster (0.712, ranked #4):** States Terraform as an explicit requirement — "Infrastructure as Code: Proficiency with Terraform, AWS CloudFormation, or similar tools."

The job that treats Terraform as a genuine requirement ranks behind one job that doesn't mention it at all. Cleanest case in the set — no multilingual, title-overlap, or "both jobs are legitimately relevant" ambiguity.

## Notable case with a confound (not counted toward the tally as "clean")

### Kubernetes DevOps (Six Robotics vs. Framna)

Query: *"Kubernetes DevOps engineer"*

- **Framna — DevOps Engineer (0.750, ranked #1):** Job description is written almost entirely in Dutch. Kubernetes is mentioned once, in an English-language tech-stack bullet ("Containers: Docker, Kubernetes"). Title is a near-verbatim lexical match to the query ("DevOps Engineer").
- **Six Robotics — Senior Platform Engineer (Kubernetes) (0.747, ranked #2):** Substantively, deeply about Kubernetes — the role is to design and build a self-hosted Kubernetes cluster from scratch, with cluster-architecture-level experience as an explicit requirement.

This is still counted as problematic (Six Robotics is clearly the better match and loses), but the likely mechanism is different from cases 1–3: this looks more like **title lexical overlap** dominating the score, possibly compounded by the embedding model down-weighting the largely non-English body text, rather than pure keyword-density blindness. Worth noting for the ADR: hybrid/BM25 search might not cleanly fix this specific sub-case, since a sparse keyword match could also favor exact title-phrase overlap over a semantically-stronger but lexically-different title. May need separate handling (e.g. normalizing or flagging non-English postings) that would be out of scope for a hybrid-search ADR alone.

## Findings that turned out NOT to be problems (worth logging honestly)

- **React frontend / Carla:** Runner-up (Carla) genuinely mentions React and TypeScript — a legitimately close second choice, not a retrieval failure.
- **PostgreSQL / Againta vs. Coragrid:** Both postings explicitly and prominently require PostgreSQL. A tight margin between two genuinely relevant jobs is correct behavior, not a bug — initially misclassified as problematic before body-text verification corrected it.
- **TypeScript / Framna vs. COODY:** Both top-2 results explicitly require TypeScript.
- **SQL data analyst / Lunar ranking lowest:** Lunar's posting does mention SQL, but as one supporting skill among several finance/domain-focused requirements — its low rank relative to more SQL/data-centric roles looks like correct behavior, not a failure.

These are included deliberately: not every tight margin is a bug, and claiming otherwise would undermine the credibility of the "problematic" cases above.

## Related finding: this spike is itself an argument for a repeatable eval process

Running this investigation required manually inspecting `document_text` for 10+ jobs by hand, one at a time, via ad hoc Qdrant scroll queries. There is currently no automated way to check "is the correct/most-relevant job actually ranking highly for a given tech-stack query" beyond the 5-query golden set, which has no adversarial confusable pairs built in. This isn't a new discovery — "setting up human evaluation systems" is already a stated Phase 1 near-term priority — but this spike is concrete evidence for *why* it matters: several of the failures found here (Learnster/Framna, Six Robotics/Framna) are exactly the kind of near-miss a small, deliberately-constructed adversarial golden set would catch automatically and repeatably, instead of waiting for a real user transcript to surface it.

## Recommendation

**Go.** Proceed to a new ADR (e.g. ADR-0010) evaluating sparse/BM25 hybrid search as a complement to the existing dense-vector retrieval, per ADR-0002's revisit trigger — now recorded in `docs/adr/0010-sparse-bm25-hybrid-search.md`. The ADR should:

- Reference cases 1–3 above as concrete, verified evidence (not the single original anecdotal transcript).
- Explicitly address the Kubernetes/Six Robotics confound — hybrid search may not resolve title-lexical-overlap or multilingual-content cases, and that limitation should be scoped honestly rather than implied away.
- Consider whether a proper automated eval (expanded golden set with adversarial pairs, or a BM25 prototype comparison script) should be built alongside or before the hybrid-search implementation, so the fix's actual impact can be measured against a baseline rather than judged anecdotally again.
