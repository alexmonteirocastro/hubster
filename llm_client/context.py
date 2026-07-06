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


def has_sufficient_retrieval(points) -> bool:
    if not points:
        return False

    for point in points:
        payload = point.payload
        if payload is None:
            continue
        document_text = payload.get("document_text", "")
        if isinstance(document_text, str) and document_text.strip():
            return True
    return False
