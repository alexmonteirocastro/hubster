import json
from pathlib import Path

import pytest

from db.database import query_jobs_in_qdrant
from db.settings import DEFAULT_CHAT_SOURCE_MIN_SCORE
from the_hub_client.models import (
    CountryCode,
    EU_COUNTRY_FILTER_EXCLUSIONS,
    country_code_to_hub_country_name,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def _load_golden_queries() -> dict:
    return json.loads(
        (FIXTURES_DIR / "golden_queries.json").read_text(encoding="utf-8")
    )


def _job_ids_from_hits(hits) -> list[str]:
    return [hit.payload["job_url_identifier"] for hit in hits]


@pytest.mark.retrieval
def test_golden_queries_hit_expected_jobs_in_top_k(retrieval_qdrant):
    client, collection_name = retrieval_qdrant
    golden_set = _load_golden_queries()
    top_k = golden_set["top_k"]

    for case in golden_set["queries"]:
        country_filter = case.get("country")
        country_code = CountryCode(country_filter) if country_filter else None
        country_name = (
            country_code_to_hub_country_name(country_code) if country_code else None
        )
        results = query_jobs_in_qdrant(
            db_client=client,
            collection_name=collection_name,
            query_text=case["query"],
            limit=top_k,
            country=country_code,
        )
        returned_job_ids = _job_ids_from_hits(results.points)
        missing = [
            job_id
            for job_id in case["expected_job_ids"]
            if job_id not in returned_job_ids
        ]

        assert not missing, (
            f"Golden query '{case['id']}' missed expected job(s) {missing} "
            f"in top-{top_k}. Returned: {returned_job_ids}"
        )

        if country_code == CountryCode.EUROPE:
            forbidden_countries = set(EU_COUNTRY_FILTER_EXCLUSIONS)
            out_of_scope = [
                hit.payload.get("Country")
                for hit in results.points
                if hit.payload.get("Country") in forbidden_countries
            ]
            assert not out_of_scope, (
                f"Golden query '{case['id']}' returned excluded job(s) "
                f"with Country={out_of_scope} when filtering for EU."
            )
        elif country_name:
            out_of_country = [
                hit.payload.get("Country")
                for hit in results.points
                if hit.payload.get("Country") != country_name
            ]
            assert not out_of_country, (
                f"Golden query '{case['id']}' returned out-of-country job(s) "
                f"with Country={out_of_country} when filtering for {country_name}."
            )


@pytest.mark.retrieval
def test_golden_queries_expected_jobs_survive_chat_source_min_score(retrieval_qdrant):
    """Calibration guard: default /chat floor keeps every golden expected hit."""
    client, collection_name = retrieval_qdrant
    golden_set = _load_golden_queries()
    top_k = golden_set["top_k"]

    for case in golden_set["queries"]:
        country_filter = case.get("country")
        country_code = CountryCode(country_filter) if country_filter else None
        results = query_jobs_in_qdrant(
            db_client=client,
            collection_name=collection_name,
            query_text=case["query"],
            limit=top_k,
            country=country_code,
        )
        surviving_job_ids = [
            hit.payload["job_url_identifier"]
            for hit in results.points
            if hit.score >= DEFAULT_CHAT_SOURCE_MIN_SCORE
        ]
        missing = [
            job_id
            for job_id in case["expected_job_ids"]
            if job_id not in surviving_job_ids
        ]

        assert not missing, (
            f"Golden query '{case['id']}' lost expected job(s) {missing} "
            f"below CHAT_SOURCE_MIN_SCORE={DEFAULT_CHAT_SOURCE_MIN_SCORE}. "
            f"Surviving: {surviving_job_ids}"
        )


@pytest.mark.retrieval
def test_eu_country_filter_excludes_na_jobs(retrieval_qdrant):
    client, collection_name = retrieval_qdrant

    results = query_jobs_in_qdrant(
        db_client=client,
        collection_name=collection_name,
        query_text="remote backend engineer building APIs",
        limit=10,
        country=CountryCode.EUROPE,
    )
    returned_job_ids = _job_ids_from_hits(results.points)

    assert "stu345" not in returned_job_ids
    assert "mno456" in returned_job_ids


@pytest.mark.retrieval
def test_na_country_remote_jobs_surface_without_country_filter(retrieval_qdrant):
    client, collection_name = retrieval_qdrant

    results = query_jobs_in_qdrant(
        db_client=client,
        collection_name=collection_name,
        query_text="remote backend engineer building APIs",
        limit=10,
        remote=True,
    )
    returned_job_ids = _job_ids_from_hits(results.points)

    assert "stu345" in returned_job_ids
