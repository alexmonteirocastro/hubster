from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests
from qdrant_client import models

from db.backfill import (
    backfill_job_title_company_metadata,
    extract_title_company_from_document_text,
)
from db.db_utils import INGEST_BATCH_SIZE
from the_hub_client.models import JobOpportunity

_WELL_FORMED_DOCUMENT_TEXT = (
    "Job Title: Backend Engineer\n"
    "Company: Acme Corp\n"
    "Company Description: We build things.\n"
    "Job Description: Build APIs."
)


def test_extract_title_company_from_document_text_parses_well_formed_text():
    assert extract_title_company_from_document_text(_WELL_FORMED_DOCUMENT_TEXT) == (
        "Backend Engineer",
        "Acme Corp",
    )


@pytest.mark.parametrize(
    "document_text",
    [
        "",
        "Not a job listing",
        "Job Title: Only one line",
    ],
)
def test_extract_title_company_from_document_text_returns_none_for_invalid_input(
    document_text,
):
    assert extract_title_company_from_document_text(document_text) is None


def _point(point_id: str, payload: dict):
    return SimpleNamespace(id=point_id, payload=payload)


@patch("db.backfill.scrape_job_offer_by_id")
def test_backfill_parses_document_text_without_hub_fetch(mock_scrape):
    db_client = MagicMock()
    db_client.scroll.return_value = (
        [
            _point(
                "point-1",
                {
                    "job_url_identifier": "job-1",
                    "document_text": _WELL_FORMED_DOCUMENT_TEXT,
                },
            )
        ],
        None,
    )

    parsed, fallback, skipped = backfill_job_title_company_metadata(db_client, "JOBS_DEV")

    mock_scrape.assert_not_called()
    db_client.batch_update_points.assert_called_once()
    operations = db_client.batch_update_points.call_args.kwargs["update_operations"]
    assert len(operations) == 1
    assert operations[0] == models.SetPayloadOperation(
        set_payload=models.SetPayload(
            payload={"job_title": "Backend Engineer", "company": "Acme Corp"},
            points=["point-1"],
        )
    )
    assert (parsed, fallback, skipped) == (1, 0, 0)


@patch("db.backfill.scrape_job_offer_by_id")
def test_backfill_falls_back_to_hub_on_malformed_document_text(mock_scrape):
    mock_scrape.return_value = JobOpportunity(
        job_id="job-2",
        job_title="Product Manager",
        company="Beta Inc",
        job_role="productmanagement",
        company_description="",
        job_description="",
        country="Sweden",
        locality="Stockholm",
        remote=False,
        salary_type="competitive",
        salary="N/A",
        equity="N/A",
    )
    db_client = MagicMock()
    db_client.scroll.return_value = (
        [
            _point(
                "point-2",
                {
                    "job_url_identifier": "job-2",
                    "document_text": "",
                },
            )
        ],
        None,
    )

    backfill_job_title_company_metadata(db_client, "JOBS_DEV")

    mock_scrape.assert_called_once_with("job-2")
    operations = db_client.batch_update_points.call_args.kwargs["update_operations"]
    assert operations[0].set_payload.payload == {
        "job_title": "Product Manager",
        "company": "Beta Inc",
    }


@patch("db.backfill.scrape_job_offer_by_id")
def test_backfill_skips_delisted_jobs_on_404(mock_scrape):
    response = requests.Response()
    response.status_code = 404
    mock_scrape.side_effect = requests.HTTPError(response=response)
    db_client = MagicMock()
    db_client.scroll.return_value = (
        [
            _point(
                "point-3",
                {
                    "job_url_identifier": "job-3",
                    "document_text": "unexpected format",
                },
            )
        ],
        None,
    )

    backfill_job_title_company_metadata(db_client, "JOBS_DEV")

    db_client.batch_update_points.assert_not_called()


@patch("db.backfill.scrape_job_offer_by_id")
def test_backfill_batches_writes_at_ingest_batch_size(mock_scrape):
    point_count = INGEST_BATCH_SIZE + 1
    points = [
        _point(
            f"point-{index}",
            {
                "job_url_identifier": f"job-{index}",
                "document_text": (
                    f"Job Title: Title {index}\n"
                    f"Company: Company {index}\n"
                    "Company Description: desc\n"
                    "Job Description: desc"
                ),
            },
        )
        for index in range(point_count)
    ]
    db_client = MagicMock()
    db_client.scroll.return_value = (points, None)

    backfill_job_title_company_metadata(db_client, "JOBS_DEV")

    mock_scrape.assert_not_called()
    assert db_client.batch_update_points.call_count == 2
    first_batch = db_client.batch_update_points.call_args_list[0].kwargs["update_operations"]
    second_batch = db_client.batch_update_points.call_args_list[1].kwargs["update_operations"]
    assert len(first_batch) == INGEST_BATCH_SIZE
    assert len(second_batch) == 1
    assert all(
        isinstance(operation, models.SetPayloadOperation)
        for operation in first_batch + second_batch
    )
