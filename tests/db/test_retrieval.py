import json
from pathlib import Path

import pytest

from db.database import query_jobs_in_qdrant
from db.settings import DEFAULT_CHAT_SOURCE_MIN_SCORE
from the_hub_client.models import (
    EU_COUNTRY_FILTER_EXCLUSIONS,
    CountryCode,
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
    """Calibration guard: /chat floor keeps every golden expected hit.

    Uses fixture_chat_source_min_score from golden_queries.json when set — the
    7-job dev corpus scores below the production E5 band (ADR-0014 / ALE-138).
    """
    client, collection_name = retrieval_qdrant
    golden_set = _load_golden_queries()
    top_k = golden_set["top_k"]
    min_score = golden_set.get(
        "fixture_chat_source_min_score", DEFAULT_CHAT_SOURCE_MIN_SCORE
    )

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
            if hit.score >= min_score
        ]
        missing = [
            job_id
            for job_id in case["expected_job_ids"]
            if job_id not in surviving_job_ids
        ]

        assert not missing, (
            f"Golden query '{case['id']}' lost expected job(s) {missing} "
            f"below CHAT_SOURCE_MIN_SCORE={min_score}. "
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
def test_eu_country_filter_with_remote_excludes_na_remote_jobs(retrieval_qdrant):
    client, collection_name = retrieval_qdrant

    results = query_jobs_in_qdrant(
        db_client=client,
        collection_name=collection_name,
        query_text="remote backend engineer building APIs",
        limit=10,
        country=CountryCode.EUROPE,
        remote=True,
    )
    returned_job_ids = _job_ids_from_hits(results.points)

    assert "stu345" not in returned_job_ids


def _scores_by_job_id(hits) -> dict[str, float]:
    return {hit.payload["job_url_identifier"]: hit.score for hit in hits}


def _assert_role_confusion_case(case: dict, hits, min_score: float) -> None:
    """Expected role match must outrank confusers and survive the score floor."""
    returned_job_ids = _job_ids_from_hits(hits)
    scores = _scores_by_job_id(hits)
    case_id = case["id"]

    missing = [
        job_id for job_id in case["expected_job_ids"] if job_id not in returned_job_ids
    ]
    assert not missing, (
        f"Role-confusion case '{case_id}' missed expected job(s) {missing} "
        f"in top results. Returned: {returned_job_ids}"
    )

    expected_scores = [
        scores[job_id] for job_id in case["expected_job_ids"] if job_id in scores
    ]
    assert expected_scores, (
        f"Role-confusion case '{case_id}' has no scores for expected jobs."
    )
    best_expected_score = max(expected_scores)
    assert best_expected_score >= min_score, (
        f"Role-confusion case '{case_id}' expected job(s) scored below "
        f"CHAT_SOURCE_MIN_SCORE={min_score}. Scores: {scores}"
    )

    for confuser_id in case["confuser_job_ids"]:
        confuser_score = scores.get(confuser_id)
        if confuser_score is None:
            continue
        assert confuser_score < best_expected_score, (
            f"Role-confusion case '{case_id}': confuser {confuser_id} "
            f"({confuser_score:.3f}) outranks expected job(s) "
            f"({best_expected_score:.3f})."
        )
        assert confuser_score < min_score, (
            f"Role-confusion case '{case_id}': confuser {confuser_id} "
            f"({confuser_score:.3f}) survives CHAT_SOURCE_MIN_SCORE={min_score}."
        )


@pytest.mark.retrieval
@pytest.mark.xfail(
    reason="ALE-151: role confusion (frontend vs Sales/BD in Copenhagen); "
    "re-run without xfail after ALE-143 (ADR-0010 hybrid search) ships.",
    strict=True,
)
def test_role_confusion_cases(retrieval_qdrant):
    """Regression guard for role/topic confusion above CHAT_SOURCE_MIN_SCORE."""
    client, collection_name = retrieval_qdrant
    golden_set = _load_golden_queries()
    top_k = golden_set["top_k"]

    for case in golden_set.get("role_confusion_cases", []):
        min_score = case.get("min_score", DEFAULT_CHAT_SOURCE_MIN_SCORE)
        results = query_jobs_in_qdrant(
            db_client=client,
            collection_name=collection_name,
            query_text=case["query"],
            limit=top_k,
        )
        _assert_role_confusion_case(case, results.points, min_score)


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
