import re
from collections.abc import Sequence
from typing import Any, Protocol

from the_hub_client.utils import build_job_url

NO_MATCHING_JOBS_MESSAGE = (
    "No matching jobs found for your question. Try broadening your search terms."
)

_MARKDOWN_LINK_URL_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_MARKDOWN_LINK_FULL_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")

_SYSTEM_INSTRUCTION = (
    "You are a job search assistant for The Hub (Nordic and European startup jobs). "
    "Answer the user's question using ONLY the job listings provided below. "
    "If the listings do not contain enough information to answer, say so clearly. "
    "Do not invent jobs, companies, salaries, locations, or requirements. "
    "When referencing a specific job in your answer, format it as a markdown link "
    "using the exact URL provided for that listing "
    "(e.g. [Job Title](url) with plain link text — no bold inside the brackets). "
    "Never invent, alter, or guess a URL. "
    "Only link jobs that appear in the current context."
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


def extract_markdown_link_urls(text: str) -> list[str]:
    """Return destination URLs from markdown links in model output."""
    return _MARKDOWN_LINK_URL_RE.findall(text)


def find_ungrounded_link_urls(answer: str, allowed_urls: set[str]) -> list[str]:
    """Return markdown link URLs in answer that are not in allowed_urls."""
    return [
        url for url in extract_markdown_link_urls(answer) if url not in allowed_urls
    ]


def sanitize_answer_links(answer: str, allowed_urls: set[str]) -> str:
    """Strip markdown links whose URL is not in allowed_urls, keeping link text."""

    def _replace(match: re.Match[str]) -> str:
        url = match.group(2)
        if url in allowed_urls:
            return match.group(0)
        return match.group(1)

    return _MARKDOWN_LINK_FULL_RE.sub(_replace, answer)


def job_url_identifier_from_payload(payload: dict[str, Any]) -> str:
    """Normalize job_url_identifier for context blocks and ChatSource.job_id."""
    job_id = payload.get("job_url_identifier", "unknown")
    if not isinstance(job_id, str) or not job_id.strip():
        return "unknown"
    return job_id.strip()


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
        job_id = job_url_identifier_from_payload(payload)
        job_url = build_job_url(job_id)
        blocks.append(
            f"--- Job {index} (id: {job_id}, url: {job_url}) ---\n{body}"
        )
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
    """Return /chat hits with usable document_text and sufficient similarity.

    Applied after top-k retrieval (see ADR-0002 Decision 4): hits below
    min_score are omitted from sources and generation context.
    """
    return filter_points_by_min_score(filter_usable_points(points), min_score)


def has_sufficient_retrieval(points: Sequence[_RetrievalPoint]) -> bool:
    return bool(filter_usable_points(points))
