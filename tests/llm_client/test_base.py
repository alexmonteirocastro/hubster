import pytest
from pydantic import ValidationError

from llm_client import reset_generator
from llm_client.base import Generator
from llm_client.context import (
    NO_MATCHING_JOBS_MESSAGE,
    build_generation_prompt,
    extract_markdown_link_urls,
    filter_chat_retrieval_points,
    filter_points_by_min_score,
    filter_usable_points,
    find_ungrounded_link_urls,
    format_job_context,
    has_sufficient_retrieval,
    job_url_identifier_from_payload,
    sanitize_answer_links,
    truncate_text,
)
from llm_client.settings import LLMSettings, get_llm_settings
from the_hub_client.utils import build_job_url


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
    assert "markdown link" in prompt
    assert "exact URL" in prompt


def test_format_job_context_includes_build_job_url_per_listing():
    job_id = "6a2ab4ce37958933f39ce11b"
    context = format_job_context(
        [
            {
                "job_url_identifier": job_id,
                "document_text": "Backend role in Copenhagen",
            },
        ]
    )

    expected_url = build_job_url(job_id)
    assert f"id: {job_id}, url: {expected_url}" in context
    assert "Backend role in Copenhagen" in context


def test_extract_markdown_link_urls_finds_inline_links():
    answer = "See [Backend role](https://thehub.io/jobs/abc) and [PM role](https://thehub.io/jobs/def)."

    assert extract_markdown_link_urls(answer) == [
        "https://thehub.io/jobs/abc",
        "https://thehub.io/jobs/def",
    ]


def test_find_ungrounded_link_urls_flags_fabricated_urls():
    answer = (
        "Good [match](https://thehub.io/jobs/abc) and bad "
        "[link](https://evil.example/job)."
    )
    allowed = {"https://thehub.io/jobs/abc"}

    assert find_ungrounded_link_urls(answer, allowed) == [
        "https://evil.example/job"
    ]


def test_sanitize_answer_links_strips_ungrounded_urls_keeps_label():
    answer = (
        "See [Good role](https://thehub.io/jobs/abc) and "
        "[Bad role](https://evil.example/job) here."
    )
    allowed = {"https://thehub.io/jobs/abc"}

    sanitized = sanitize_answer_links(answer, allowed)

    assert sanitized == (
        "See [Good role](https://thehub.io/jobs/abc) and Bad role here."
    )
    assert find_ungrounded_link_urls(sanitized, allowed) == []


def test_job_url_identifier_from_payload_falls_back_to_unknown():
    assert job_url_identifier_from_payload({}) == "unknown"
    assert job_url_identifier_from_payload({"job_url_identifier": ""}) == "unknown"
    assert (
        job_url_identifier_from_payload({"job_url_identifier": "  job-1  "})
        == "job-1"
    )


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


def test_format_job_context_truncates_long_document_text():
    long_text = "A" * 2000
    context = format_job_context(
        [{"job_url_identifier": "job-1", "document_text": long_text}],
        max_chars_per_job=1200,
    )

    assert "…" in context
    assert long_text not in context
    assert "A" * 1199 in context


def test_truncate_text_returns_original_when_under_limit():
    assert truncate_text("hello", 10) == "hello"
    assert truncate_text("  hello  ", 10) == "hello"


def test_filter_usable_points_excludes_empty_document_text():
    points = [
        type(
            "Point",
            (),
            {
                "score": 0.9,
                "payload": {
                    "job_url_identifier": "job-1",
                    "document_text": "Backend role",
                },
            },
        )(),
        type(
            "Point",
            (),
            {
                "score": 0.9,
                "payload": {"job_url_identifier": "job-2", "document_text": ""},
            },
        )(),
        type("Point", (), {"score": 0.9, "payload": None})(),
    ]

    usable = filter_usable_points(points)

    assert len(usable) == 1
    assert usable[0].payload["job_url_identifier"] == "job-1"


def test_filter_points_by_min_score_drops_weak_hits():
    points = [
        type("Point", (), {"score": 0.88, "payload": {}})(),
        type("Point", (), {"score": 0.62, "payload": {}})(),
        type("Point", (), {"score": 0.70, "payload": {}})(),
    ]

    filtered = filter_points_by_min_score(points, min_score=0.70)

    assert [point.score for point in filtered] == [0.88, 0.70]


def test_filter_chat_retrieval_points_requires_text_and_score():
    points = [
        type(
            "Point",
            (),
            {
                "score": 0.88,
                "payload": {
                    "job_url_identifier": "strong",
                    "document_text": "Backend role",
                },
            },
        )(),
        type(
            "Point",
            (),
            {
                "score": 0.62,
                "payload": {
                    "job_url_identifier": "weak",
                    "document_text": "Sales role",
                },
            },
        )(),
        type(
            "Point",
            (),
            {
                "score": 0.75,
                "payload": {"job_url_identifier": "empty", "document_text": ""},
            },
        )(),
    ]

    filtered = filter_chat_retrieval_points(points, min_score=0.70)

    assert len(filtered) == 1
    assert filtered[0].payload["job_url_identifier"] == "strong"


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
    assert settings.ollama_model == "qwen3:4b"


def test_get_generator_returns_ollama_when_configured(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")

    from llm_client import get_generator
    from llm_client.ollama import OllamaGenerator

    assert isinstance(get_generator(), OllamaGenerator)


def test_get_generator_returns_stub_when_configured(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "stub")

    from llm_client import get_generator
    from llm_client.stub import StubGenerator

    assert isinstance(get_generator(), StubGenerator)


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
