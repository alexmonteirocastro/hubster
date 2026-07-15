"""Unit tests for evals comparison / sweep helpers (no Qdrant / API keys)."""

from __future__ import annotations

import pytest

from evals.collections import collection_name_for_model
from evals.embeddings import summarize_query_results
from evals.generation import build_generator
from evals.hyperparameters import (
    evaluate_threshold,
    suggest_max_safe_threshold,
    sweep_from_case_scores,
)
from evals.types import QueryResult, ScoredHit, SweepCaseScores
from llm_client.stub import StubGenerator


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


def test_generation_case_result_fields_omit_mock_substring() -> None:
    # GenerationCaseResult has no mock_answer_substring attribute — guard against
    # wiring ScriptedGenerator-only fixture fields into live-model metrics.
    from evals.types import GenerationCaseResult

    fields = set(GenerationCaseResult.__dataclass_fields__)
    assert "mock_answer_substring" not in fields
    assert "answer" in fields
    assert "ungrounded_urls" in fields
    assert "ungrounded_phrases" in fields
