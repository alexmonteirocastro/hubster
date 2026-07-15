"""Embedding model comparison against the golden retrieval set (ALE-147)."""

from __future__ import annotations

from qdrant_client import QdrantClient

from db import query_jobs_in_qdrant
from db.settings import uses_cloud_inference
from evals.collections import (
    collection_name_for_model,
    delete_collections,
    embedding_model_override,
    get_comparison_client,
    resolve_model_name,
    seed_collection_for_model,
    validate_qdrant_config,
)
from evals.fixtures import load_golden_queries
from evals.types import EmbeddingComparisonResult, ModelSummary, QueryResult
from the_hub_client import CountryCode

DEFAULT_MODELS: list[str] = [
    "all-MiniLM-L6-v2",
    "intfloat/multilingual-e5-small",
]


def summarize_query_results(model: str, results: list[QueryResult]) -> ModelSummary:
    """Compute missed-hit / margin summary for one model's QueryResult list."""
    all_expected_scores = [
        score
        for result in results
        for score in result.expected_scores.values()
        if score is not None
    ]
    all_noise_scores = [
        result.top_noise_score
        for result in results
        if result.top_noise_score is not None
    ]
    missed_count = sum(len(result.all_missing) for result in results)
    min_expected = min(all_expected_scores) if all_expected_scores else None
    max_noise = max(all_noise_scores) if all_noise_scores else None
    margin: float | None = None
    if min_expected is not None and max_noise is not None:
        margin = min_expected - max_noise
    return ModelSummary(
        model=model,
        missed_count=missed_count,
        min_expected_score=min_expected,
        max_noise_score=max_noise,
        separation_margin=margin,
    )


def run_golden_queries_against(
    client: QdrantClient,
    collection_name: str,
    model: str,
    golden_set: dict,
) -> list[QueryResult]:
    """Run golden queries against one seeded collection; return structured results."""
    with embedding_model_override(model):
        results: list[QueryResult] = []
        top_k = int(golden_set["top_k"])
        for case in golden_set["queries"]:
            country_filter = case.get("country")
            country_code = CountryCode(country_filter) if country_filter else None

            response = query_jobs_in_qdrant(
                db_client=client,
                collection_name=collection_name,
                query_text=case["query"],
                limit=top_k,
                country=country_code,
            )

            hits_by_id = {
                hit.payload.get("job_url_identifier"): hit.score
                for hit in response.points
                if hit.payload
            }

            result = QueryResult(
                query_id=case["id"],
                query_text=case["query"],
                expected_job_ids=list(case["expected_job_ids"]),
            )
            for job_id in case["expected_job_ids"]:
                result.expected_scores[job_id] = hits_by_id.get(job_id)
                if job_id not in hits_by_id:
                    result.all_missing.append(job_id)

            noise_scores = [
                score
                for job_id, score in hits_by_id.items()
                if job_id not in case["expected_job_ids"]
            ]
            result.top_noise_score = max(noise_scores) if noise_scores else None
            results.append(result)
        return results


def compare_embedding_models(
    models: list[str] | None = None,
    *,
    keep_collections: bool = False,
    client: QdrantClient | None = None,
) -> EmbeddingComparisonResult:
    """Seed disposable collections and compare models on the golden query set.

    Returns structured results suitable for CLIs and UI (ALE-146). Creates
    ``JOBS_COMPARE_*`` collections and deletes them unless ``keep_collections``.
    """
    validate_qdrant_config()
    cloud_mode = uses_cloud_inference()
    chosen = list(models) if models is not None else list(DEFAULT_MODELS)
    if len(chosen) < 2:
        raise ValueError("compare_embedding_models requires at least two models")

    resolved = [resolve_model_name(name, cloud_mode=cloud_mode) for name in chosen]
    qdrant = client if client is not None else get_comparison_client()
    golden_set = load_golden_queries()

    collection_names: dict[str, str] = {
        model: collection_name_for_model(model) for model in resolved
    }

    for model, collection_name in collection_names.items():
        if qdrant.collection_exists(collection_name):
            qdrant.delete_collection(collection_name)
        seed_collection_for_model(qdrant, collection_name, model)

    results_by_model: dict[str, list[QueryResult]] = {}
    summaries: dict[str, ModelSummary] = {}
    for model, collection_name in collection_names.items():
        results = run_golden_queries_against(qdrant, collection_name, model, golden_set)
        results_by_model[model] = results
        summaries[model] = summarize_query_results(model, results)

    if not keep_collections:
        delete_collections(qdrant, list(collection_names.values()))

    return EmbeddingComparisonResult(
        models=resolved,
        results_by_model=results_by_model,
        summaries=summaries,
        collection_names=collection_names,
    )
