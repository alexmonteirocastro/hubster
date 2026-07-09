from collections.abc import Sequence
from typing import Any, Protocol

NO_MATCHING_JOBS_MESSAGE = (
    "No matching jobs found for your question. Try broadening your search terms."
)

_SYSTEM_INSTRUCTION = (
    "You are a job search assistant for The Hub (Nordic and European startup jobs). "
    "Answer the user's question using ONLY the job listings provided below. "
    "If the listings do not contain enough information to answer, say so clearly. "
    "Do not invent jobs, companies, salaries, locations, or requirements."
)


class _RetrievalPoint(Protocol):
    score: float
    payload: dict[str, Any] | None


def build_generation_prompt(context: str, question: str) -> str:
    return (
        f"{_SYSTEM_INSTRUCTION}\n\n"
        f"Job listings:\n{context}\n\n"
        f"Question: {question}\n\n"
        "Answer:"
    )


def truncate_text(text: str, max_chars: int) -> str:
    """Truncate text to max_chars, appending an ellipsis when shortened."""
    stripped = text.strip()
    if max_chars <= 0 or len(stripped) <= max_chars:
        return stripped
    if max_chars <= 1:
        return "…"
    return stripped[: max_chars - 1].rstrip() + "…"


def format_job_context(
    payloads: list[dict[str, Any]],
    *,
    max_chars_per_job: int | None = None,
) -> str:
    blocks: list[str] = []
    for index, payload in enumerate(payloads, start=1):
        document_text = payload.get("document_text", "")
        if not isinstance(document_text, str) or not document_text.strip():
            continue
        body = document_text.strip()
        if max_chars_per_job is not None:
            body = truncate_text(body, max_chars_per_job)
        job_id = payload.get("job_url_identifier", "unknown")
        blocks.append(f"--- Job {index} (id: {job_id}) ---\n{body}")
    return "\n\n".join(blocks)


def _payload_has_document_text(payload: dict[str, Any]) -> bool:
    document_text = payload.get("document_text", "")
    return isinstance(document_text, str) and bool(document_text.strip())


def filter_usable_points(points: Sequence[_RetrievalPoint]) -> list[_RetrievalPoint]:
    """Return retrieval hits that have non-empty document_text for generation."""
    return [
        point
        for point in points
        if point.payload is not None and _payload_has_document_text(point.payload)
    ]


def filter_points_by_min_score(
    points: Sequence[_RetrievalPoint],
    min_score: float,
) -> list[_RetrievalPoint]:
    """Return retrieval hits at or above the similarity floor."""
    return [point for point in points if point.score >= min_score]


def filter_chat_retrieval_points(
    points: Sequence[_RetrievalPoint],
    *,
    min_score: float,
) -> list[_RetrievalPoint]:
    """Return /chat hits with usable document_text and sufficient similarity."""
    return filter_points_by_min_score(filter_usable_points(points), min_score)


def has_sufficient_retrieval(points: Sequence[_RetrievalPoint]) -> bool:
    return bool(filter_usable_points(points))
