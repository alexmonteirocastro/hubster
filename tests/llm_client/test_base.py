import pytest
from pydantic import ValidationError

from llm_client import reset_generator
from llm_client.base import Generator
from llm_client.context import (
    NO_MATCHING_JOBS_MESSAGE,
    build_generation_prompt,
    filter_usable_points,
    format_job_context,
    has_sufficient_retrieval,
)
from llm_client.settings import LLMSettings, get_llm_settings


@pytest.fixture(autouse=True)
def clear_llm_caches():
    reset_generator()
    yield
    reset_generator()


class _FakeGenerator(Generator):
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def generate(self, context: str, question: str) -> str:
        self.calls.append((context, question))
        return "fake answer"


def test_generator_protocol_is_implemented_by_fake():
    generator = _FakeGenerator()
    assert generator.generate("context", "question") == "fake answer"
    assert generator.calls == [("context", "question")]


def test_build_generation_prompt_includes_context_and_question():
    prompt = build_generation_prompt("Job A", "remote python roles?")

    assert "Job A" in prompt
    assert "remote python roles?" in prompt
    assert "ONLY the job listings" in prompt


def test_format_job_context_skips_empty_document_text():
    context = format_job_context(
        [
            {
                "job_url_identifier": "job-1",
                "document_text": "Backend role in Copenhagen",
            },
            {"job_url_identifier": "job-2", "document_text": ""},
        ]
    )

    assert "job-1" in context
    assert "Backend role in Copenhagen" in context
    assert "job-2" not in context


def test_filter_usable_points_excludes_empty_document_text():
    points = [
        type(
            "Point",
            (),
            {
                "payload": {
                    "job_url_identifier": "job-1",
                    "document_text": "Backend role",
                }
            },
        )(),
        type(
            "Point",
            (),
            {"payload": {"job_url_identifier": "job-2", "document_text": ""}},
        )(),
        type("Point", (), {"payload": None})(),
    ]

    usable = filter_usable_points(points)

    assert len(usable) == 1
    assert usable[0].payload["job_url_identifier"] == "job-1"


def test_has_sufficient_retrieval_requires_non_empty_document_text():
    assert not has_sufficient_retrieval([])
    assert not has_sufficient_retrieval(
        [type("Point", (), {"payload": {"document_text": ""}})()]
    )
    assert has_sufficient_retrieval(
        [type("Point", (), {"payload": {"document_text": "Backend role"}})()]
    )


def test_no_matching_jobs_message_is_stable():
    assert "no matching jobs" in NO_MATCHING_JOBS_MESSAGE.lower()


def test_get_llm_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")

    settings = get_llm_settings()

    assert settings.gemini_api_key == "test-key"
    assert settings.gemini_model == "gemini-2.5-flash"
    assert settings.max_retries == 3


def test_get_llm_settings_raises_when_api_key_missing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(ValidationError):
        get_llm_settings()


def test_get_llm_settings_allows_missing_gemini_key_for_ollama(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")

    settings = get_llm_settings()

    assert settings.llm_provider == "ollama"
    assert settings.ollama_model == "qwen3:8b"


def test_get_generator_returns_ollama_when_configured(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")

    from llm_client import get_generator
    from llm_client.ollama import OllamaGenerator

    assert isinstance(get_generator(), OllamaGenerator)


def test_get_generator_returns_gemini_by_default(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    from llm_client import get_generator
    from llm_client.gemini import GeminiGenerator

    assert isinstance(get_generator(), GeminiGenerator)


def test_llm_settings_rejects_empty_model(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "")

    with pytest.raises(ValidationError):
        LLMSettings()
