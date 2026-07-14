"""ALE-138: Compare candidate embedding models against the retrieval golden set.

Seeds two disposable Qdrant collections — one per candidate model — with the
fixed evaluation corpus in `tests/fixtures/golden_jobs.json` (same as the
`@pytest.mark.retrieval` tests), runs every query in
`tests/fixtures/golden_queries.json` against both, and prints a side-by-side
score comparison.

This does not touch QDRANT_COLLECTION_NAME or QDRANT_DEV_COLLECTION_NAME —
it creates its own throwaway collections, so it's safe to run against your
existing Qdrant Cloud cluster without risk to JOBS_ON_THE_HUB or JOBS_DEV.

Usage:

    uv run python scripts/compare_embedding_models.py
    uv run python scripts/compare_embedding_models.py --keep-collections
    uv run python scripts/compare_embedding_models.py \\
        --models BAAI/bge-small-en-v1.5 intfloat/multilingual-e5-small

Requires the same .env as the rest of the project (QDRANT_URL, QDRANT_API_KEY).
Against Qdrant Cloud, the script enables `cloud_inference=True` on the client so
`models.Document(...)` embedding runs server-side (required for
`intfloat/multilingual-e5-small`). On local Qdrant, shorthand model names are
resolved to FastEmbed registry names automatically.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastembed import TextEmbedding  # noqa: E402
from qdrant_client import QdrantClient  # noqa: E402

from db import (  # noqa: E402
    create_collection,
    drop_db,
    get_qdrant_client,
    get_settings,
    load_jobs_into_qdrant,
    query_jobs_in_qdrant,
)
from the_hub_client import CountryCode, JobOpportunity  # noqa: E402

FIXTURES_DIR = _REPO_ROOT / "tests" / "fixtures"
GOLDEN_QUERIES_PATH = FIXTURES_DIR / "golden_queries.json"
GOLDEN_JOBS_PATH = FIXTURES_DIR / "golden_jobs.json"

DEFAULT_MODELS = ["all-MiniLM-L6-v2", "intfloat/multilingual-e5-small"]

# Shorthand / ticket names -> local FastEmbed registry name.
_FASTEMBED_ALIASES: dict[str, str] = {
    "all-minilm-l6-v2": "sentence-transformers/all-MiniLM-L6-v2",
    "sentence-transformers/all-minilm-l6-v2": "sentence-transformers/all-MiniLM-L6-v2",
}

# Shorthand / ticket names -> Qdrant Cloud Inference API name.
# Cloud rejects bare `all-MiniLM-L6-v2`; use sentence-transformers/... instead.
_CLOUD_INFERENCE_ALIASES: dict[str, str] = {
    "all-minilm-l6-v2": "sentence-transformers/all-MiniLM-L6-v2",
    "sentence-transformers/all-minilm-l6-v2": "sentence-transformers/all-MiniLM-L6-v2",
}


@dataclass
class QueryResult:
    query_id: str
    query_text: str
    expected_job_ids: list[str]
    expected_scores: dict[str, float | None] = field(default_factory=dict)
    top_noise_score: float | None = None
    all_missing: list[str] = field(default_factory=list)


def _is_local_qdrant() -> bool:
    settings = get_settings()
    host = urlparse(settings.qdrant_url).hostname or ""
    return settings.qdrant_api_key is None and host in {"localhost", "127.0.0.1", "::1"}


def _uses_cloud_inference() -> bool:
    settings = get_settings()
    host = urlparse(settings.qdrant_url).hostname or ""
    is_cloud_host = host not in {"", "localhost", "127.0.0.1", "::1"}
    return is_cloud_host and settings.qdrant_api_key is not None


def _get_comparison_client() -> QdrantClient:
    """Return a Qdrant client configured for this spike's embedding path."""
    settings = get_settings()
    if _uses_cloud_inference():
        print(
            "Qdrant Cloud detected — using Cloud Inference "
            "(cloud_inference=True on QdrantClient)."
        )
        return QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            cloud_inference=True,
            check_compatibility=False,
        )
    print("Local Qdrant detected — using client-side FastEmbed.")
    return get_qdrant_client()


def _validate_qdrant_config() -> None:
    settings = get_settings()
    host = urlparse(settings.qdrant_url).hostname or ""
    is_cloud_host = host not in {"", "localhost", "127.0.0.1", "::1"}
    if is_cloud_host and settings.qdrant_api_key is None:
        raise ValueError(
            f"QDRANT_URL points at Qdrant Cloud ({settings.qdrant_url}) but "
            "QDRANT_API_KEY is not set. Add your cluster API key to .env, or "
            "point QDRANT_URL at local Qdrant (http://localhost:6333) for "
            "FastEmbed-only comparison."
        )


def _fastembed_supported_models() -> set[str]:
    return {entry["model"] for entry in TextEmbedding.list_supported_models()}


def _resolve_model_name(model: str, *, cloud_mode: bool) -> str:
    if cloud_mode:
        alias = _CLOUD_INFERENCE_ALIASES.get(model.lower())
        if alias:
            print(f"Resolved Cloud Inference alias: {model!r} -> {alias!r}")
            return alias
        return model

    supported = _fastembed_supported_models()
    if model in supported:
        return model

    alias = _FASTEMBED_ALIASES.get(model.lower())
    if alias and alias in supported:
        print(f"Resolved local FastEmbed alias: {model!r} -> {alias!r}")
        return alias

    raise ValueError(
        f"Model {model!r} is not available in local FastEmbed. "
        f"Supported locally: {sorted(supported)}. "
        "Point QDRANT_URL/QDRANT_API_KEY at Qdrant Cloud to use "
        "intfloat/multilingual-e5-small and other Cloud Inference models."
    )


def _collection_name_for_model(model: str) -> str:
    safe = model.replace("/", "_").replace(".", "_")
    return f"JOBS_COMPARE_{safe.upper()}"


def _load_golden_queries() -> dict:
    if not GOLDEN_QUERIES_PATH.exists():
        raise FileNotFoundError(
            f"Could not find golden_queries.json at {GOLDEN_QUERIES_PATH}"
        )
    return json.loads(GOLDEN_QUERIES_PATH.read_text(encoding="utf-8"))


def _load_golden_jobs() -> list[JobOpportunity]:
    if not GOLDEN_JOBS_PATH.exists():
        raise FileNotFoundError(
            f"Could not find golden_jobs.json at {GOLDEN_JOBS_PATH}"
        )
    payload = json.loads(GOLDEN_JOBS_PATH.read_text(encoding="utf-8"))
    return [JobOpportunity.model_validate(job) for job in payload]


def _seed_collection_for_model(
    client: QdrantClient, collection_name: str, model: str
) -> None:
    """Create + seed a throwaway collection using `model` for embedding.

    NOTE: get_settings() is an lru_cache'd singleton (db/settings.py). We
    mutate the cached Settings instance's embedding_model in place for the
    duration of seeding + querying this collection, then restore it. This is
    a deliberate, narrow hack for a standalone comparison script — do not
    reuse this pattern inside the application itself.
    """
    settings = get_settings()
    original_model = settings.embedding_model
    settings.embedding_model = model
    try:
        drop_db(client, collection_name)
        create_collection(client, collection_name)
        jobs = _load_golden_jobs()
        job_count = len(jobs)
        print(f"\n=== Seeding {collection_name!r}: {job_count} jobs, {model!r} ===")
        load_jobs_into_qdrant(
            db_client=client,
            collection_name=collection_name,
            jobs=jobs,
        )
        info = client.get_collection(collection_name)
        print(f"Collection status: {info.status}, points: {info.points_count}")
    finally:
        settings.embedding_model = original_model


def _run_golden_queries_against(
    client: QdrantClient,
    collection_name: str,
    model: str,
    golden_set: dict,
) -> list[QueryResult]:
    settings = get_settings()
    original_model = settings.embedding_model
    settings.embedding_model = model
    results: list[QueryResult] = []
    try:
        top_k = golden_set["top_k"]
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
                expected_job_ids=case["expected_job_ids"],
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
    finally:
        settings.embedding_model = original_model
    return results


def _print_comparison_table(
    model_a: str,
    results_a: list[QueryResult],
    model_b: str,
    results_b: list[QueryResult],
) -> None:
    print("\n" + "=" * 100)
    print(f"COMPARISON: {model_a}  vs  {model_b}")
    print("=" * 100)

    by_id_b = {r.query_id: r for r in results_b}

    for r_a in results_a:
        r_b = by_id_b.get(r_a.query_id)
        print(f"\n--- Query [{r_a.query_id}]: {r_a.query_text!r} ---")
        print(f"Expected job(s): {r_a.expected_job_ids}")

        for job_id in r_a.expected_job_ids:
            score_a = r_a.expected_scores.get(job_id)
            score_b = r_b.expected_scores.get(job_id) if r_b else None
            print(
                f"  job={job_id:<20} "
                f"{model_a}={score_a if score_a is not None else 'MISSING':<10} "
                f"{model_b}={score_b if score_b is not None else 'MISSING'}"
            )

        noise_a = r_a.top_noise_score
        noise_b = r_b.top_noise_score if r_b else None
        print(f"  top noise score:  {model_a}={noise_a}   {model_b}={noise_b}")

        if r_a.all_missing:
            print(f"  ⚠️  {model_a} MISSED: {r_a.all_missing}")
        if r_b and r_b.all_missing:
            print(f"  ⚠️  {model_b} MISSED: {r_b.all_missing}")

    print("\n" + "=" * 100)
    print("SUMMARY")
    print("=" * 100)
    for label, results in ((model_a, results_a), (model_b, results_b)):
        all_expected_scores = [
            score
            for r in results
            for score in r.expected_scores.values()
            if score is not None
        ]
        all_noise_scores = [
            r.top_noise_score for r in results if r.top_noise_score is not None
        ]
        missed_count = sum(len(r.all_missing) for r in results)
        min_expected = min(all_expected_scores) if all_expected_scores else None
        max_noise = max(all_noise_scores) if all_noise_scores else None
        print(f"\n{label}:")
        print(f"  Missed expected hits: {missed_count}")
        print(f"  Min expected-hit score (CHAT_SOURCE_MIN_SCORE floor): {min_expected}")
        print(f"  Max noise-hit score (should sit below the floor above): {max_noise}")
        if min_expected is not None and max_noise is not None:
            margin = min_expected - max_noise
            verdict = (
                "✅ clean separation"
                if margin > 0
                else "⚠️  OVERLAP — recalibration will be lossy"
            )
            print(f"  Separation margin: {margin:.4f} {verdict}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        nargs=2,
        default=DEFAULT_MODELS,
        metavar=("MODEL_A", "MODEL_B"),
        help=f"Two embedding model names to compare. Default: {DEFAULT_MODELS}",
    )
    parser.add_argument(
        "--keep-collections",
        action="store_true",
        help="Keep comparison collections after running (default: delete both).",
    )
    args = parser.parse_args()

    try:
        _validate_qdrant_config()
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    local_mode = _is_local_qdrant()
    cloud_mode = _uses_cloud_inference()
    if cloud_mode:
        print("Resolving model names for Qdrant Cloud Inference.")
    elif local_mode:
        print("Resolving model names against local FastEmbed registry.")

    try:
        model_a = _resolve_model_name(args.models[0], cloud_mode=cloud_mode)
        model_b = _resolve_model_name(args.models[1], cloud_mode=cloud_mode)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    client = _get_comparison_client()
    golden_set = _load_golden_queries()

    collection_a = _collection_name_for_model(model_a)
    collection_b = _collection_name_for_model(model_b)

    for collection_name, model in ((collection_a, model_a), (collection_b, model_b)):
        if client.collection_exists(collection_name):
            print(f"Dropping pre-existing '{collection_name}' before reseeding...")
            client.delete_collection(collection_name)
        _seed_collection_for_model(client, collection_name, model)

    print("\nRunning golden queries against both collections...")
    results_a = _run_golden_queries_against(client, collection_a, model_a, golden_set)
    results_b = _run_golden_queries_against(client, collection_b, model_b, golden_set)

    _print_comparison_table(model_a, results_a, model_b, results_b)

    if not args.keep_collections:
        print(f"\nCleaning up: dropping '{collection_a}' and '{collection_b}'...")
        client.delete_collection(collection_a)
        client.delete_collection(collection_b)
    else:
        print(f"\nKept collections '{collection_a}' and '{collection_b}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
