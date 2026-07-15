"""Generation-model comparison against golden_generation.json (ALE-147).

Metrics intentionally omit ``mock_answer_substring`` from the fixture. That
field only makes sense against ScriptedGenerator in pytest
(``tests/db/test_generation.py``); it has no meaningful relationship to what
a real Gemini/Ollama call will output. Do not wire it into live-model scoring.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from qdrant_client import QdrantClient

from db import get_settings, query_jobs_in_qdrant
from evals.collections import (
    GENERATION_COMPARE_COLLECTION,
    delete_collections,
    get_comparison_client,
    seed_collection_for_model,
    validate_qdrant_config,
)
from evals.fixtures import load_golden_generation
from evals.types import GenerationCaseResult, GenerationComparisonResult
from llm_client.base import Generator
from llm_client.context import (
    filter_chat_retrieval_points,
    find_ungrounded_job_detail_phrases,
    find_ungrounded_link_urls,
    format_job_context,
)
from llm_client.gemini import GeminiGenerator
from llm_client.ollama import OllamaGenerator
from llm_client.settings import LLMSettings, get_llm_settings
from llm_client.stub import StubGenerator
from the_hub_client.utils import build_job_url


def build_generator(
    label: str,
    *,
    base_settings: LLMSettings | None = None,
) -> Generator:
    """Construct a Generator from a CLI/UI label without touching get_generator().

    Accepted labels:
    - ``gemini`` / ``gemini:<model>``
    - ``ollama`` / ``ollama:<model>``
    - ``stub``
    """
    normalized = label.strip().lower()

    if normalized == "stub":
        return StubGenerator()

    settings = base_settings if base_settings is not None else get_llm_settings()

    if normalized == "gemini" or normalized.startswith("gemini:"):
        gemini_model = (
            normalized.split(":", 1)[1]
            if normalized.startswith("gemini:")
            else settings.gemini_model
        )
        copied = settings.model_copy(
            update={"llm_provider": "gemini", "gemini_model": gemini_model}
        )
        return GeminiGenerator(copied)

    if normalized == "ollama" or normalized.startswith("ollama:"):
        ollama_model = (
            normalized.split(":", 1)[1]
            if normalized.startswith("ollama:")
            else settings.ollama_model
        )
        copied = settings.model_copy(
            update={"llm_provider": "ollama", "ollama_model": ollama_model}
        )
        return OllamaGenerator(copied)

    raise ValueError(
        f"Unknown generator label {label!r}. "
        "Use 'gemini', 'gemini:<model>', 'ollama', 'ollama:<model>', or 'stub'."
    )


def _source_ids_and_urls(
    usable_points: list[Any],
) -> tuple[list[str], set[str], list[str]]:
    source_ids: list[str] = []
    allowed_urls: set[str] = set()
    document_texts: list[str] = []
    for point in usable_points:
        payload = cast(dict[str, Any], point.payload)
        job_id = payload.get("job_url_identifier")
        if isinstance(job_id, str) and job_id.strip():
            source_ids.append(job_id.strip())
            allowed_urls.add(build_job_url(job_id.strip()))
        document_text = payload.get("document_text", "")
        if isinstance(document_text, str) and document_text.strip():
            document_texts.append(document_text.strip())
    return source_ids, allowed_urls, document_texts


def compare_generators(
    generators: Mapping[str, Generator],
    *,
    collection_name: str = GENERATION_COMPARE_COLLECTION,
    keep_collection: bool = False,
    top_k: int = 5,
    min_score: float | None = None,
    client: QdrantClient | None = None,
    embedding_model: str | None = None,
) -> GenerationComparisonResult:
    """Run golden_generation cases through each Generator; return structured results.

    Seeds a disposable collection under the current (or provided) embedding
    model. Does not mutate ``get_generator()``; callers pass constructed
    Generator instances (see ``build_generator``).
    """
    if not generators:
        raise ValueError("compare_generators requires at least one generator")

    validate_qdrant_config()
    settings = get_settings()
    model = embedding_model if embedding_model is not None else settings.embedding_model
    score_floor = min_score if min_score is not None else settings.chat_source_min_score
    qdrant = client if client is not None else get_comparison_client()
    fixture = load_golden_generation()
    cases = fixture.get("cases", [])
    if not isinstance(cases, list) or not cases:
        raise ValueError("golden_generation.json has no cases")

    if qdrant.collection_exists(collection_name):
        qdrant.delete_collection(collection_name)
    seed_collection_for_model(qdrant, collection_name, model)

    results: list[GenerationCaseResult] = []
    labels = list(generators.keys())

    try:
        for case in cases:
            case_id = str(case["id"])
            query = str(case["query"])
            expected_ids = [str(job_id) for job_id in case["expected_source_job_ids"]]

            response = query_jobs_in_qdrant(
                db_client=qdrant,
                collection_name=collection_name,
                query_text=query,
                limit=top_k,
            )
            usable_points = filter_chat_retrieval_points(
                response.points,
                min_score=score_floor,
            )
            source_ids, allowed_urls, document_texts = _source_ids_and_urls(
                list(usable_points)
            )
            missing_expected = [
                job_id for job_id in expected_ids if job_id not in source_ids
            ]

            if not usable_points:
                for label in labels:
                    results.append(
                        GenerationCaseResult(
                            case_id=case_id,
                            query=query,
                            generator_label=label,
                            answer="",
                            source_job_ids=[],
                            expected_source_job_ids=expected_ids,
                            missing_expected_source_ids=missing_expected,
                            ungrounded_urls=[],
                            ungrounded_phrases=[],
                            generated=False,
                        )
                    )
                continue

            context = format_job_context(
                [cast(dict[str, Any], point.payload) for point in usable_points]
            )
            for label, generator in generators.items():
                answer = generator.generate(context=context, question=query)
                results.append(
                    GenerationCaseResult(
                        case_id=case_id,
                        query=query,
                        generator_label=label,
                        answer=answer,
                        source_job_ids=list(source_ids),
                        expected_source_job_ids=expected_ids,
                        missing_expected_source_ids=list(missing_expected),
                        ungrounded_urls=find_ungrounded_link_urls(answer, allowed_urls),
                        ungrounded_phrases=find_ungrounded_job_detail_phrases(
                            answer, document_texts
                        ),
                        generated=True,
                    )
                )
    finally:
        if not keep_collection:
            delete_collections(qdrant, [collection_name])

    return GenerationComparisonResult(
        generator_labels=labels,
        results=results,
        collection_name=collection_name,
    )
