from types import SimpleNamespace
from unittest.mock import patch

import requests
import responses
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.main import app, create_app
from tests.api.conftest import api_settings_namespace
from the_hub_client.models import CountryCode
from the_hub_client.utils import HUB_BASE_URL, JOB_LISTINGS_ENDPOINT_ROUTE

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_middleware_configured_from_settings(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("QDRANT_COLLECTION_NAME", "JOBS_ON_THE_HUB")
    monkeypatch.setenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    monkeypatch.setenv(
        "CORS_ALLOWED_ORIGINS",
        "http://example.com,http://other.com",
    )

    test_app = create_app()
    cors = next(m for m in test_app.user_middleware if m.cls is CORSMiddleware)

    assert cors.kwargs["allow_origins"] == ["http://example.com", "http://other.com"]
    assert cors.kwargs["allow_credentials"] is False
    assert cors.kwargs["allow_methods"] == ["GET", "POST", "OPTIONS"]
    assert cors.kwargs["allow_headers"] == ["Content-Type", "Accept"]


def test_cors_preflight_allows_configured_origin():
    response = client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


@responses.activate
def test_jobs_stats_returns_openings(load_fixture):
    payload = load_fixture("jobs_listing_summary.json")
    responses.add(
        responses.GET,
        f"{HUB_BASE_URL}{JOB_LISTINGS_ENDPOINT_ROUTE}?countryCode=SE",
        json=payload,
    )

    response = client.get("/jobs/stats", params={"country": "SE"})

    assert response.status_code == 200
    body = response.json()
    assert body["total_jobs"] == 120
    assert body["remote_jobs"] == 30
    assert body["jobs_per_role"]["backend_developer"] == 19


def test_jobs_stats_rejects_invalid_country():
    response = client.get("/jobs/stats", params={"country": "XX"})

    assert response.status_code == 422


@responses.activate
def test_jobs_stats_returns_502_when_hub_is_down():
    responses.add(
        responses.GET,
        f"{HUB_BASE_URL}{JOB_LISTINGS_ENDPOINT_ROUTE}?countryCode=DK",
        body=requests.ConnectionError("connection failed"),
    )

    response = client.get("/jobs/stats", params={"country": "DK"})

    assert response.status_code == 502
    assert response.json()["detail"] == "The Hub API is unavailable."


def test_jobs_search_rejects_empty_query():
    response = client.get("/jobs/search", params={"q": ""})

    assert response.status_code == 422


def test_jobs_search_rejects_invalid_country():
    response = client.get(
        "/jobs/search", params={"q": "python developer", "country": "XX"}
    )

    assert response.status_code == 422


@patch("api.main.query_jobs_in_qdrant")
@patch("api.main.get_qdrant_client")
@patch("api.main.get_settings")
def test_jobs_search_passes_country_filter_to_query(
    mock_get_settings, mock_get_qdrant_client, mock_query_jobs
):
    mock_get_settings.return_value = api_settings_namespace()
    mock_get_qdrant_client.return_value = object()
    mock_query_jobs.return_value = SimpleNamespace(points=[])

    response = client.get(
        "/jobs/search",
        params={"q": "python developer", "country": "DK"},
    )

    assert response.status_code == 200
    mock_query_jobs.assert_called_once()
    _, kwargs = mock_query_jobs.call_args
    assert kwargs["country"] == CountryCode.DENMARK


@patch("api.main.query_jobs_in_qdrant")
@patch("api.main.get_qdrant_client")
@patch("api.main.get_settings")
def test_jobs_search_passes_remote_filter_to_query(
    mock_get_settings, mock_get_qdrant_client, mock_query_jobs
):
    mock_get_settings.return_value = api_settings_namespace()
    mock_get_qdrant_client.return_value = object()
    mock_query_jobs.return_value = SimpleNamespace(points=[])

    response = client.get(
        "/jobs/search",
        params={"q": "python developer", "remote": "true"},
    )

    assert response.status_code == 200
    mock_query_jobs.assert_called_once()
    _, kwargs = mock_query_jobs.call_args
    assert kwargs["remote"] is True


@patch("api.main.query_jobs_in_qdrant")
@patch("api.main.get_qdrant_client")
@patch("api.main.get_settings")
def test_jobs_search_returns_clean_json(
    mock_get_settings, mock_get_qdrant_client, mock_query_jobs
):
    mock_get_settings.return_value = api_settings_namespace()
    mock_get_qdrant_client.return_value = object()
    mock_query_jobs.return_value = SimpleNamespace(
        points=[
            SimpleNamespace(
                score=0.91,
                payload={
                    "job_url_identifier": "job-123",
                    "job_title": "Backend Developer",
                    "company": "Acme",
                    "job_role": "Backend Developer",
                    "Country": "Denmark",
                    "location": "Copenhagen",
                    "Remote": True,
                    "Salary Type": "paid",
                    "Salary": "Competitive",
                    "Equity": "Yes",
                },
            )
        ]
    )

    response = client.get("/jobs/search", params={"q": "python developer"})

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "python developer"
    assert len(body["results"]) == 1
    assert body["results"][0] == {
        "score": 0.91,
        "job_id": "job-123",
        "job_title": "Backend Developer",
        "company": "Acme",
        "job_role": "Backend Developer",
        "country": "Denmark",
        "location": "Copenhagen",
        "remote": True,
        "salary_type": "paid",
        "salary": "Competitive",
        "equity": "Yes",
    }
    mock_query_jobs.assert_called_once()


@patch("api.main.query_jobs_in_qdrant")
@patch("api.main.get_qdrant_client")
@patch("api.main.get_settings")
def test_jobs_search_omits_job_title_and_company_when_not_in_payload(
    mock_get_settings, mock_get_qdrant_client, mock_query_jobs
):
    mock_get_settings.return_value = api_settings_namespace()
    mock_get_qdrant_client.return_value = object()
    mock_query_jobs.return_value = SimpleNamespace(
        points=[
            SimpleNamespace(
                score=0.91,
                payload={
                    "job_url_identifier": "job-legacy",
                    "job_role": "Backend Developer",
                    "Country": "Denmark",
                    "location": "Copenhagen",
                    "Remote": True,
                    "Salary Type": "paid",
                    "Salary": "Competitive",
                    "Equity": "Yes",
                },
            )
        ]
    )

    response = client.get("/jobs/search", params={"q": "python developer"})

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["job_title"] is None
    assert result["company"] is None


@patch("api.main.get_qdrant_client", side_effect=ConnectionError("refused"))
@patch("api.main.get_settings")
def test_jobs_search_returns_503_when_qdrant_is_unavailable(
    mock_get_settings, mock_get_qdrant_client
):
    mock_get_settings.return_value = api_settings_namespace()

    response = client.get("/jobs/search", params={"q": "python developer"})

    assert response.status_code == 503
    assert response.json()["detail"] == "Qdrant is unavailable."


@patch(
    "api.main.get_settings",
    side_effect=ValidationError.from_exception_data("Settings", []),
)
def test_jobs_search_returns_500_when_configuration_is_invalid(mock_get_settings):
    response = client.get("/jobs/search", params={"q": "python developer"})

    assert response.status_code == 500
    assert response.json()["detail"] == "Server configuration is invalid."


@patch("api.main.query_jobs_in_qdrant")
@patch("api.main.get_qdrant_client")
@patch("api.main.get_settings")
def test_jobs_search_returns_502_when_payload_is_missing_fields(
    mock_get_settings, mock_get_qdrant_client, mock_query_jobs
):
    mock_get_settings.return_value = api_settings_namespace()
    mock_get_qdrant_client.return_value = object()
    mock_query_jobs.return_value = SimpleNamespace(
        points=[
            SimpleNamespace(
                score=0.91,
                payload={
                    "job_url_identifier": "job-123",
                    "job_role": "Backend Developer",
                    "Country": "Denmark",
                    "location": "Copenhagen",
                    "Remote": True,
                    "Salary Type": "paid",
                    "Salary": "Competitive",
                },
            )
        ]
    )

    response = client.get("/jobs/search", params={"q": "python developer"})

    assert response.status_code == 502
    assert (
        response.json()["detail"] == "Search result payload is missing required fields."
    )
