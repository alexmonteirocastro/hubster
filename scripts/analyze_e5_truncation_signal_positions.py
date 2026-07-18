"""ALE-141: Correlate E5 dense truncation with retrieval-precision failures.

Read-only scroll of JOBS_ON_THE_HUB. For ALE-92 / ALE-138 failure jobs, locate
distinguishing keywords relative to the 512-token dense cutoff; run a broader
sample of where role/stack signal sits; and confirm geo misses are
mechanism-inapplicable (Country/location are payload-only, not in document_text).

Qdrant Cloud Inference prepends `passage: ` on upsert for E5, so token offsets
use that prefixed form (same as scripts/check_e5_document_token_lengths.py).

Usage:

    uv run python scripts/analyze_e5_truncation_signal_positions.py
    uv run python scripts/analyze_e5_truncation_signal_positions.py --limit 200
    uv run python scripts/analyze_e5_truncation_signal_positions.py \\
        --print-linear-comment

Requires .env with QDRANT_URL, QDRANT_API_KEY, QDRANT_COLLECTION_NAME.
"""

from __future__ import annotations

import argparse
import math
import random
import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from huggingface_hub import hf_hub_download  # noqa: E402
from qdrant_client import QdrantClient  # noqa: E402
from tokenizers import Tokenizer  # type: ignore[import-untyped]

from db import get_settings  # noqa: E402
from db.settings import uses_cloud_inference  # noqa: E402

E5_MODEL = "intfloat/multilingual-e5-small"
E5_MAX_TOKENS = 512
E5_PASSAGE_PREFIX = "passage: "
SCROLL_BATCH_SIZE = 100
JOB_DESCRIPTION_MARKER = "Job Description:"
COMPANY_DESCRIPTION_MARKER = "Company Description:"

# Role / stack keywords for the broader sample (case-insensitive word match).
BROADER_STACK_KEYWORDS = (
    "Python",
    "React",
    "Kubernetes",
    "Terraform",
    "Django",
    "FastAPI",
    "Golang",
    "Go",
)
BROADER_ROLE_KEYWORDS = (
    "frontend",
    "backend",
    "devops",
    "fullstack",
)

# ---------------------------------------------------------------------------
# ALE-92 / ALE-138 targets (company + title substrings; no stable Hub IDs).
# role: "better" = expected/correct match; "wrong" = confuser / wrong top-1;
#        "control" = geo control (mechanism-inapplicable).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TargetSpec:
    case_id: str
    role: str  # better | wrong | related | control
    company_substr: str
    title_substr: str
    keywords: tuple[str, ...]
    notes: str = ""


TARGETS: tuple[TargetSpec, ...] = (
    # ALE-92 Case 1 — Python/FastAPI
    TargetSpec(
        "ale92-python-wrong",
        "wrong",
        "Framna",
        "Backend",
        ("Python", "FastAPI", "Django", "PHP", "Node"),
        "Framna Backend — PHP/Node primary; Python once",
    ),
    TargetSpec(
        "ale92-python-better",
        "better",
        "Learnster",
        "Backend",
        ("Python", "Django", "FastAPI"),
        "Learnster Backend & Platform — Python/Django core",
    ),
    # ALE-92 Case 2 — Go
    TargetSpec(
        "ale92-go-wrong",
        "wrong",
        "Learnster",
        "Backend",
        ("Go", "Golang", "Python", "Django"),
        "Learnster — no Go (same posting as python-better)",
    ),
    TargetSpec(
        "ale92-go-better",
        "better",
        "Carla",
        "Backend",
        ("Go", "Golang"),
        "Carla Backend — Go-primary",
    ),
    TargetSpec(
        "ale92-go-title",
        "related",
        "Monil",
        "Go",
        ("Go", "Golang"),
        "Monil AS — (Go) in title, ranked #5",
    ),
    # ALE-92 Case 3 — Terraform
    TargetSpec(
        "ale92-terraform-wrong",
        "wrong",
        "Spoor",
        "Senior Software",
        ("Terraform", "IaC", "Ansible", "CloudFormation"),
        "Spoor Senior SWE — no Terraform",
    ),
    TargetSpec(
        "ale92-terraform-better",
        "better",
        "Learnster",
        "Backend",
        ("Terraform", "CloudFormation", "IaC"),
        "Learnster — Terraform as explicit requirement",
    ),
    TargetSpec(
        "ale92-terraform-bonus",
        "related",
        "Acembee",
        "Full",
        ("Terraform", "Ansible"),
        "Acembee — Terraform as bonus only",
    ),
    # ALE-92 K8s confound
    TargetSpec(
        "ale92-k8s-wrong",
        "wrong",
        "Framna",
        "DevOps",
        ("Kubernetes", "Docker", "Containers"),
        "Framna DevOps — Dutch body; K8s once",
    ),
    TargetSpec(
        "ale92-k8s-better",
        "better",
        "Six Robotics",
        "Platform",
        ("Kubernetes",),
        "Six Robotics Platform (Kubernetes)",
    ),
    # ALE-138 role / support misses
    TargetSpec(
        "ale138-frontend-miss",
        "wrong",
        "Learnster",
        "Backend",
        ("frontend", "backend", "Frontend", "Backend"),
        "frontend roles [SE] → Learnster backend",
    ),
    TargetSpec(
        "ale138-support-miss",
        "wrong",
        "Custobar",
        "Account",
        ("support", "customer support", "Key Account", "customer"),
        "customer support Finland → Custobar KAM",
    ),
    # ALE-138 geo controls (mechanism-inapplicable)
    TargetSpec(
        "ale138-geo-stockholm",
        "control",
        "Telgea",
        "Product Manager",
        ("Sweden", "Stockholm", "Spain"),
        "PM Stockholm → Telgea Spain (Country is payload-only)",
    ),
    TargetSpec(
        "ale138-geo-germany",
        "control",
        "Framna",
        "Backend",
        ("Germany", "Netherlands", "Dutch"),
        "backend python Germany → Framna NL (Country is payload-only)",
    ),
)


@dataclass
class KeywordHit:
    keyword: str
    char_offset: int | None
    token_offset: int | None
    section: str
    past_cutoff: bool | None  # None = not found


@dataclass
class ResolvedJob:
    case_id: str
    role: str
    notes: str
    job_url_identifier: str
    job_title: str
    company: str
    country: str
    location: str
    total_tokens: int
    job_description_token_offset: int | None
    company_description_token_offset: int | None
    keyword_hits: list[KeywordHit] = field(default_factory=list)
    match_quality: str = "exact"  # exact | fuzzy | missing


@dataclass
class BroaderKeywordStats:
    keyword: str
    n_found: int
    n_past_cutoff: int
    median_offset: float | None
    p90_offset: float | None


@dataclass
class AnalysisResult:
    corpus_size: int
    resolved: list[ResolvedJob]
    missing_targets: list[str]
    broader_stack: list[BroaderKeywordStats]
    broader_role: list[BroaderKeywordStats]
    job_desc_start_median: float | None
    job_desc_start_past_pct: float | None
    go_decision: str
    go_rationale: str
    better_match_past_cutoff_count: int
    better_match_total: int
    stack_median_gt_512: bool


def _validate_config() -> None:
    if not uses_cloud_inference():
        raise ValueError(
            f"{E5_MODEL} requires Qdrant Cloud Inference. "
            "Point QDRANT_URL and QDRANT_API_KEY at your Cloud cluster."
        )


def _get_client() -> QdrantClient:
    settings = get_settings()
    kwargs: dict[str, Any] = {"url": settings.qdrant_url}
    if settings.qdrant_api_key:
        kwargs["api_key"] = settings.qdrant_api_key
    return QdrantClient(**kwargs)


@lru_cache(maxsize=1)
def _load_e5_tokenizer() -> Tokenizer:
    tokenizer_path = hf_hub_download(E5_MODEL, "tokenizer.json")
    return Tokenizer.from_file(tokenizer_path)


def _percentile(values: list[int], pct: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = (len(sorted_vals) - 1) * pct / 100
    lower = math.floor(idx)
    upper = math.ceil(idx)
    if lower == upper:
        return float(sorted_vals[int(idx)])
    weight = idx - lower
    return sorted_vals[lower] * (1 - weight) + sorted_vals[upper] * weight


def _embedding_input(document_text: str) -> str:
    if document_text.startswith(E5_PASSAGE_PREFIX):
        return document_text
    return f"{E5_PASSAGE_PREFIX}{document_text}"


def _count_tokens(tokenizer: Tokenizer, document_text: str) -> int:
    return len(tokenizer.encode(_embedding_input(document_text)).ids)


def _token_offset_at_char(
    tokenizer: Tokenizer, document_text: str, char_offset: int
) -> int:
    """Token count of passage-prefixed text up to char_offset in document_text."""
    prefix_len = (
        0 if document_text.startswith(E5_PASSAGE_PREFIX) else len(E5_PASSAGE_PREFIX)
    )
    # Encode only the prefix of the embedding input that ends at char_offset.
    emb = _embedding_input(document_text)
    cut = prefix_len + char_offset
    return len(tokenizer.encode(emb[:cut]).ids)


def _section_for_char_offset(document_text: str, char_offset: int) -> str:
    jd = document_text.find(JOB_DESCRIPTION_MARKER)
    cd = document_text.find(COMPANY_DESCRIPTION_MARKER)
    if jd >= 0 and char_offset >= jd:
        return "job_description"
    if cd >= 0 and char_offset >= cd:
        return "company_description"
    # First lines: Job Title / Company
    first_nl = document_text.find("\n")
    second_nl = document_text.find("\n", first_nl + 1) if first_nl >= 0 else -1
    if first_nl >= 0 and char_offset < first_nl:
        return "title"
    if second_nl >= 0 and char_offset < second_nl:
        return "company"
    return "preamble"


def _find_keyword_char_offset(document_text: str, keyword: str) -> int | None:
    """First case-insensitive match; word-boundary for short keywords like Go."""
    if keyword.lower() in {"go"}:
        pattern = re.compile(r"(?<![A-Za-z])Go(?![A-Za-z])", re.IGNORECASE)
        match = pattern.search(document_text)
        return match.start() if match else None
    pattern = re.compile(re.escape(keyword), re.IGNORECASE)
    match = pattern.search(document_text)
    return match.start() if match else None


def _analyze_keywords(
    tokenizer: Tokenizer, document_text: str, keywords: tuple[str, ...]
) -> list[KeywordHit]:
    hits: list[KeywordHit] = []
    for keyword in keywords:
        char_off = _find_keyword_char_offset(document_text, keyword)
        if char_off is None:
            hits.append(
                KeywordHit(
                    keyword=keyword,
                    char_offset=None,
                    token_offset=None,
                    section="not_found",
                    past_cutoff=None,
                )
            )
            continue
        tok_off = _token_offset_at_char(tokenizer, document_text, char_off)
        hits.append(
            KeywordHit(
                keyword=keyword,
                char_offset=char_off,
                token_offset=tok_off,
                section=_section_for_char_offset(document_text, char_off),
                past_cutoff=tok_off > E5_MAX_TOKENS,
            )
        )
    return hits


def _scroll_production_corpus(
    client: QdrantClient, collection_name: str, limit: int | None
) -> list[dict]:
    print(f"Scrolling production collection {collection_name!r} (read-only)...")
    points: list[dict] = []
    next_offset = None
    while True:
        batch, next_offset = client.scroll(
            collection_name=collection_name,
            limit=SCROLL_BATCH_SIZE,
            offset=next_offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in batch:
            payload = point.payload or {}
            doc_text = payload.get("document_text")
            job_id = payload.get("job_url_identifier")
            if not doc_text or not job_id:
                continue
            points.append(
                {
                    "job_url_identifier": job_id,
                    "document_text": doc_text,
                    "job_title": payload.get("job_title") or "?",
                    "company": payload.get("company") or "?",
                    "Country": payload.get("Country") or "",
                    "location": payload.get("location") or "",
                }
            )
            if limit is not None and len(points) >= limit:
                print(f"Stopped at --limit {limit}.")
                return points
        print(f"  scrolled {len(points)} points so far...")
        if next_offset is None:
            break
    print(f"Done: {len(points)} points pulled from production (read-only).")
    return points


def _match_score(point: dict, spec: TargetSpec) -> tuple[int, str]:
    """Higher is better. Prefer company+title substring matches."""
    company = (point["company"] or "").casefold()
    title = (point["job_title"] or "").casefold()
    c_sub = spec.company_substr.casefold()
    t_sub = spec.title_substr.casefold()
    if c_sub in company and t_sub in title:
        # Prefer tighter title match (shorter title distance)
        return (100 - abs(len(title) - len(t_sub)), "exact")
    if c_sub in company:
        return (50, "fuzzy")
    return (0, "missing")


def _resolve_target(points: list[dict], spec: TargetSpec) -> dict | None:
    best: dict | None = None
    best_score = 0
    best_quality = "missing"
    for point in points:
        score, quality = _match_score(point, spec)
        if score > best_score:
            best_score = score
            best = point
            best_quality = quality
    if best is None or best_score == 0:
        return None
    best = dict(best)
    best["_match_quality"] = best_quality
    return best


def _primary_keyword_past_cutoff(job: ResolvedJob) -> bool | None:
    """True if any found keyword is past cutoff; False if all found are inside;
    None if no keywords found at all."""
    found = [h for h in job.keyword_hits if h.token_offset is not None]
    if not found:
        return None
    return any(h.past_cutoff for h in found)


def _better_match_primary_past(job: ResolvedJob) -> bool | None:
    """For GO tally: primary distinguishing keyword after 512.

    Prefer stack-ish keywords that were found; if any found keyword is past
    cutoff, count as past. If all found are inside window, count as inside.
    """
    return _primary_keyword_past_cutoff(job)


def _broader_stats(
    tokenizer: Tokenizer,
    sample: list[dict],
    keywords: tuple[str, ...],
) -> list[BroaderKeywordStats]:
    stats: list[BroaderKeywordStats] = []
    for keyword in keywords:
        offsets: list[int] = []
        past = 0
        for item in sample:
            char_off = _find_keyword_char_offset(item["document_text"], keyword)
            if char_off is None:
                continue
            tok = _token_offset_at_char(tokenizer, item["document_text"], char_off)
            offsets.append(tok)
            if tok > E5_MAX_TOKENS:
                past += 1
        stats.append(
            BroaderKeywordStats(
                keyword=keyword,
                n_found=len(offsets),
                n_past_cutoff=past,
                median_offset=_percentile(offsets, 50) if offsets else None,
                p90_offset=_percentile(offsets, 90) if offsets else None,
            )
        )
    return stats


def _job_description_starts(tokenizer: Tokenizer, sample: list[dict]) -> list[int]:
    offsets: list[int] = []
    for item in sample:
        text = item["document_text"]
        char_off = text.find(JOB_DESCRIPTION_MARKER)
        if char_off < 0:
            continue
        offsets.append(_token_offset_at_char(tokenizer, text, char_off))
    return offsets


def run_analysis(
    points: list[dict],
    *,
    sample_size: int = 150,
    seed: int = 42,
) -> AnalysisResult:
    tokenizer = _load_e5_tokenizer()
    resolved: list[ResolvedJob] = []
    missing: list[str] = []

    for spec in TARGETS:
        match = _resolve_target(points, spec)
        if match is None:
            missing.append(
                f"{spec.case_id} ({spec.company_substr} / {spec.title_substr})"
            )
            continue
        text = match["document_text"]
        jd_char = text.find(JOB_DESCRIPTION_MARKER)
        cd_char = text.find(COMPANY_DESCRIPTION_MARKER)
        resolved.append(
            ResolvedJob(
                case_id=spec.case_id,
                role=spec.role,
                notes=spec.notes,
                job_url_identifier=match["job_url_identifier"],
                job_title=match["job_title"],
                company=match["company"],
                country=str(match.get("Country") or ""),
                location=str(match.get("location") or ""),
                total_tokens=_count_tokens(tokenizer, text),
                job_description_token_offset=(
                    _token_offset_at_char(tokenizer, text, jd_char)
                    if jd_char >= 0
                    else None
                ),
                company_description_token_offset=(
                    _token_offset_at_char(tokenizer, text, cd_char)
                    if cd_char >= 0
                    else None
                ),
                keyword_hits=_analyze_keywords(tokenizer, text, spec.keywords),
                match_quality=str(match.get("_match_quality") or "exact"),
            )
        )

    rng = random.Random(seed)
    sample = list(points)
    if len(sample) > sample_size:
        sample = rng.sample(sample, sample_size)

    broader_stack = _broader_stats(tokenizer, sample, BROADER_STACK_KEYWORDS)
    broader_role = _broader_stats(tokenizer, sample, BROADER_ROLE_KEYWORDS)
    # Drop duplicate Go from stack helper if we added it via GO_KEYWORD path only
    # _broader_stats always appends Go when not in keywords — stack already has no Go.
    jd_starts = _job_description_starts(tokenizer, sample)
    jd_median = _percentile(jd_starts, 50) if jd_starts else None
    jd_past_pct = (
        100.0 * sum(1 for o in jd_starts if o > E5_MAX_TOKENS) / len(jd_starts)
        if jd_starts
        else None
    )

    # Unique better-match jobs for GO tally (Learnster appears in multiple cases).
    better_jobs = [j for j in resolved if j.role == "better"]
    # Deduplicate by job_url_identifier for the ≥50% rule on "better-match jobs"
    seen_ids: set[str] = set()
    unique_better: list[ResolvedJob] = []
    for job in better_jobs:
        if job.job_url_identifier in seen_ids:
            continue
        seen_ids.add(job.job_url_identifier)
        unique_better.append(job)

    past_count = 0
    eligible = 0
    for job in unique_better:
        verdict = _better_match_primary_past(job)
        if verdict is None:
            continue
        eligible += 1
        if verdict:
            past_count += 1

    # Decision rule: broader sample shows tech-stack medians systematically > 512
    # when a keyword appears often enough to be meaningful (n_found >= 5).
    stack_median_gt_512 = any(
        s.median_offset is not None
        and s.n_found >= 5
        and s.median_offset > E5_MAX_TOKENS
        for s in broader_stack
    )

    better_pct = (100.0 * past_count / eligible) if eligible else 0.0
    go_threshold_met = eligible > 0 and (past_count / eligible) >= 0.5

    if go_threshold_met and stack_median_gt_512:
        go = "GO"
        rationale = (
            f"{past_count}/{eligible} unique better-match jobs "
            f"({better_pct:.0f}%) have distinguishing keyword(s) past token "
            f"{E5_MAX_TOKENS}, AND broader sample tech-stack medians exceed "
            f"{E5_MAX_TOKENS}. Dense truncation likely cuts disambiguating signal."
        )
    else:
        go = "NO-GO"
        parts: list[str] = []
        if not go_threshold_met:
            parts.append(
                f"only {past_count}/{eligible} unique better-match jobs "
                f"({better_pct:.0f}%) have distinguishing keywords past "
                f"{E5_MAX_TOKENS} (need ≥50%)"
            )
        if not stack_median_gt_512:
            parts.append(
                f"broader-sample tech-stack keyword medians are not "
                f"systematically > {E5_MAX_TOKENS}"
            )
        rationale = (
            "Truncation is real corpus-wide, but does not meet the locked "
            "decision rule: " + "; ".join(parts) + ". "
            "Revisit if a new failure class depends on body content past the "
            "dense window after hybrid is the production default."
        )

    return AnalysisResult(
        corpus_size=len(points),
        resolved=resolved,
        missing_targets=missing,
        broader_stack=broader_stack,
        broader_role=broader_role,
        job_desc_start_median=jd_median,
        job_desc_start_past_pct=jd_past_pct,
        go_decision=go,
        go_rationale=rationale,
        better_match_past_cutoff_count=past_count,
        better_match_total=eligible,
        stack_median_gt_512=stack_median_gt_512,
    )


def _fmt_hit(hit: KeywordHit) -> str:
    if hit.token_offset is None:
        return f"{hit.keyword}=NOT_FOUND"
    side = "AFTER" if hit.past_cutoff else "BEFORE"
    return f"{hit.keyword}@{hit.token_offset} ({side}, {hit.section})"


def _print_results(result: AnalysisResult) -> None:
    print("\n" + "=" * 80)
    print(f"ALE-141 truncation signal positions — {E5_MODEL} (limit={E5_MAX_TOKENS})")
    print("=" * 80)
    print(f"Corpus size: {result.corpus_size} points")

    if result.missing_targets:
        print("\nMissing targets (company/title not found — may have rotated off Hub):")
        for m in result.missing_targets:
            print(f"  - {m}")

    print("\n--- Targeted failure / control jobs ---")
    for job in result.resolved:
        print(
            f"\n[{job.case_id}] role={job.role} match={job.match_quality}\n"
            f"  {job.job_title} @ {job.company} "
            f"(id={job.job_url_identifier})\n"
            f"  Country={job.country!r} location={job.location!r}\n"
            f"  total_tokens={job.total_tokens}  "
            f"JobDesc@{job.job_description_token_offset}  "
            f"CoDesc@{job.company_description_token_offset}\n"
            f"  notes: {job.notes}"
        )
        for hit in job.keyword_hits:
            print(f"    {_fmt_hit(hit)}")
        if job.role == "control":
            # Explicit control note: query country typically absent from document_text
            print(
                "  CONTROL: Country/location are payload fields; "
                "geo mismatch cannot be explained by truncating location out of "
                "document_text."
            )

    print("\n--- Broader sample: tech-stack keywords ---")
    for s in result.broader_stack:
        med = f"{s.median_offset:.0f}" if s.median_offset is not None else "n/a"
        p90 = f"{s.p90_offset:.0f}" if s.p90_offset is not None else "n/a"
        print(
            f"  {s.keyword:<12} found={s.n_found:<4} "
            f"past_512={s.n_past_cutoff:<4} median={med:<6} p90={p90}"
        )

    print("\n--- Broader sample: role keywords ---")
    for s in result.broader_role:
        med = f"{s.median_offset:.0f}" if s.median_offset is not None else "n/a"
        p90 = f"{s.p90_offset:.0f}" if s.p90_offset is not None else "n/a"
        print(
            f"  {s.keyword:<12} found={s.n_found:<4} "
            f"past_512={s.n_past_cutoff:<4} median={med:<6} p90={p90}"
        )

    jd_med = (
        f"{result.job_desc_start_median:.0f}"
        if result.job_desc_start_median is not None
        else "n/a"
    )
    jd_pct = (
        f"{result.job_desc_start_past_pct:.1f}%"
        if result.job_desc_start_past_pct is not None
        else "n/a"
    )
    print(
        f"\nJob Description: marker token offset — "
        f"median={jd_med}, % starting after 512={jd_pct}"
    )

    print("\n" + "=" * 80)
    print(f"DECISION: {result.go_decision}")
    print("=" * 80)
    print(
        f"Better-match jobs with keyword(s) past 512: "
        f"{result.better_match_past_cutoff_count}/{result.better_match_total}"
    )
    print(f"Broader stack median > 512: {result.stack_median_gt_512}")
    print(result.go_rationale)


def _fmt_opt(value: float | None, fmt: str = ".0f") -> str:
    if value is None:
        return "n/a"
    return format(value, fmt)


def _next_steps(go_decision: str) -> str:
    if go_decision == "GO":
        return (
            "Open a follow-up ADR scoping document_text restructuring "
            "(front-load distinguishing fields), chunking, or summarization — "
            "do not implement in this ticket."
        )
    return (
        "Record as investigated-and-ruled-out. Revisit trigger: re-open if a "
        "new failure class is shown to depend on body content past the dense "
        "window after hybrid is the production default. ADR-0010 / ADR-0002 "
        "priorities unchanged."
    )


def format_linear_comment(result: AnalysisResult, *, collection_name: str) -> str:
    rows: list[str] = []
    for job in result.resolved:
        hits = "; ".join(_fmt_hit(h) for h in job.keyword_hits)
        rows.append(
            f"| `{job.case_id}` | {job.role} | {job.company} / {job.job_title} | "
            f"{job.total_tokens} | {job.job_description_token_offset} | {hits} |"
        )

    stack_rows = []
    for s in result.broader_stack:
        med = f"{s.median_offset:.0f}" if s.median_offset is not None else "—"
        stack_rows.append(f"| {s.keyword} | {s.n_found} | {s.n_past_cutoff} | {med} |")

    missing = (
        "\n".join(f"- {m}" for m in result.missing_targets)
        if result.missing_targets
        else "_None_"
    )

    return f"""## Spike findings: E5 truncation vs retrieval failures (ALE-141)

**Recommendation: {result.go_decision}.**

{result.go_rationale}

### Methodology

Read-only scroll of `{collection_name}` ({result.corpus_size} points). Tokenized
with `{E5_MODEL}` using `passage: ` + stored `document_text` (Cloud Inference
upsert behavior). For each ALE-92 / ALE-138 target, resolved by company+title
substring and reported first-match token offset vs the 512-token dense cutoff.
Broader sample (~150 jobs) for role/stack keyword position distributions.
Geo cases treated as **control** (Country/location are payload-only per ADR-0002).

Script: `scripts/analyze_e5_truncation_signal_positions.py`.

### Decision rule (locked)

- **GO** if ≥50% of unique ALE-92 better-match jobs have distinguishing
  keyword(s) after token 512, **and** broader-sample tech-stack medians > 512.
- Geo / payload-only misses never count toward the GO tally.

### Targeted jobs

| Case | Role | Job | Tokens | JobDesc@ | Keywords |
|---|---|---|---:|---:|---|
{chr(10).join(rows)}

### Missing targets

{missing}

### Broader sample — tech-stack first-occurrence offsets

| Keyword | Found | Past 512 | Median token |
|---|---:|---:|---:|
{chr(10).join(stack_rows)}

Job Description section start — median token offset: \
{_fmt_opt(result.job_desc_start_median)} \
({_fmt_opt(result.job_desc_start_past_pct, ".1f")}% after 512).

### Control: geo misses

ALE-138 Stockholm→Spain and Germany→Netherlands failures cannot be explained by
truncating location out of the dense vector — `Country` / `location` are never
part of `document_text` (ADR-0002). Mechanism-inapplicable; excluded from GO tally.

### Next steps

{_next_steps(result.go_decision)}

Full write-up: `docs/findings/0003-e5-truncation-retrieval-correlation-findings.md`.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Scroll only the first N production points (smoke test).",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=150,
        help="Broader-sample size (default 150).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="RNG seed for broader sample (default 42).",
    )
    parser.add_argument(
        "--print-linear-comment",
        action="store_true",
        help="Print a Markdown block suitable for a Linear ticket comment.",
    )
    args = parser.parse_args()

    try:
        _validate_config()
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    settings = get_settings()
    client = _get_client()
    points = _scroll_production_corpus(
        client, settings.qdrant_collection_name, args.limit
    )
    if not points:
        print("No points found in production collection.")
        return 1

    result = run_analysis(points, sample_size=args.sample_size, seed=args.seed)
    _print_results(result)
    if args.print_linear_comment:
        print(
            "\n"
            + format_linear_comment(
                result, collection_name=settings.qdrant_collection_name
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
