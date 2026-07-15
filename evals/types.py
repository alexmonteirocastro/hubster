"""Structured result types for comparison / sweep tooling (ALE-147).

Designed for CLI printers and UI consumers (ALE-146) alike — avoid print-only
APIs in the library layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class QueryResult:
    """Per-query embedding retrieval outcome against golden expectations."""

    query_id: str
    query_text: str
    expected_job_ids: list[str]
    expected_scores: dict[str, float | None] = field(default_factory=dict)
    top_noise_score: float | None = None
    all_missing: list[str] = field(default_factory=list)


@dataclass
class ModelSummary:
    """Aggregate metrics for one embedding model over a golden query set."""

    model: str
    missed_count: int
    min_expected_score: float | None
    max_noise_score: float | None
    separation_margin: float | None


@dataclass
class EmbeddingComparisonResult:
    """Side-by-side embedding model comparison against the golden set."""

    models: list[str]
    results_by_model: dict[str, list[QueryResult]]
    summaries: dict[str, ModelSummary]
    collection_names: dict[str, str]


@dataclass
class GenerationCaseResult:
    """One golden_generation case run through one Generator."""

    case_id: str
    query: str
    generator_label: str
    answer: str
    source_job_ids: list[str]
    expected_source_job_ids: list[str]
    missing_expected_source_ids: list[str]
    ungrounded_urls: list[str]
    ungrounded_phrases: list[str]
    generated: bool
    error: str | None = None


@dataclass
class GenerationComparisonResult:
    """Side-by-side generation comparison against golden_generation.json.

    Note: ``mock_answer_substring`` from the fixture is intentionally omitted —
    that field only applies to ScriptedGenerator in pytest, not live models.
    """

    generator_labels: list[str]
    results: list[GenerationCaseResult]
    collection_name: str


@dataclass
class MinScoreSweepRow:
    """One CHAT_SOURCE_MIN_SCORE candidate evaluated against retrieval scores."""

    threshold: float
    expected_survivors: int
    expected_total: int
    missed_expected: int
    confuser_survivors: int
    confuser_total: int


@dataclass
class MinScoreSweepResult:
    """Grid of CHAT_SOURCE_MIN_SCORE candidates with a suggested safe band."""

    rows: list[MinScoreSweepRow]
    suggested_max_safe_threshold: float | None
    collection_name: str


@dataclass
class ScoredHit:
    """Lightweight retrieval hit used by the min-score sweep (no Qdrant deps)."""

    job_id: str
    score: float


@dataclass
class SweepCaseScores:
    """Precomputed per-case hit scores for threshold application."""

    case_id: str
    query_text: str
    expected_job_ids: list[str]
    confuser_job_ids: list[str]
    hits: list[ScoredHit]
