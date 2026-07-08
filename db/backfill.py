import logging

import requests
from qdrant_client import QdrantClient, models

from db.db_utils import INGEST_BATCH_SIZE
from the_hub_client import scrape_job_offer_by_id

logger = logging.getLogger(__name__)

_JOB_TITLE_PREFIX = "Job Title: "
_COMPANY_PREFIX = "Company: "


def extract_title_company_from_document_text(
    document_text: str,
) -> tuple[str, str] | None:
    if not document_text:
        return None

    lines = document_text.split("\n", 2)
    if len(lines) < 2:
        return None

    title_line, company_line = lines[0], lines[1]
    if not title_line.startswith(_JOB_TITLE_PREFIX) or not company_line.startswith(
        _COMPANY_PREFIX
    ):
        return None

    return title_line[len(_JOB_TITLE_PREFIX) :], company_line[len(_COMPANY_PREFIX) :]


def backfill_job_title_company_metadata(
    db_client: QdrantClient,
    collection_name: str,
) -> tuple[int, int, int]:
    """One-time migration: add job_title/company payload fields to indexed points.

    Idempotent — safe to re-run after an interrupted run. Skips points that already
    have both fields. Connection errors during the Hub API fallback abort the run
    but leave already-flushed batches in place; re-run to continue.

    Returns:
        (parsed_count, fallback_count, skipped_count) for programmatic checks.
    """
    parsed_count = 0
    fallback_count = 0
    skipped_count = 0
    pending_operations: list[models.SetPayloadOperation] = []
    offset = None

    def flush_batch() -> None:
        nonlocal pending_operations
        if not pending_operations:
            return
        db_client.batch_update_points(
            collection_name=collection_name,
            update_operations=pending_operations,
        )
        pending_operations = []

    def enqueue_update(point_id: str | int, job_title: str, company: str) -> None:
        nonlocal pending_operations
        pending_operations.append(
            models.SetPayloadOperation(
                set_payload=models.SetPayload(
                    payload={"job_title": job_title, "company": company},
                    points=[point_id],
                )
            )
        )
        if len(pending_operations) >= INGEST_BATCH_SIZE:
            flush_batch()

    while True:
        points, next_offset = db_client.scroll(
            collection_name=collection_name,
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )

        for point in points:
            payload = point.payload or {}
            if (
                payload.get("job_title") is not None
                and payload.get("company") is not None
            ):
                continue

            document_text = payload.get("document_text", "")
            extracted = extract_title_company_from_document_text(document_text)

            if extracted is not None:
                job_title, company = extracted
                parsed_count += 1
            else:
                job_id = payload.get("job_url_identifier")
                if not job_id:
                    logger.warning(
                        "Point %s missing job_url_identifier; skipping.", point.id
                    )
                    skipped_count += 1
                    continue

                try:
                    job = scrape_job_offer_by_id(job_id)
                    if not job:
                        logger.warning("Failed to scrape job %s; skipping.", job_id)
                        skipped_count += 1
                        continue
                    job_title = job.job_title
                    company = job.company
                    fallback_count += 1
                except requests.HTTPError as exc:
                    if exc.response is not None and exc.response.status_code == 404:
                        logger.warning("Job %s delisted (404); skipping.", job_id)
                        skipped_count += 1
                        continue
                    raise
                # ConnectionError/Timeout from hub_get abort here; already-flushed
                # batches are persisted — re-run backfill to continue.

            enqueue_update(point.id, job_title, company)

        if next_offset is None:
            break
        offset = next_offset

    flush_batch()

    logger.info(
        "Backfill complete: %d parsed from document_text, "
        "%d fetched from Hub API, %d skipped.",
        parsed_count,
        fallback_count,
        skipped_count,
    )
    return parsed_count, fallback_count, skipped_count
