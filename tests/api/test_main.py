from types import SimpleNamespace
from unittest.mock import patch

import requests
import responses
from fastapi.testclient import TestClient

from api.main import app
from the_hub_client.utils import HUB_BASE_URL, JOB_LISTINGS_ENDPOINT_ROUTE

client = TestClient(app)


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


@patch("api.main.query_jobs_in_qdrant")
@patch("api.main.get_qdrant_client")
@patch("api.main.get_settings")
def test_jobs_search_returns_clean_json(
    mock_get_settings, mock_get_qdrant_client, mock_query_jobs
):
    mock_get_settings.return_value = SimpleNamespace(
        qdrant_collection_name="JOBS_ON_THE_HUB"
    )
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
        "job_role": "Backend Developer",
        "country": "Denmark",
        "location": "Copenhagen",
        "remote": True,
        "salary_type": "paid",
        "salary": "Competitive",
        "equity": "Yes",
    }
    mock_query_jobs.assert_called_once()


@patch("api.main.get_qdrant_client", side_effect=ConnectionError("refused"))
def test_jobs_search_returns_503_when_qdrant_is_unavailable(mock_get_qdrant_client):
    response = client.get("/jobs/search", params={"q": "python developer"})

    assert response.status_code == 503
    assert response.json()["detail"] == "Qdrant is unavailable."
