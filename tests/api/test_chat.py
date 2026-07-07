import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api.main import app, get_chat_generator
from llm_client.base import Generator
from llm_client.context import NO_MATCHING_JOBS_MESSAGE
from llm_client.exceptions import GenerationRateLimitError, GenerationUnavailableError

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
            raise AssertionError("api/main.py must not import llm_client.gemini directly")


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
    mock_get_settings.return_value = SimpleNamespace(qdrant_collection_name="JOBS_ON_THE_HUB")
    mock_get_qdrant_client.return_value = object()
    mock_query_jobs.return_value = SimpleNamespace(
        points=[
            SimpleNamespace(
                score=0.88,
                payload={
                    "job_url_identifier": "job-123",
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
def test_chat_sources_match_context_passed_to_generator(
    mock_get_settings,
    mock_get_qdrant_client,
    mock_query_jobs,
):
    fake_generator = FakeGenerator()
    app.dependency_overrides[get_chat_generator] = lambda: fake_generator
    mock_get_settings.return_value = SimpleNamespace(qdrant_collection_name="JOBS_ON_THE_HUB")
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
    mock_get_settings.return_value = SimpleNamespace(qdrant_collection_name="JOBS_ON_THE_HUB")
    mock_get_qdrant_client.return_value = object()
    mock_query_jobs.return_value = SimpleNamespace(points=[])

    response = client.post("/chat", json={"question": "underwater basket weaving?"})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == NO_MATCHING_JOBS_MESSAGE
    assert body["generated"] is False
    assert body["sources"] == []
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
    mock_get_settings.return_value = SimpleNamespace(qdrant_collection_name="JOBS_ON_THE_HUB")
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
def test_chat_returns_503_when_generator_is_rate_limited(
    mock_get_settings,
    mock_get_qdrant_client,
    mock_query_jobs,
):
    class RateLimitedGenerator(Generator):
        def generate(self, context: str, question: str) -> str:
            raise GenerationRateLimitError("rate limited")

    app.dependency_overrides[get_chat_generator] = lambda: RateLimitedGenerator()
    mock_get_settings.return_value = SimpleNamespace(qdrant_collection_name="JOBS_ON_THE_HUB")
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

    assert response.status_code == 503
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
    mock_get_settings.return_value = SimpleNamespace(qdrant_collection_name="JOBS_ON_THE_HUB")
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
def test_chat_returns_503_when_qdrant_is_unavailable(mock_get_settings, mock_get_qdrant_client):
    mock_get_settings.return_value = SimpleNamespace(qdrant_collection_name="JOBS_ON_THE_HUB")

    response = client.post("/chat", json={"question": "backend roles?"})

    assert response.status_code == 503
    assert response.json()["detail"] == "Qdrant is unavailable."


@patch("api.main.get_settings", side_effect=ValidationError.from_exception_data("Settings", []))
def test_chat_returns_500_when_configuration_is_invalid(mock_get_settings):
    response = client.post("/chat", json={"question": "backend roles?"})

    assert response.status_code == 500
    assert response.json()["detail"] == "Server configuration is invalid."


def test_chat_rejects_empty_question():
    response = client.post("/chat", json={"question": ""})

    assert response.status_code == 422


def test_chat_rejects_invalid_country():
    response = client.post("/chat", json={"question": "backend roles?", "country": "XX"})

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
    mock_get_settings.return_value = SimpleNamespace(qdrant_collection_name="JOBS_ON_THE_HUB")
    mock_get_qdrant_client.return_value = object()
    mock_query_jobs.return_value = SimpleNamespace(points=[])

    response = client.post(
        "/chat",
        json={"question": "backend python roles in Denmark", "country": "DK"},
    )

    assert response.status_code == 200
    mock_query_jobs.assert_called_once()
    _, kwargs = mock_query_jobs.call_args
    assert kwargs["country"] == "Denmark"
