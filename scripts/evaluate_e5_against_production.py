"""ALE-138 follow-up: Evaluate intfloat/multilingual-e5-small against the REAL
production corpus (JOBS_ON_THE_HUB), not the 7-job fixture set.

Why this is a different script, not a rerun of compare_embedding_models.py:
real jobs don't have expected_job_ids ground truth the way golden_queries.json
fixtures do, so this can't do hit/miss scoring. Instead it:

  1. Scrolls the existing production collection (READ-ONLY — no writes, no
     deletes against QDRANT_COLLECTION_NAME, ever) to pull every point's
     already-stored `document_text` + metadata. No re-scraping The Hub.
  2. Re-embeds those same texts under E5 into a throwaway collection
     (JOBS_COMPARE_E5_PROD by default).
  3. Runs a query set (the 6 golden query texts from golden_queries.json, plus
     a few broader ones spanning countries/roles/remote) against it.
  4. Prints, per query: top-5 results with job title/company/country/score
     (for manual eyeballing, same spirit as ALE-92's manual verification
     methodology), plus an aggregate score-distribution summary across all
     queries — top-1 scores, rank-5 scores, min/max/mean — to inform a real
     CHAT_SOURCE_MIN_SCORE recalibration.

Usage:

    uv run python scripts/evaluate_e5_against_production.py
    uv run python scripts/evaluate_e5_against_production.py --keep-collection
    uv run python scripts/evaluate_e5_against_production.py --limit 100

Requires .env pointing at Qdrant Cloud (QDRANT_URL, QDRANT_API_KEY,
QDRANT_COLLECTION_NAME=JOBS_ON_THE_HUB). Uses cloud_inference=True for E5.

SAFETY: this script only ever calls read operations (scroll, get_collection,
query_points) against settings.qdrant_collection_name. All writes/deletes
target only the throwaway --collection-name value.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from qdrant_client import QdrantClient, models  # noqa: E402

from db import create_collection, get_settings, query_jobs_in_qdrant  # noqa: E402
from db.database import get_vector_name, job_id_to_point_id  # noqa: E402
from db.settings import uses_cloud_inference  # noqa: E402
from the_hub_client import CountryCode  # noqa: E402

E5_MODEL = "intfloat/multilingual-e5-small"
DEFAULT_COMPARE_COLLECTION = "JOBS_COMPARE_E5_PROD"
GOLDEN_QUERIES_PATH = _REPO_ROOT / "tests" / "fixtures" / "golden_queries.json"
SCROLL_BATCH_SIZE = 100
REEMBED_BATCH_SIZE = 25

# Broader queries for real-scale coverage (not in golden_queries.json).
EXTENDED_QUERIES: list[tuple[str, CountryCode | None]] = [
    ("remote software engineer", None),
    ("data scientist in Norway", CountryCode.NORWAY),
    ("DevOps or infrastructure engineer", None),
    ("customer support role in Finland", CountryCode.FINLAND),
]


@dataclass
class ProductionQueryResult:
    query_text: str
    country: CountryCode | None
    top_hits: list[tuple[float, str, str, str]] = field(default_factory=list)


def _validate_config() -> None:
    if not uses_cloud_inference():
        raise ValueError(
            f"{E5_MODEL} requires Qdrant Cloud Inference. "
            "Point QDRANT_URL and QDRANT_API_KEY at your Cloud cluster."
        )


def _get_eval_client() -> QdrantClient:
    settings = get_settings()
    print("Using Qdrant Cloud Inference (cloud_inference=True).")
    return QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        cloud_inference=True,
        check_compatibility=False,
    )


def _load_query_texts() -> list[tuple[str, CountryCode | None]]:
    golden = json.loads(GOLDEN_QUERIES_PATH.read_text(encoding="utf-8"))
    queries: list[tuple[str, CountryCode | None]] = []
    for case in golden["queries"]:
        country_filter = case.get("country")
        country_code = CountryCode(country_filter) if country_filter else None
        queries.append((case["query"], country_code))
    queries.extend(EXTENDED_QUERIES)
    return queries


def _scroll_production_corpus(client: QdrantClient, collection_name: str) -> list[dict]:
    """READ-ONLY scroll of the production collection. No writes here, ever."""
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
                    "job_title": payload.get("job_title"),
                    "company": payload.get("company"),
                    "Country": payload.get("Country"),
                    "Remote": payload.get("Remote"),
                }
            )
        print(f"  scrolled {len(points)} points so far...")
        if next_offset is None:
            break
    print(f"Done: {len(points)} points pulled from production (read-only).")
    return points


def _reembed_into_comparison_collection(
    client: QdrantClient,
    compare_collection: str,
    production_points: list[dict],
    limit: int | None,
) -> None:
    settings = get_settings()
    original_model = settings.embedding_model
    settings.embedding_model = E5_MODEL
    try:
        if client.collection_exists(compare_collection):
            print(f"Dropping pre-existing {compare_collection!r}...")
            client.delete_collection(compare_collection)
        create_collection(client, compare_collection)
        vector_name = get_vector_name(client, compare_collection)

        to_embed = production_points[:limit] if limit else production_points
        print(f"Re-embedding {len(to_embed)} jobs under {E5_MODEL}...")

        for batch_start in range(0, len(to_embed), REEMBED_BATCH_SIZE):
            batch = to_embed[batch_start : batch_start + REEMBED_BATCH_SIZE]
            points = [
                models.PointStruct(
                    id=job_id_to_point_id(item["job_url_identifier"]),
                    vector={
                        vector_name: models.Document(
                            text=item["document_text"], model=E5_MODEL
                        )
                    },
                    payload=item,
                )
                for item in batch
            ]
            client.upsert(collection_name=compare_collection, points=points)
            print(f"  upserted {batch_start + len(batch)}/{len(to_embed)}")

        info = client.get_collection(compare_collection)
        print(f"Comparison collection ready: {info.points_count} points.")
    finally:
        settings.embedding_model = original_model


def _run_queries(
    client: QdrantClient,
    compare_collection: str,
    query_texts: list[tuple[str, CountryCode | None]],
) -> list[ProductionQueryResult]:
    settings = get_settings()
    original_model = settings.embedding_model
    settings.embedding_model = E5_MODEL
    results: list[ProductionQueryResult] = []
    try:
        for query_text, country in query_texts:
            response = query_jobs_in_qdrant(
                db_client=client,
                collection_name=compare_collection,
                query_text=query_text,
                limit=5,
                country=country,
            )
            result = ProductionQueryResult(query_text=query_text, country=country)
            for hit in response.points:
                payload = hit.payload or {}
                result.top_hits.append(
                    (
                        hit.score,
                        payload.get("job_title", "?"),
                        payload.get("company", "?"),
                        payload.get("Country", "?"),
                    )
                )
            results.append(result)
    finally:
        settings.embedding_model = original_model
    return results


def _print_results(results: list[ProductionQueryResult]) -> None:
    print("\n" + "=" * 100)
    print(f"E5 ({E5_MODEL}) — top-5 results against REAL production corpus")
    print("=" * 100)

    all_top1_scores: list[float] = []
    all_rank5_scores: list[float] = []

    for result in results:
        country_label = f" [country={result.country.value}]" if result.country else ""
        print(f"\n--- Query: {result.query_text!r}{country_label} ---")
        if not result.top_hits:
            print("  (no hits returned)")
            continue
        for rank, hit in enumerate(result.top_hits, start=1):
            score, title, company, country = hit
            print(f"  #{rank}  score={score:.4f}  {title} @ {company} ({country})")
        all_top1_scores.append(result.top_hits[0][0])
        if len(result.top_hits) >= 5:
            all_rank5_scores.append(result.top_hits[4][0])

    print("\n" + "=" * 100)
    print("AGGREGATE SCORE DISTRIBUTION (for CHAT_SOURCE_MIN_SCORE recalibration)")
    print("=" * 100)
    if all_top1_scores:
        print(f"Top-1 scores across {len(all_top1_scores)} queries:")
        print(
            f"  min={min(all_top1_scores):.4f}  max={max(all_top1_scores):.4f}  "
            f"mean={statistics.mean(all_top1_scores):.4f}  "
            f"median={statistics.median(all_top1_scores):.4f}"
        )
    if all_rank5_scores:
        print(f"\nRank-5 scores across {len(all_rank5_scores)} queries:")
        print(
            f"  min={min(all_rank5_scores):.4f}  max={max(all_rank5_scores):.4f}  "
            f"mean={statistics.mean(all_rank5_scores):.4f}  "
            f"median={statistics.median(all_rank5_scores):.4f}"
        )

    print(
        "\nManual review reminder: for each query above, does #1 (and ideally #2-3) "
        "actually look relevant? Real jobs have no expected_job_ids — "
        "human judgment on title/company relevance is the signal here."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--collection-name",
        default=DEFAULT_COMPARE_COLLECTION,
        help=f"Throwaway E5 collection (default: {DEFAULT_COMPARE_COLLECTION}).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Re-embed only the first N production points (smoke test).",
    )
    parser.add_argument(
        "--keep-collection",
        action="store_true",
        help="Do not delete the comparison collection after running.",
    )
    args = parser.parse_args()

    try:
        _validate_config()
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    client = _get_eval_client()
    settings = get_settings()
    query_texts = _load_query_texts()

    prod_collection = settings.qdrant_collection_name
    production_points = _scroll_production_corpus(client, prod_collection)
    if not production_points:
        print("No points found in production collection — nothing to compare.")
        return 1

    _reembed_into_comparison_collection(
        client, args.collection_name, production_points, args.limit
    )

    results = _run_queries(client, args.collection_name, query_texts)
    _print_results(results)

    if not args.keep_collection:
        print(f"\nCleaning up: dropping {args.collection_name!r}...")
        client.delete_collection(args.collection_name)
    else:
        print(f"\nKept {args.collection_name!r} for further manual inspection.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
