from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app
from tests.api_auth import AUTH_HEADERS, TEST_API_KEY
from tests.mock_settings import api_settings_namespace

client = TestClient(app, headers=AUTH_HEADERS)


@patch("api.main.query_jobs_in_qdrant")
@patch("api.main.get_qdrant_client")
@patch("api.main.get_settings")
def test_protected_route_accepts_valid_api_key(
    mock_get_settings, mock_get_qdrant_client, mock_query_jobs
):
    from types import SimpleNamespace

    mock_get_settings.return_value = api_settings_namespace(
        hubster_api_keys={TEST_API_KEY}
    )
    mock_get_qdrant_client.return_value = object()
    mock_query_jobs.return_value = SimpleNamespace(points=[])

    response = client.get("/jobs/search", params={"q": "backend"})

    assert response.status_code == 200


def test_protected_route_rejects_missing_authorization_header():
    unauthenticated = TestClient(app)

    response = unauthenticated.get("/jobs/search", params={"q": "backend"})

    assert response.status_code == 401
    assert response.json()["detail"] == {
        "message": "Missing or invalid Authorization header.",
        "code": "missing_api_key",
    }


def test_protected_route_rejects_invalid_api_key():
    invalid_client = TestClient(
        app, headers={"Authorization": "Bearer not-a-valid-key"}
    )

    response = invalid_client.get("/jobs/search", params={"q": "backend"})

    assert response.status_code == 401
    assert response.json()["detail"] == {
        "message": "API key is not authorized.",
        "code": "invalid_api_key",
    }


def test_health_remains_unauthenticated():
    unauthenticated = TestClient(app)

    response = unauthenticated.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
