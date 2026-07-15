"""Unit tests for evals comparison / sweep helpers (no Qdrant / API keys)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from evals.collections import collection_name_for_model
from evals.embeddings import summarize_query_results
from evals.generation import (
    build_generator,
    format_context_for_generator,
    max_chars_per_job_for_generator,
    run_generators_for_case,
)
from evals.hyperparameters import (
    evaluate_threshold,
    suggest_max_safe_threshold,
    sweep_from_case_scores,
)
from evals.types import GenerationCaseResult, QueryResult, ScoredHit, SweepCaseScores
from llm_client.base import Generator
from llm_client.exceptions import GenerationUnavailableError
from llm_client.gemini import GeminiGenerator
from llm_client.ollama import OllamaGenerator
from llm_client.settings import LLMSettings
from llm_client.stub import StubGenerator


def _llm_settings(**overrides: Any) -> LLMSettings:
    defaults: dict[str, Any] = {
        "llm_provider": "ollama",
        "gemini_api_key": "test-key",
        "gemini_model": "gemini-2.5-flash",
        "max_retries": 3,
        "backoff_factor": 1.0,
        "timeout_seconds": 30.0,
        "ollama_base_url": "http://localhost:11434/v1",
        "ollama_model": "qwen3:4b",
        "ollama_timeout_seconds": 60.0,
        "ollama_max_chars_per_job": 1200,
        "ollama_num_predict": 256,
    }
    defaults.update(overrides)
    return LLMSettings.model_construct(**defaults)


@dataclass
class _FakePoint:
    score: float
    payload: dict[str, Any] | None


class _RecordingGenerator(Generator):
    """Captures the context string passed to generate()."""

    def __init__(self, answer: str = "ok") -> None:
        self.answer = answer
        self.contexts: list[str] = []

    def generate(self, context: str, question: str) -> str:
        self.contexts.append(context)
        return self.answer


class _FailingGenerator(Generator):
    def generate(self, context: str, question: str) -> str:
        raise GenerationUnavailableError("ollama timed out")


def test_collection_name_for_model_slugifies_slashes_and_dots() -> None:
    assert (
        collection_name_for_model("intfloat/multilingual-e5-small")
        == "JOBS_COMPARE_INTFLOAT_MULTILINGUAL-E5-SMALL"
    )
    assert (
        collection_name_for_model("sentence-transformers/all-MiniLM-L6-v2")
        == "JOBS_COMPARE_SENTENCE-TRANSFORMERS_ALL-MINILM-L6-V2"
    )


def test_collection_name_for_model_does_not_produce_e5_prod_default() -> None:
    # evaluate_e5_against_production uses hardcoded JOBS_COMPARE_E5_PROD —
    # ensure centralized slugifier does not collide with that name for E5.
    assert collection_name_for_model("intfloat/multilingual-e5-small") != (
        "JOBS_COMPARE_E5_PROD"
    )


def test_summarize_query_results_margin() -> None:
    results = [
        QueryResult(
            query_id="q1",
            query_text="backend",
            expected_job_ids=["abc"],
            expected_scores={"abc": 0.90},
            top_noise_score=0.70,
            all_missing=[],
        ),
        QueryResult(
            query_id="q2",
            query_text="pm",
            expected_job_ids=["def"],
            expected_scores={"def": 0.85},
            top_noise_score=0.80,
            all_missing=[],
        ),
    ]
    summary = summarize_query_results("demo-model", results)
    assert summary.missed_count == 0
    assert summary.min_expected_score == 0.85
    assert summary.max_noise_score == 0.80
    assert summary.separation_margin == pytest.approx(0.05)


def test_summarize_query_results_counts_misses() -> None:
    results = [
        QueryResult(
            query_id="q1",
            query_text="x",
            expected_job_ids=["a", "b"],
            expected_scores={"a": None, "b": 0.9},
            top_noise_score=None,
            all_missing=["a"],
        )
    ]
    summary = summarize_query_results("m", results)
    assert summary.missed_count == 1
    assert summary.min_expected_score == 0.9
    assert summary.separation_margin is None


def test_evaluate_threshold_expected_and_confuser() -> None:
    cases = [
        SweepCaseScores(
            case_id="frontend-copenhagen",
            query_text="frontend jobs in Copenhagen",
            expected_job_ids=["cph001"],
            confuser_job_ids=["cph002", "cph003"],
            hits=[
                ScoredHit(job_id="cph001", score=0.88),
                ScoredHit(job_id="cph002", score=0.86),
                ScoredHit(job_id="cph003", score=0.84),
            ],
        )
    ]
    high = evaluate_threshold(cases, 0.87)
    assert high.expected_survivors == 1
    assert high.missed_expected == 0
    assert high.confuser_survivors == 0

    mid = evaluate_threshold(cases, 0.85)
    assert mid.expected_survivors == 1
    assert mid.confuser_survivors == 1

    low = evaluate_threshold(cases, 0.80)
    assert low.confuser_survivors == 2


def test_sweep_from_case_scores_suggests_max_safe() -> None:
    cases = [
        SweepCaseScores(
            case_id="q1",
            query_text="backend",
            expected_job_ids=["abc"],
            confuser_job_ids=[],
            hits=[ScoredHit(job_id="abc", score=0.86)],
        )
    ]
    result = sweep_from_case_scores(cases, [0.80, 0.85, 0.90])
    assert result.suggested_max_safe_threshold == 0.85
    assert suggest_max_safe_threshold(result.rows) == 0.85


def test_build_generator_stub_without_llm_settings() -> None:
    generator = build_generator("stub")
    assert isinstance(generator, StubGenerator)
    answer = generator.generate(context="ctx", question="q")
    assert isinstance(answer, str)


def test_build_generator_ollama_model_label() -> None:
    base = _llm_settings(ollama_model="qwen3:4b")
    generator = build_generator("ollama:qwen3:8b", base_settings=base)
    assert isinstance(generator, OllamaGenerator)
    assert generator._settings.ollama_model == "qwen3:8b"
    assert generator._settings.llm_provider == "ollama"


def test_build_generator_gemini_model_label() -> None:
    base = _llm_settings(llm_provider="gemini", gemini_model="gemini-2.5-flash")
    generator = build_generator("gemini:gemini-2.0-flash", base_settings=base)
    assert isinstance(generator, GeminiGenerator)
    assert generator._settings.gemini_model == "gemini-2.0-flash"
    assert generator._settings.llm_provider == "gemini"


def test_max_chars_per_job_only_for_ollama() -> None:
    ollama = OllamaGenerator(_llm_settings(ollama_max_chars_per_job=500))
    gemini = GeminiGenerator(_llm_settings(llm_provider="gemini"))
    assert max_chars_per_job_for_generator(ollama) == 500
    assert max_chars_per_job_for_generator(gemini) is None
    assert max_chars_per_job_for_generator(StubGenerator()) is None


def test_format_context_truncates_for_ollama_only() -> None:
    long_body = "x" * 2000
    payloads = [
        {
            "job_url_identifier": "abc123",
            "document_text": long_body,
        }
    ]
    ollama = OllamaGenerator(_llm_settings(ollama_max_chars_per_job=50))
    gemini = GeminiGenerator(_llm_settings(llm_provider="gemini"))

    ollama_ctx = format_context_for_generator(payloads, ollama)
    gemini_ctx = format_context_for_generator(payloads, gemini)

    assert len(ollama_ctx) < len(gemini_ctx)
    assert long_body not in ollama_ctx
    assert long_body in gemini_ctx


def test_run_generators_for_case_builds_per_provider_context() -> None:
    long_body = "y" * 3000
    points = [
        _FakePoint(
            score=0.9,
            payload={
                "job_url_identifier": "abc123",
                "document_text": long_body,
            },
        )
    ]
    stub = _RecordingGenerator("stub-answer")
    ollama = OllamaGenerator(_llm_settings(ollama_max_chars_per_job=80))
    ollama_contexts: list[str] = []

    def _capture(context: str, question: str) -> str:
        ollama_contexts.append(context)
        return "ollama-answer"

    ollama.generate = _capture  # type: ignore[method-assign]

    results = run_generators_for_case(
        case_id="backend_copenhagen",
        query="backend engineer",
        expected_source_job_ids=["abc123"],
        usable_points=points,
        generators={"stub": stub, "ollama": ollama},
    )

    assert len(results) == 2
    by_label = {r.generator_label: r for r in results}
    assert by_label["stub"].generated is True
    assert by_label["ollama"].generated is True
    assert long_body in stub.contexts[0]
    assert long_body not in ollama_contexts[0]
    assert len(ollama_contexts[0]) < len(stub.contexts[0])


def test_run_generators_for_case_records_error_and_continues() -> None:
    points = [
        _FakePoint(
            score=0.9,
            payload={
                "job_url_identifier": "abc123",
                "document_text": "Backend engineer role in Copenhagen.",
            },
        )
    ]
    results = run_generators_for_case(
        case_id="backend_copenhagen",
        query="backend",
        expected_source_job_ids=["abc123"],
        usable_points=points,
        generators={
            "failing": _FailingGenerator(),
            "ok": _RecordingGenerator("all good"),
        },
    )
    by_label = {r.generator_label: r for r in results}
    assert by_label["failing"].generated is False
    assert by_label["failing"].error is not None
    assert "GenerationUnavailableError" in by_label["failing"].error
    assert by_label["ok"].generated is True
    assert by_label["ok"].answer == "all good"
    assert by_label["ok"].error is None


def test_run_generators_for_case_empty_retrieval() -> None:
    results = run_generators_for_case(
        case_id="x",
        query="q",
        expected_source_job_ids=["abc"],
        usable_points=[],
        generators={"stub": StubGenerator()},
    )
    assert len(results) == 1
    assert results[0].generated is False
    assert results[0].missing_expected_source_ids == ["abc"]


def test_generation_case_result_fields_omit_mock_substring() -> None:
    # GenerationCaseResult has no mock_answer_substring attribute — guard against
    # wiring ScriptedGenerator-only fixture fields into live-model metrics.
    fields = set(GenerationCaseResult.__dataclass_fields__)
    assert "mock_answer_substring" not in fields
    assert "answer" in fields
    assert "error" in fields
    assert "ungrounded_urls" in fields
    assert "ungrounded_phrases" in fields
