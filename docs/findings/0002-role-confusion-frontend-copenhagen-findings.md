# ALE-151 Findings: Role-Confusion Regression — "frontend jobs in Copenhagen"

* **Ticket:** ALE-151
* **Related:** ALE-138 (manual review flagged frontend↔backend confusion), ALE-92 / ADR-0010 (keyword-precision gap — distinct failure mode), ALE-143 (hybrid-search verification)
* **Date:** 2026-07-14 (production observation); fixture codified 2026-07-15; ALE-143 re-check 2026-07-16
* **Status:** Still failing after ADR-0010 hybrid search — follow-up required

## Summary

Live production evidence (`POST /chat` against `JOBS_ON_THE_HUB`, 2026-07-14): querying **"frontend jobs in Copenhagen"** correctly declined to claim a match (no hallucination), but the sources shown were **Sales Development Representative**, **Country Manager**, and **Business Development Consultant** listings — none frontend-related — all scoring **0.855–0.860**, comfortably above `CHAT_SOURCE_MIN_SCORE` (0.85).

The generator behaved correctly; the defect is retrieval surfacing irrelevant noise above the similarity floor.

## Fixture regression case

Codified in `tests/fixtures/golden_queries.json` under `role_confusion_cases`:

| Field | Value |
|---|---|
| Query | `frontend jobs in Copenhagen` |
| Expected winner | `cph001` — Frontend Developer @ Copenhagen Digital (Copenhagen, Denmark) |
| Confusers | `cph002` — Sales Development Representative; `cph003` — Business Development Consultant (both Copenhagen) |
| Score floor | `0.85` (production `CHAT_SOURCE_MIN_SCORE`) |

Test: `test_role_confusion_cases` in `tests/db/test_retrieval.py` (remains `xfail(strict=True)` after ALE-143).

Observed fixture scores (E5, dense-only, 2026-07-15):

| Rank | job_id | Title | Score |
|---|---|---|---|
| 1 | cph001 | Frontend Developer | 0.917 |
| 2 | jkl012 | Frontend Developer (Stockholm) | 0.854 |
| 3 | cph002 | Sales Development Representative | **0.852** |
| 4 | pqr678 | Backend Developer (Oslo) | 0.839 |
| 5 | cph003 | Business Development Consultant | 0.839 |

Failure mode under dense-only retrieval: confuser `cph002` survives `CHAT_SOURCE_MIN_SCORE` (0.85) and would appear in `/chat` sources despite being role-irrelevant — matching the production observation (confusers at 0.855–0.860 above floor).

Assertions:

1. Expected frontend job appears in top-k.
2. Expected job score ≥ `CHAT_SOURCE_MIN_SCORE`.
3. Each confuser ranks below the expected job and scores below the floor.

## ALE-143 verification result (2026-07-16)

Re-ran `test_role_confusion_cases` against fused dense+BM25 RRF retrieval (ADR-0010 / ALE-143) with dense cosine attached for the floor (Decision 7).

**Still fails.** Confuser `cph002` still scores ≈ **0.852** on the companion dense leg — above `CHAT_SOURCE_MIN_SCORE=0.85`. Hybrid search improves keyword/tech-stack ranking (`test_tech_stack_adversarial_cases` now passes) but does not suppress role-confused dense neighbors that share location and generic job-market language.

This confirms the pre-ALE-143 expectation: role/topic confusion is a **dense-embedding semantic proximity** problem, not the keyword-density gap ADR-0010 targeted.

## Follow-up directions (not solved by ALE-143)

- **Role-aware payload filtering** — filter or boost by `job_role` / title when the query encodes an explicit role (extends ADR-0002's categorical-signal approach).
- **Query intent parsing** — extract role + location facets before retrieval and apply structured filters.
- **Re-ranking with role classifier** — lightweight title/role match pass after dense retrieval.

Tracked as an ADR-0010 revisit trigger; requires a dedicated follow-up ticket/ADR.
