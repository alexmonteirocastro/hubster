"""CHAT_SOURCE_MIN_SCORE hyperparameter sweep against the golden set (ALE-147).

Pulls from ``queries`` and ``role_confusion_cases`` in golden_queries.json —
both have a real score-floor semantic. Explicitly does **not** include
``tech_stack_adversarial_cases`` (ALE-145): those are rank-order-only with no
``min_score`` field and do not mean anything run through a floor sweep.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from qdrant_client import QdrantClient

from db import get_settings, query_jobs_in_qdrant
from evals.collections import (
    MIN_SCORE_SWEEP_COLLECTION,
    delete_collections,
    embedding_model_override,
    get_comparison_client,
    seed_collection_for_model,
    validate_qdrant_config,
)
from evals.fixtures import load_golden_queries
from evals.types import (
    MinScoreSweepResult,
    MinScoreSweepRow,
    ScoredHit,
    SweepCaseScores,
)
from the_hub_client import CountryCode

DEFAULT_THRESHOLDS: list[float] = [0.80, 0.82, 0.84, 0.85, 0.87]


def collect_sweep_case_scores(
    client: QdrantClient,
    collection_name: str,
    model: str,
    golden_set: dict[str, Any],
) -> list[SweepCaseScores]:
    """Query once for each golden / role-confusion case; return hit scores."""
    top_k = int(golden_set["top_k"])
    cases: list[SweepCaseScores] = []

    with embedding_model_override(model):
        for case in golden_set.get("queries", []):
            country_filter = case.get("country")
            country_code = CountryCode(country_filter) if country_filter else None
            response = query_jobs_in_qdrant(
                db_client=client,
                collection_name=collection_name,
                query_text=case["query"],
                limit=top_k,
                country=country_code,
            )
            hits = [
                ScoredHit(
                    job_id=str(hit.payload.get("job_url_identifier")),
                    score=float(hit.score),
                )
                for hit in response.points
                if hit.payload and hit.payload.get("job_url_identifier")
            ]
            cases.append(
                SweepCaseScores(
                    case_id=str(case["id"]),
                    query_text=str(case["query"]),
                    expected_job_ids=[str(j) for j in case["expected_job_ids"]],
                    confuser_job_ids=[],
                    hits=hits,
                )
            )

        # role_confusion_cases only — not tech_stack_adversarial_cases (ALE-145).
        for case in golden_set.get("role_confusion_cases", []):
            response = query_jobs_in_qdrant(
                db_client=client,
                collection_name=collection_name,
                query_text=case["query"],
                limit=top_k,
            )
            hits = [
                ScoredHit(
                    job_id=str(hit.payload.get("job_url_identifier")),
                    score=float(hit.score),
                )
                for hit in response.points
                if hit.payload and hit.payload.get("job_url_identifier")
            ]
            cases.append(
                SweepCaseScores(
                    case_id=str(case["id"]),
                    query_text=str(case["query"]),
                    expected_job_ids=[str(j) for j in case["expected_job_ids"]],
                    confuser_job_ids=[str(j) for j in case.get("confuser_job_ids", [])],
                    hits=hits,
                )
            )

    return cases


def evaluate_threshold(
    cases: Sequence[SweepCaseScores],
    threshold: float,
) -> MinScoreSweepRow:
    """Apply a min-score floor to precomputed hits.

    Same idea as ``filter_points_by_min_score`` / chat source filtering.
    """
    expected_total = 0
    expected_survivors = 0
    confuser_total = 0
    confuser_survivors = 0

    for case in cases:
        scores_by_id = {hit.job_id: hit.score for hit in case.hits}
        for job_id in case.expected_job_ids:
            expected_total += 1
            score = scores_by_id.get(job_id)
            if score is not None and score >= threshold:
                expected_survivors += 1
        for job_id in case.confuser_job_ids:
            confuser_total += 1
            score = scores_by_id.get(job_id)
            if score is not None and score >= threshold:
                confuser_survivors += 1

    return MinScoreSweepRow(
        threshold=threshold,
        expected_survivors=expected_survivors,
        expected_total=expected_total,
        missed_expected=expected_total - expected_survivors,
        confuser_survivors=confuser_survivors,
        confuser_total=confuser_total,
    )


def suggest_max_safe_threshold(rows: Sequence[MinScoreSweepRow]) -> float | None:
    """Largest threshold where every expected golden hit still survives."""
    safe = [
        row.threshold
        for row in rows
        if row.expected_total > 0 and row.missed_expected == 0
    ]
    return max(safe) if safe else None


def sweep_from_case_scores(
    cases: Sequence[SweepCaseScores],
    thresholds: Sequence[float],
    *,
    collection_name: str = "",
) -> MinScoreSweepResult:
    """Pure aggregation over precomputed scores — unit-testable without Qdrant."""
    rows = [evaluate_threshold(cases, threshold) for threshold in thresholds]
    return MinScoreSweepResult(
        rows=rows,
        suggested_max_safe_threshold=suggest_max_safe_threshold(rows),
        collection_name=collection_name,
    )


def sweep_chat_source_min_score(
    thresholds: Sequence[float] | None = None,
    *,
    keep_collection: bool = False,
    collection_name: str = MIN_SCORE_SWEEP_COLLECTION,
    client: QdrantClient | None = None,
    embedding_model: str | None = None,
) -> MinScoreSweepResult:
    """Seed golden jobs, query once, evaluate each CHAT_SOURCE_MIN_SCORE candidate."""
    validate_qdrant_config()
    settings = get_settings()
    model = embedding_model if embedding_model is not None else settings.embedding_model
    chosen = list(thresholds) if thresholds is not None else list(DEFAULT_THRESHOLDS)
    if not chosen:
        raise ValueError("sweep_chat_source_min_score requires at least one threshold")

    qdrant = client if client is not None else get_comparison_client()
    golden_set = load_golden_queries()

    if qdrant.collection_exists(collection_name):
        qdrant.delete_collection(collection_name)
    seed_collection_for_model(qdrant, collection_name, model)

    try:
        cases = collect_sweep_case_scores(qdrant, collection_name, model, golden_set)
        return sweep_from_case_scores(cases, chosen, collection_name=collection_name)
    finally:
        if not keep_collection:
            delete_collections(qdrant, [collection_name])
