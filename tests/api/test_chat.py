import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.main import app, get_chat_generator
from db.settings import get_settings
from llm_client.base import Generator
from llm_client.context import NO_MATCHING_JOBS_MESSAGE
from llm_client.exceptions import GenerationRateLimitError, GenerationUnavailableError
from tests.api.conftest import api_settings_namespace
from the_hub_client.models import CountryCode

client = TestClient(app)


class FakeGenerator(Generator):
    def __init__(self, answer: str = "Grounded answer from fake generator."):
        self.answer = answer
        self.calls: list[tuple[str, str]] = []

    def generate(self, context: str, question: str) -> str:
        self.calls.append((context, question))
        return self.answer


@pytest.fixture(autouse=True)
def default_fake_chat_generator():
    app.dependency_overrides[get_chat_generator] = lambda: FakeGenerator()
    yield
    app.dependency_overrides.clear()


def test_main_does_not_import_gemini_directly():
    source = Path("api/main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "gemini" in node.module:
            raise AssertionError(
                "api/main.py must not import llm_client.gemini directly"
            )


@patch("api.main.query_jobs_in_qdrant")
@patch("api.main.get_qdrant_client")
@patch("api.main.get_settings")
def test_chat_returns_grounded_answer_via_injected_generator(
    mock_get_settings,
    mock_get_qdrant_client,
    mock_query_jobs,
):
    fake_generator = FakeGenerator()
    app.dependency_overrides[get_chat_generator] = lambda: fake_generator
    mock_get_settings.return_value = api_settings_namespace()
    mock_get_qdrant_client.return_value = object()
    mock_query_jobs.return_value = SimpleNamespace(
        points=[
            SimpleNamespace(
                score=0.88,
                payload={
                    "job_url_identifier": "job-123",
                    "job_title": "Backend Developer",
                    "company": "Acme",
                    "job_role": "Backend Developer",
                    "Country": "Denmark",
                    "location": "Copenhagen",
                    "document_text": "Job Title: Backend Developer\nCompany: Acme",
                },
            )
        ]
    )

    response = client.post("/chat", json={"question": "any backend roles?"})

    assert response.status_code == 200
    body = response.json()
    assert body["question"] == "any backend roles?"
    assert body["answer"] == "Grounded answer from fake generator."
    assert body["generated"] is True
    assert body["sources"] == [
        {
            "score": 0.88,
            "job_id": "job-123",
            "job_role": "Backend Developer",
            "document_text": "Job Title: Backend Developer\nCompany: Acme",
            "job_title": "Backend Developer",
            "company": "Acme",
            "country": "Denmark",
            "location": "Copenhagen",
        }
    ]
    assert len(fake_generator.calls) == 1
    context, question = fake_generator.calls[0]
    assert "Backend Developer" in context
    assert question == "any backend roles?"


@patch("api.main.query_jobs_in_qdrant")
@patch("api.main.get_qdrant_client")
@patch("api.main.get_settings")
def test_chat_omits_job_title_and_company_when_not_in_payload(
    mock_get_settings,
    mock_get_qdrant_client,
    mock_query_jobs,
):
    fake_generator = FakeGenerator()
    app.dependency_overrides[get_chat_generator] = lambda: fake_generator
    mock_get_settings.return_value = api_settings_namespace()
    mock_get_qdrant_client.return_value = object()
    mock_query_jobs.return_value = SimpleNamespace(
        points=[
            SimpleNamespace(
                score=0.88,
                payload={
                    "job_url_identifier": "job-legacy",
                    "job_role": "Backend Developer",
                    "document_text": "Job Title: Backend Developer\nCompany: Acme",
                },
            )
        ]
    )

    response = client.post("/chat", json={"question": "any backend roles?"})

    assert response.status_code == 200
    source = response.json()["sources"][0]
    assert source["job_title"] is None
    assert source["company"] is None


@patch("api.main.query_jobs_in_qdrant")
@patch("api.main.get_qdrant_client")
@patch("api.main.get_settings")
def test_chat_sources_match_context_passed_to_generator(
    mock_get_settings,
    mock_get_qdrant_client,
    mock_query_jobs,
):
    fake_generator = FakeGenerator()
    app.dependency_overrides[get_chat_generator] = lambda: fake_generator
    mock_get_settings.return_value = api_settings_namespace()
    mock_get_qdrant_client.return_value = object()
    mock_query_jobs.return_value = SimpleNamespace(
        points=[
            SimpleNamespace(
                score=0.9,
                payload={
                    "job_url_identifier": "job-with-text",
                    "job_role": "Backend Developer",
                    "Country": "Denmark",
                    "location": "Copenhagen",
                    "document_text": "Job Title: Backend Developer\nCompany: Acme",
                },
            ),
            SimpleNamespace(
                score=0.85,
                payload={
                    "job_url_identifier": "job-without-text",
                    "job_role": "N/A",
                    "document_text": "",
                },
            ),
        ]
    )

    response = client.post("/chat", json={"question": "backend roles?"})

    assert response.status_code == 200
    body = response.json()
    assert body["generated"] is True
    assert len(body["sources"]) == 1
    assert body["sources"][0]["job_id"] == "job-with-text"
    assert "job-without-text" not in [source["job_id"] for source in body["sources"]]
    context, _question = fake_generator.calls[0]
    assert "job-with-text" in context
    assert "job-without-text" not in context


@patch("api.main.query_jobs_in_qdrant")
@patch("api.main.get_qdrant_client")
@patch("api.main.get_settings")
def test_chat_skips_generation_when_retrieval_is_empty(
    mock_get_settings,
    mock_get_qdrant_client,
    mock_query_jobs,
):
    fake_generator = FakeGenerator()
    app.dependency_overrides[get_chat_generator] = lambda: fake_generator
    mock_get_settings.return_value = api_settings_namespace()
    mock_get_qdrant_client.return_value = object()
    mock_query_jobs.return_value = SimpleNamespace(points=[])

    response = client.post("/chat", json={"question": "underwater basket weaving?"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == NO_MATCHING_JOBS_MESSAGE
    assert body["generated"] is False
    assert body["sources"] == []
    assert body["applied_country"] is None
    assert body["applied_remote"] is None
    assert fake_generator.calls == []


@patch("api.main.query_jobs_in_qdrant")
@patch("api.main.get_qdrant_client")
@patch("api.main.get_settings")
def test_chat_applied_filters_present_when_no_usable_points(
    mock_get_settings,
    mock_get_qdrant_client,
    mock_query_jobs,
):
    fake_generator = FakeGenerator()
    app.dependency_overrides[get_chat_generator] = lambda: fake_generator
    mock_get_settings.return_value = api_settings_namespace()
    mock_get_qdrant_client.return_value = object()
    mock_query_jobs.return_value = SimpleNamespace(points=[])

    response = client.post(
        "/chat",
        json={"question": "backend roles?", "country": "FI", "remote": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["generated"] is False
    assert body["sources"] == []
    assert body["applied_country"] == "FI"
    assert body["applied_remote"] is True
    assert fake_generator.calls == []


@patch("api.main.query_jobs_in_qdrant")
@patch("api.main.get_qdrant_client")
@patch("api.main.get_settings")
def test_chat_skips_generation_when_document_text_is_missing(
    mock_get_settings,
    mock_get_qdrant_client,
    mock_query_jobs,
):
    fake_generator = FakeGenerator()
    app.dependency_overrides[get_chat_generator] = lambda: fake_generator
    mock_get_settings.return_value = api_settings_namespace()
    mock_get_qdrant_client.return_value = object()
    mock_query_jobs.return_value = SimpleNamespace(
        points=[
            SimpleNamespace(
                score=0.5,
                payload={
                    "job_url_identifier": "job-123",
                    "job_role": "Backend Developer",
                    "document_text": "",
                },
            )
        ]
    )

    response = client.post("/chat", json={"question": "backend roles?"})

    assert response.status_code == 200
    assert response.json()["generated"] is False
    assert fake_generator.calls == []


@patch("api.main.query_jobs_in_qdrant")
@patch("api.main.get_qdrant_client")
@patch("api.main.get_settings")
def test_chat_returns_429_when_generator_is_rate_limited(
    mock_get_settings,
    mock_get_qdrant_client,
    mock_query_jobs,
):
    class RateLimitedGenerator(Generator):
        def generate(self, context: str, question: str) -> str:
            raise GenerationRateLimitError("rate limited")

    app.dependency_overrides[get_chat_generator] = lambda: RateLimitedGenerator()
    mock_get_settings.return_value = api_settings_namespace()
    mock_get_qdrant_client.return_value = object()
    mock_query_jobs.return_value = SimpleNamespace(
        points=[
            SimpleNamespace(
                score=0.9,
                payload={
                    "job_url_identifier": "job-123",
                    "job_role": "Backend Developer",
                    "document_text": "Backend role in Copenhagen",
                },
            )
        ]
    )

    response = client.post("/chat", json={"question": "backend roles?"})

    assert response.status_code == 429
    assert "rate-limited" in response.json()["detail"].lower()


@patch("api.main.query_jobs_in_qdrant")
@patch("api.main.get_qdrant_client")
@patch("api.main.get_settings")
def test_chat_returns_502_when_generator_is_unavailable(
    mock_get_settings,
    mock_get_qdrant_client,
    mock_query_jobs,
):
    class UnavailableGenerator(Generator):
        def generate(self, context: str, question: str) -> str:
            raise GenerationUnavailableError("upstream down")

    app.dependency_overrides[get_chat_generator] = lambda: UnavailableGenerator()
    mock_get_settings.return_value = api_settings_namespace()
    mock_get_qdrant_client.return_value = object()
    mock_query_jobs.return_value = SimpleNamespace(
        points=[
            SimpleNamespace(
                score=0.9,
                payload={
                    "job_url_identifier": "job-123",
                    "job_role": "Backend Developer",
                    "document_text": "Backend role in Copenhagen",
                },
            )
        ]
    )

    response = client.post("/chat", json={"question": "backend roles?"})

    assert response.status_code == 502
    assert response.json()["detail"] == "The generation service is unavailable."


@patch("api.main.get_qdrant_client", side_effect=ConnectionError("refused"))
@patch("api.main.get_settings")
def test_chat_returns_503_when_qdrant_is_unavailable(
    mock_get_settings, mock_get_qdrant_client
):
    mock_get_settings.return_value = api_settings_namespace()

    response = client.post("/chat", json={"question": "backend roles?"})

    assert response.status_code == 503
    assert response.json()["detail"] == "Qdrant is unavailable."


@patch("api.main._chat_rate_limit", return_value="10/minute")
@patch(
    "api.main.get_settings",
    side_effect=ValidationError.from_exception_data("Settings", []),
)
def test_chat_returns_500_when_configuration_is_invalid(
    mock_get_settings, mock_chat_rate_limit
):
    response = client.post("/chat", json={"question": "backend roles?"})

    assert response.status_code == 500
    assert response.json()["detail"] == "Server configuration is invalid."


def test_chat_rejects_empty_question():
    response = client.post("/chat", json={"question": ""})

    assert response.status_code == 422


@patch("api.main.query_jobs_in_qdrant")
@patch("api.main.get_qdrant_client")
@patch("api.main.get_settings")
def test_chat_rejects_oversized_question(
    mock_get_settings,
    mock_get_qdrant_client,
    mock_query_jobs,
):
    fake_generator = FakeGenerator()
    app.dependency_overrides[get_chat_generator] = lambda: fake_generator
    mock_get_settings.return_value = api_settings_namespace(
        chat_question_max_length=5,
    )
    mock_get_qdrant_client.return_value = object()

    response = client.post("/chat", json={"question": "x" * 6})

    assert response.status_code == 422
    assert response.json()["detail"] == "question must be at most 5 characters long"
    mock_query_jobs.assert_not_called()
    assert fake_generator.calls == []


@patch("api.main.query_jobs_in_qdrant")
@patch("api.main.get_qdrant_client")
@patch("api.main.get_settings")
def test_chat_accepts_question_at_max_length(
    mock_get_settings,
    mock_get_qdrant_client,
    mock_query_jobs,
):
    fake_generator = FakeGenerator()
    app.dependency_overrides[get_chat_generator] = lambda: fake_generator
    mock_get_settings.return_value = api_settings_namespace(
        chat_question_max_length=5,
    )
    mock_get_qdrant_client.return_value = object()
    mock_query_jobs.return_value = SimpleNamespace(points=[])

    response = client.post("/chat", json={"question": "x" * 5})

    assert response.status_code == 200
    mock_query_jobs.assert_called_once()
    assert fake_generator.calls == []


@patch("api.main.query_jobs_in_qdrant")
@patch("api.main.get_qdrant_client")
@patch("api.main.get_settings")
def test_chat_returns_429_when_rate_limit_exceeded(
    mock_get_settings,
    mock_get_qdrant_client,
    mock_query_jobs,
    monkeypatch,
):
    monkeypatch.setenv("CHAT_RATE_LIMIT", "1/minute")
    get_settings.cache_clear()

    fake_generator = FakeGenerator()
    app.dependency_overrides[get_chat_generator] = lambda: fake_generator
    mock_get_settings.return_value = api_settings_namespace(
        chat_rate_limit="1/minute",
    )
    mock_get_qdrant_client.return_value = object()
    mock_query_jobs.return_value = SimpleNamespace(points=[])

    first = client.post("/chat", json={"question": "backend roles?"})
    second = client.post("/chat", json={"question": "frontend roles?"})

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["detail"] == (
        "Too many chat requests. Please wait before trying again."
    )
    mock_query_jobs.assert_called_once()
    assert fake_generator.calls == []


def test_jobs_search_unaffected_by_chat_rate_limit():
    with (
        patch("api.main.get_settings") as mock_get_settings,
        patch("api.main.get_qdrant_client") as mock_get_qdrant_client,
        patch("api.main.query_jobs_in_qdrant") as mock_query_jobs,
    ):
        mock_get_settings.return_value = api_settings_namespace()
        mock_get_qdrant_client.return_value = object()
        mock_query_jobs.return_value = SimpleNamespace(points=[])

        for _ in range(3):
            response = client.get("/jobs/search", params={"q": "backend"})

        assert response.status_code == 200
        assert mock_query_jobs.call_count == 3


def test_chat_rejects_invalid_country():
    response = client.post(
        "/chat", json={"question": "backend roles?", "country": "XX"}
    )

    assert response.status_code == 422


@patch("api.main.query_jobs_in_qdrant")
@patch("api.main.get_qdrant_client")
@patch("api.main.get_settings")
def test_chat_passes_country_filter_to_query(
    mock_get_settings,
    mock_get_qdrant_client,
    mock_query_jobs,
):
    fake_generator = FakeGenerator()
    app.dependency_overrides[get_chat_generator] = lambda: fake_generator
    mock_get_settings.return_value = api_settings_namespace()
    mock_get_qdrant_client.return_value = object()
    mock_query_jobs.return_value = SimpleNamespace(points=[])

    response = client.post(
        "/chat",
        json={"question": "backend python roles in Denmark", "country": "DK"},
    )

    assert response.status_code == 200
    mock_query_jobs.assert_called_once()
    _, kwargs = mock_query_jobs.call_args
    assert kwargs["country"] == CountryCode.DENMARK
    body = response.json()
    assert body["applied_country"] == "DK"
    assert body["applied_remote"] is None


@patch("api.main.query_jobs_in_qdrant")
@patch("api.main.get_qdrant_client")
@patch("api.main.get_settings")
def test_chat_derives_country_filter_from_question_when_not_explicit(
    mock_get_settings,
    mock_get_qdrant_client,
    mock_query_jobs,
):
    fake_generator = FakeGenerator()
    app.dependency_overrides[get_chat_generator] = lambda: fake_generator
    mock_get_settings.return_value = api_settings_namespace()
    mock_get_qdrant_client.return_value = object()
    mock_query_jobs.return_value = SimpleNamespace(points=[])

    response = client.post(
        "/chat",
        json={"question": "Any frontend developer roles in Sweden?"},
    )

    assert response.status_code == 200
    mock_query_jobs.assert_called_once()
    _, kwargs = mock_query_jobs.call_args
    assert kwargs["country"] == CountryCode.SWEDEN
    assert kwargs["remote"] is None
    body = response.json()
    assert body["applied_country"] == "SE"
    assert body["applied_remote"] is None


@patch("api.main.query_jobs_in_qdrant")
@patch("api.main.get_qdrant_client")
@patch("api.main.get_settings")
def test_chat_applied_filters_are_null_when_nothing_resolved(
    mock_get_settings,
    mock_get_qdrant_client,
    mock_query_jobs,
):
    fake_generator = FakeGenerator()
    app.dependency_overrides[get_chat_generator] = lambda: fake_generator
    mock_get_settings.return_value = api_settings_namespace()
    mock_get_qdrant_client.return_value = object()
    mock_query_jobs.return_value = SimpleNamespace(
        points=[
            SimpleNamespace(
                score=0.88,
                payload={
                    "job_url_identifier": "job-123",
                    "job_role": "Backend Developer",
                    "document_text": "Backend role",
                },
            )
        ]
    )

    response = client.post(
        "/chat",
        json={"question": "any backend roles?"},
    )

    assert response.status_code == 200
    mock_query_jobs.assert_called_once()
    _, kwargs = mock_query_jobs.call_args
    assert kwargs["country"] is None
    assert kwargs["remote"] is None
    body = response.json()
    assert body["applied_country"] is None
    assert body["applied_remote"] is None


@patch("api.main.query_jobs_in_qdrant")
@patch("api.main.get_qdrant_client")
@patch("api.main.get_settings")
def test_chat_applied_remote_reflects_derived_value_on_success_path(
    mock_get_settings,
    mock_get_qdrant_client,
    mock_query_jobs,
):
    fake_generator = FakeGenerator()
    app.dependency_overrides[get_chat_generator] = lambda: fake_generator
    mock_get_settings.return_value = api_settings_namespace()
    mock_get_qdrant_client.return_value = object()
    mock_query_jobs.return_value = SimpleNamespace(
        points=[
            SimpleNamespace(
                score=0.88,
                payload={
                    "job_url_identifier": "job-123",
                    "job_role": "Backend Developer",
                    "document_text": "Remote backend role in Copenhagen",
                },
            )
        ]
    )

    response = client.post(
        "/chat",
        json={"question": "remote backend python roles in Denmark"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["generated"] is True
    assert body["applied_country"] == "DK"
    assert body["applied_remote"] is True
    mock_query_jobs.assert_called_once()
    _, kwargs = mock_query_jobs.call_args
    assert kwargs["country"] == CountryCode.DENMARK
    assert kwargs["remote"] is True


@patch("api.main.query_jobs_in_qdrant")
@patch("api.main.get_qdrant_client")
@patch("api.main.get_settings")
def test_chat_applied_remote_reflects_explicit_value_over_question_text(
    mock_get_settings,
    mock_get_qdrant_client,
    mock_query_jobs,
):
    fake_generator = FakeGenerator()
    app.dependency_overrides[get_chat_generator] = lambda: fake_generator
    mock_get_settings.return_value = api_settings_namespace()
    mock_get_qdrant_client.return_value = object()
    mock_query_jobs.return_value = SimpleNamespace(
        points=[
            SimpleNamespace(
                score=0.88,
                payload={
                    "job_url_identifier": "job-123",
                    "job_role": "Backend Developer",
                    "document_text": "On-site backend role in Copenhagen",
                },
            )
        ]
    )

    response = client.post(
        "/chat",
        json={"question": "remote backend roles in Denmark", "remote": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["generated"] is True
    assert body["applied_country"] == "DK"
    assert body["applied_remote"] is False
    mock_query_jobs.assert_called_once()
    _, kwargs = mock_query_jobs.call_args
    assert kwargs["remote"] is False


@patch("api.main.query_jobs_in_qdrant")
@patch("api.main.get_qdrant_client")
@patch("api.main.get_settings")
def test_chat_derives_filters_for_backend_denmark_transcript(
    mock_get_settings,
    mock_get_qdrant_client,
    mock_query_jobs,
):
    fake_generator = FakeGenerator()
    app.dependency_overrides[get_chat_generator] = lambda: fake_generator
    mock_get_settings.return_value = api_settings_namespace()
    mock_get_qdrant_client.return_value = object()
    mock_query_jobs.return_value = SimpleNamespace(points=[])

    response = client.post(
        "/chat",
        json={"question": "Any backend Python developer roles in Denmark?"},
    )

    assert response.status_code == 200
    mock_query_jobs.assert_called_once()
    _, kwargs = mock_query_jobs.call_args
    assert kwargs["country"] == CountryCode.DENMARK
    body = response.json()
    assert body["applied_country"] == "DK"
    assert body["applied_remote"] is None


@patch("api.main.query_jobs_in_qdrant")
@patch("api.main.get_qdrant_client")
@patch("api.main.get_settings")
def test_chat_explicit_country_overrides_extracted_country(
    mock_get_settings,
    mock_get_qdrant_client,
    mock_query_jobs,
):
    fake_generator = FakeGenerator()
    app.dependency_overrides[get_chat_generator] = lambda: fake_generator
    mock_get_settings.return_value = api_settings_namespace()
    mock_get_qdrant_client.return_value = object()
    mock_query_jobs.return_value = SimpleNamespace(points=[])

    response = client.post(
        "/chat",
        json={
            "question": "frontend roles in Sweden",
            "country": "DK",
        },
    )

    assert response.status_code == 200
    mock_query_jobs.assert_called_once()
    _, kwargs = mock_query_jobs.call_args
    assert kwargs["country"] == CountryCode.DENMARK
    body = response.json()
    assert body["applied_country"] == "DK"
    assert body["applied_remote"] is None
