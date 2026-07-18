# ALE-141 Spike Findings: E5 Truncation vs Retrieval-Precision Failures

* **Ticket:** ALE-141
* **Related:** ALE-92 / [`docs/findings/0001-keyword-tech-stack-retrieval-gap-findings.md`](0001-keyword-tech-stack-retrieval-gap-findings.md); ALE-138 (Linear findings); ALE-140 (`scripts/check_e5_document_token_lengths.py`); ADR-0014; ADR-0010; ADR-0002
* **Date:** 2026-07-18
* **Status:** Spike complete — recommendation below

## Summary

**Recommendation: NO-GO.** Dense E5 truncation at 512 tokens is real and nearly corpus-wide (confirmed earlier by ALE-140: ~99% of points exceed the window), and a broader sample shows tech-stack keywords often first appear *past* that cutoff. But for the specific ALE-92 better-match jobs that dense retrieval failed to rank correctly, the distinguishing keywords sit **inside** the first 512 tokens. Truncation therefore does **not** explain those documented precision failures — the model already saw the disambiguating signal and still ranked the wrong job higher.

Locked decision rule: GO only if ≥50% of unique better-match jobs have distinguishing keyword(s) after token 512 **and** broader-sample tech-stack medians > 512. Result: **0/2 (0%)** better-match jobs past cutoff (need ≥50%), even though broader stack medians *do* exceed 512. Gate fails → NO-GO.

## Methodology

Read-only scroll of production `JOBS_ON_THE_HUB` (**992** points with `document_text`), 2026-07-18. Tokenized with `intfloat/multilingual-e5-small` using `passage: ` + stored text (Qdrant Cloud Inference upsert behavior — same convention as ALE-140).

1. **Targeted pass** — resolve ALE-92 / ALE-138 failure jobs by company + title substring; for each distinguishing keyword report first-match token offset, section (`title` / `company` / `company_description` / `job_description`), and before/after 512.
2. **Broader sample** — 150 randomly sampled jobs (seed 42); distribution of first-occurrence offsets for role and tech-stack keywords; token offset where `Job Description:` begins.
3. **Geo control** — ALE-138 Stockholm→Spain and Germany→Netherlands cases; confirm `Country` / `location` are payload-only (ADR-0002) and do not count toward the GO tally.

Script: `scripts/analyze_e5_truncation_signal_positions.py` (re-runnable).

## Targeted results (ALE-92 better matches)

Unique better-match jobs with at least one found keyword (eligible for the ≥50% rule):

| Job | Distinguishing keywords vs 512 | Verdict |
|---|---|---|
| Learnster — Backend & Platform Engineer (1,102 tokens) | Python@399, Django@405, Terraform@477, IaC@467, CloudFormation@482 — all **BEFORE** | Inside window |
| Carla — Backend engineer (1,131 tokens) | Go@264 — **BEFORE** | Inside window |

Six Robotics was targeted as the Kubernetes better match, but the current collection hit is `Senior Data Platform Engineer` with **no** `Kubernetes` string in `document_text` — treated as rotated / ineligible (not counted in the 0/2 denominator). Acembee (Terraform bonus) is missing from the collection entirely.

### Confuser / wrong-top jobs (context)

| Job | Notable offsets | Notes |
|---|---|---|
| Framna Backend | Python@499 **BEFORE**; PHP@343, Node@345 | Light Python mention still inside window |
| Framna DevOps | Kubernetes@506 **BEFORE** (barely) | Title-lexical confound from ALE-92 still stands |
| Spoor Senior SWE | Terraform / IaC / Ansible = NOT_FOUND | Wrong top had no IaC signal at all |
| Monil AS Backend (Go) | Go@11 **BEFORE** (title) | Title exact-match still lost to non-Go Learnster under dense retrieval |
| Learnster (Go query) | Go = NOT_FOUND | Confuser lacks Go; Carla's Go@264 was visible to dense E5 |

**Reading:** In every clean ALE-92 pair we could still resolve, the better match's distinguishing tech-stack term was present in the dense embedding window. Ranking failures therefore look like dense semantic near-ties / keyword-blindness (the gap ADR-0010 targets), not "the vector never saw the word."

## ALE-138 role / geo

| Case | Finding |
|---|---|
| frontend roles → Learnster backend | `backend` in title (@8); no `frontend` in body — role confusion from title/semantic proximity, not a truncated frontend signal |
| customer support → Custobar KAM | `Key Account` in title (@12); lone `support`@536 is AFTER cutoff but is not the primary role signal |
| PM Stockholm → Telgea Spain | **Control.** Payload `Country=Spain`, `location=Barcelona`. `document_text` never contains Spain; incidental Stockholm/Sweden appear in company description (@168/@224) — geo miss is payload-filter territory (ADR-0002), not truncation |
| backend python Germany → Framna NL | **Control.** Payload `Country=Netherlands`. Germany absent from `document_text`. Mechanism-inapplicable |

## Broader sample (n=150)

| Keyword | Found | Past 512 | Median token |
|---|---:|---:|---:|
| Python | 13 | 9 | 713 |
| React | 19 | 13 | 567 |
| Kubernetes | 8 | 7 | 899 |
| Terraform | 8 | 8 | 804 |
| Go | 40 | 20 | 510 |
| frontend | 15 | 11 | 616 |
| backend | 26 | 16 | 602 |
| devops | 6 | 5 | 758 |

`Job Description:` section start — median token offset **164** (only 1.3% of samples start the job body after 512). Company descriptions often consume the early window, and tech-stack language *in general* frequently sits past 512 — but that corpus-level pattern did not hold for the specific better-match jobs that ALE-92 flagged.

## Decision

**NO-GO** on a dedicated truncation-fix ADR (chunking / `document_text` restructuring / summarization) as a response to the ALE-92 / ALE-138 precision failures.

| Gate | Result |
|---|---|
| ≥50% better-match jobs with keyword(s) past 512 | **Fail** — 0/2 (0%) |
| Broader tech-stack medians > 512 | **Pass** — several keywords (Python, React, Kubernetes, Terraform, …) |
| Combined (AND) | **Fail → NO-GO** |

Truncation remains a real property of the corpus and may matter for *other* failure modes later. It is not the explanatory mechanism for the already-documented dense keyword / role / geo gaps.

### Revisit trigger

Re-open this investigation if a new failure class is shown to depend on body content that sits past the dense 512-token window **after** hybrid search (ADR-0010) is the production default. Do not silently re-raise truncation as the cause of ALE-92 / ALE-138 misses without new evidence.

### Priority unchanged

- ADR-0010 / ALE-143 (sparse/BM25 hybrid) remains the right fix path for keyword/tech-stack precision.
- ADR-0002 structured filters remain the right path for country/geo.
- Role confusion (ALE-151 / findings 0002) remains a separate dense-semantic problem, not a truncation problem.

## Out of scope (unchanged)

No chunking, document restructuring, or summarization implemented here. E5 migration (ADR-0014) and hybrid search (ADR-0010) are not re-litigated.
