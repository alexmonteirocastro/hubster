from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app
from db.settings import get_settings
from tests.api_auth import AUTH_HEADERS
from tests.mock_settings import api_settings_namespace

client = TestClient(app, headers=AUTH_HEADERS)

_OVERRIDE_API_KEY = "override-only-api-key"
_OVERRIDE_AUTH_HEADERS = {"Authorization": f"Bearer {_OVERRIDE_API_KEY}"}


@patch("api.main.query_jobs_in_qdrant")
@patch("api.main.get_qdrant_client")
def test_protected_route_accepts_valid_api_key(mock_get_qdrant_client, mock_query_jobs):
    from types import SimpleNamespace

    mock_settings = api_settings_namespace(hubster_api_keys={_OVERRIDE_API_KEY})
    app.dependency_overrides[get_settings] = lambda: mock_settings
    mock_get_qdrant_client.return_value = object()
    mock_query_jobs.return_value = SimpleNamespace(points=[])

    try:
        authed_client = TestClient(app, headers=_OVERRIDE_AUTH_HEADERS)
        response = authed_client.get("/jobs/search", params={"q": "backend"})
    finally:
        app.dependency_overrides.clear()

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


def test_protected_route_rejects_key_not_in_overridden_settings():
    mock_settings = api_settings_namespace(hubster_api_keys={"other-key"})
    app.dependency_overrides[get_settings] = lambda: mock_settings

    try:
        response = client.get("/jobs/search", params={"q": "backend"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_api_key"


def test_health_remains_unauthenticated():
    unauthenticated = TestClient(app)

    response = unauthenticated.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
