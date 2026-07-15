# ALE-151 Findings: Role-Confusion Regression — "frontend jobs in Copenhagen"

* **Ticket:** ALE-151
* **Related:** ALE-138 (manual review flagged frontend↔backend confusion), ALE-92 / ADR-0010 (keyword-precision gap — distinct failure mode), ALE-143 (hybrid-search fix candidate)
* **Date:** 2026-07-14 (production observation); fixture codified 2026-07-15
* **Status:** Regression case added; awaiting ALE-143 verification

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

Test: `test_role_confusion_cases` in `tests/db/test_retrieval.py` (marked `xfail` until ALE-143 ships and is re-evaluated).

Observed fixture scores (E5, dense-only, 2026-07-15):

| Rank | job_id | Title | Score |
|---|---|---|---|
| 1 | cph001 | Frontend Developer | 0.917 |
| 2 | jkl012 | Frontend Developer (Stockholm) | 0.854 |
| 3 | cph002 | Sales Development Representative | **0.852** |
| 4 | pqr678 | Backend Developer (Oslo) | 0.839 |
| 5 | cph003 | Business Development Consultant | 0.839 |

Failure mode under current retrieval: confuser `cph002` survives `CHAT_SOURCE_MIN_SCORE` (0.85) and would appear in `/chat` sources despite being role-irrelevant — matching the production observation (confusers at 0.855–0.860 above floor).

Assertions:

1. Expected frontend job appears in top-k.
2. Expected job score ≥ `CHAT_SOURCE_MIN_SCORE`.
3. Each confuser ranks below the expected job and scores below the floor.

## ALE-143 verification plan

ADR-0010 hybrid search targets **keyword/tech-stack precision** (Python/FastAPI, Go, Terraform), not role/topic confusion. Do not assume ALE-143 fixes this case automatically.

After ALE-143 merges:

1. Re-run `uv run pytest -v -m retrieval tests/db/test_retrieval.py::test_role_confusion_cases` **without** the `xfail` marker.
2. Document pass or fail in this file and in ADR-0010 revisit triggers.

## If still failing post-hybrid-search

Role confusion is likely a **dense-embedding semantic proximity** problem (shared "Copenhagen startup job" context) rather than missing keyword overlap. Hybrid BM25 may not disambiguate "frontend" from "sales/BD" when confusers share location and generic job-market language.

Likely fix directions (not scoped here — for a future ADR/ticket if ALE-143 does not pass):

- **Role-aware payload filtering** — filter or boost by `job_role` / title when the query encodes an explicit role (extends ADR-0002's categorical-signal approach).
- **Query intent parsing** — extract role + location facets before retrieval and apply structured filters.
- **Re-ranking with role classifier** — lightweight title/role match pass after dense retrieval.

Until verified, tracked as an ADR-0010 revisit trigger (see `docs/adr/0010-sparse-bm25-hybrid-search.md`).
