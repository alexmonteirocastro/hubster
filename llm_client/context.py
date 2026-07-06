NO_MATCHING_JOBS_MESSAGE = (
    "No matching jobs found for your question. Try broadening your search terms."
)

_SYSTEM_INSTRUCTION = (
    "You are a job search assistant for The Hub (Nordic and European startup jobs). "
    "Answer the user's question using ONLY the job listings provided below. "
    "If the listings do not contain enough information to answer, say so clearly. "
    "Do not invent jobs, companies, salaries, locations, or requirements."
)


def build_generation_prompt(context: str, question: str) -> str:
    return (
        f"{_SYSTEM_INSTRUCTION}\n\n"
        f"Job listings:\n{context}\n\n"
        f"Question: {question}\n\n"
        "Answer:"
    )


def format_job_context(payloads: list[dict]) -> str:
    blocks: list[str] = []
    for index, payload in enumerate(payloads, start=1):
        document_text = payload.get("document_text", "")
        if not isinstance(document_text, str) or not document_text.strip():
            continue
        job_id = payload.get("job_url_identifier", "unknown")
        blocks.append(f"--- Job {index} (id: {job_id}) ---\n{document_text.strip()}")
    return "\n\n".join(blocks)


def _payload_has_document_text(payload: dict) -> bool:
    document_text = payload.get("document_text", "")
    return isinstance(document_text, str) and bool(document_text.strip())


def filter_usable_points(points) -> list:
    """Return retrieval hits that have non-empty document_text for generation."""
    return [
        point
        for point in points
        if point.payload is not None and _payload_has_document_text(point.payload)
    ]


def has_sufficient_retrieval(points) -> bool:
    return bool(filter_usable_points(points))
