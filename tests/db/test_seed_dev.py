from unittest.mock import MagicMock

from the_hub_client.models import CountryCode, JobOpportunity, JobsAndPages

from db.db_utils import INGEST_BATCH_SIZE, seed_dev_qdrant_db


def _sample_job(job_id: str) -> JobOpportunity:
    return JobOpportunity(
        job_id=job_id,
        job_title="Backend Engineer",
        company="Acme Corp",
        job_role="backenddeveloper",
        company_description="We build things.",
        job_description="Build APIs.",
        country="Denmark",
        locality="Copenhagen",
        remote=True,
        salary_type="range",
        salary="N/A",
        equity="N/A",
    )


def test_seed_dev_qdrant_db_ingests_listing_pages_in_batches(monkeypatch):
    db_client = MagicMock()
    db_client.get_collection.return_value = MagicMock(status="green", points_count=2)

    job_ids = [f"job-{index}" for index in range(INGEST_BATCH_SIZE + 3)]
    ingested_batches: list[list[str]] = []

    monkeypatch.setattr(
        "db.db_utils.get_number_of_jobs_and_pages_by_country",
        lambda country: JobsAndPages(
            total_jobs=len(job_ids),
            number_of_pages=1,
            jobs_per_page=len(job_ids),
        ),
    )
    monkeypatch.setattr(
        "db.db_utils.get_job_ids_per_page_per_country",
        lambda page, country: job_ids,
    )
    monkeypatch.setattr(
        "db.db_utils._scrape_jobs",
        lambda batch_ids: [_sample_job(job_id) for job_id in batch_ids],
    )
    monkeypatch.setattr("db.db_utils.drop_db", lambda *args, **kwargs: None)
    monkeypatch.setattr("db.db_utils.create_collection", lambda *args, **kwargs: None)

    def _record_ingest(db_client, collection_name, jobs):
        ingested_batches.append([job.job_id for job in jobs])

    monkeypatch.setattr("db.db_utils.load_jobs_into_qdrant", _record_ingest)

    seed_dev_qdrant_db(
        db_client,
        "JOBS_DEV",
        country=CountryCode.DENMARK,
        max_pages=1,
        reset=True,
    )

    assert ingested_batches == [
        job_ids[:INGEST_BATCH_SIZE],
        job_ids[INGEST_BATCH_SIZE:],
    ]
