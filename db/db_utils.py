import csv
from typing import List, Set, Tuple

from qdrant_client import QdrantClient

from db.database import (
    delete_jobs_from_qdrant,
    get_indexed_job_ids,
    load_jobs_into_qdrant,
)
from the_hub_client import (
    CountryCode,
    JobOpportunity,
    get_all_job_ids_per_country,
    get_all_live_job_ids,
    get_number_of_jobs_and_pages_by_country,
    scrape_job_offer_by_id,
)

INGEST_BATCH_SIZE = 15


def compute_sync_diff(
    live_job_ids: Set[str], indexed_job_ids: Set[str]
) -> Tuple[Set[str], Set[str]]:
    return live_job_ids - indexed_job_ids, indexed_job_ids - live_job_ids


def _chunk_job_ids(job_ids: List[str], chunk_size: int) -> List[List[str]]:
    if chunk_size <= 0:
        return [job_ids]
    return [job_ids[i : i + chunk_size] for i in range(0, len(job_ids), chunk_size)]


def load_jobs_data_into_csv(file_name: str = "jobs_preview.csv"):
    headers = list(JobOpportunity.model_fields.keys())

    with open(f"tmp/{file_name}", "w", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=headers,
            extrasaction="ignore",
        )
        writer.writeheader()

        for country in CountryCode:
            country_overall = get_number_of_jobs_and_pages_by_country(country)
            all_job_ids = get_all_job_ids_per_country(
                country=country,
                pages_in_country=country_overall.number_of_pages,
                total_jobs_in_country=country_overall.total_jobs,
            )
            page_chunks = _chunk_job_ids(
                all_job_ids, country_overall.jobs_per_page
            )

            for page, job_ids_in_page in enumerate(page_chunks, start=1):
                jobs_batch = []
                print(
                    f"Scraping page {page} out of {country_overall.number_of_pages} for jobs in {country.name}"
                )
                print(f"Page {page} has {len(job_ids_in_page)} job ids")
                for job_id in job_ids_in_page:
                    job_data = scrape_job_offer_by_id(job_id=job_id).model_dump()

                    if not job_data:
                        print(f"❌ Failed to scrape job_id: {job_id}")

                    jobs_batch.append(job_data)  # type: ignore

                writer.writerows(jobs_batch)  # type: ignore

    print("Al jobs loaded")


def seed_qdrant_db(db_client: QdrantClient, collection_name: str):
    """Fetches jobs and loads them into the vector DB"""
    for country in CountryCode:
        country_overall = get_number_of_jobs_and_pages_by_country(country)
        all_job_ids = get_all_job_ids_per_country(
            country=country,
            pages_in_country=country_overall.number_of_pages,
            total_jobs_in_country=country_overall.total_jobs,
        )
        page_chunks = _chunk_job_ids(all_job_ids, country_overall.jobs_per_page)

        for page, job_ids_in_page in enumerate(page_chunks, start=1):
            jobs_batch: List[JobOpportunity] = []
            print(
                f"Scraping page {page} out of {country_overall.number_of_pages} for jobs in {country.name}"
            )
            print(f"Page {page} has {len(job_ids_in_page)} job ids")
            for job_id in job_ids_in_page:
                try:
                    job_data = scrape_job_offer_by_id(job_id=job_id)

                    if not job_data:
                        print(f"❌ Failed to scrape job_id: {job_id}")

                    jobs_batch.append(job_data)  # type: ignore
                except Exception as e:
                    print(f"  ⚠️ Error scraping {job_id}: {e}")

            if jobs_batch:
                print(f"--- Ingesting {len(job_ids_in_page)} Jobs ---")
                load_jobs_into_qdrant(
                    db_client=db_client,
                    collection_name=collection_name,
                    jobs=jobs_batch,
                )

                if len(jobs_batch) < len(job_ids_in_page):
                    print(
                        f"⚠️ Warning: Only {len(jobs_batch)}/{len(job_ids_in_page)} jobs were successfully scraped on this page."
                    )

            info = db_client.get_collection(collection_name)
            print(f"\nCollection Status: {info.status}")
            print(f"Points (Jobs) in DB: {info.points_count}")


def _scrape_jobs(job_ids: List[str]) -> List[JobOpportunity]:
    jobs: List[JobOpportunity] = []
    for job_id in job_ids:
        try:
            job_data = scrape_job_offer_by_id(job_id=job_id)
            if not job_data:
                print(f"❌ Failed to scrape job_id: {job_id}")
                continue
            jobs.append(job_data)
        except Exception as e:
            print(f"  ⚠️ Error scraping {job_id}: {e}")
    return jobs


def sync_qdrant_db(db_client: QdrantClient, collection_name: str):
    """Reconcile Qdrant with live Hub listings: add new jobs, remove delisted ones."""
    print("Fetching live job IDs from The Hub (listing API only)...")
    live_job_ids = get_all_live_job_ids()
    indexed_job_ids = get_indexed_job_ids(db_client, collection_name)

    to_add, to_remove = compute_sync_diff(live_job_ids, indexed_job_ids)

    print(f"Live jobs: {len(live_job_ids)}")
    print(f"Indexed jobs: {len(indexed_job_ids)}")
    print(f"New jobs to add: {len(to_add)}")
    print(f"Stale jobs to remove: {len(to_remove)}")

    if to_remove:
        delete_jobs_from_qdrant(
            db_client=db_client,
            collection_name=collection_name,
            job_ids=sorted(to_remove),
        )

    if to_add:
        to_add_list = sorted(to_add)
        for batch_start in range(0, len(to_add_list), INGEST_BATCH_SIZE):
            batch_ids = to_add_list[batch_start : batch_start + INGEST_BATCH_SIZE]
            print(f"--- Fetching and ingesting {len(batch_ids)} new jobs ---")
            jobs_batch = _scrape_jobs(batch_ids)
            if jobs_batch:
                load_jobs_into_qdrant(
                    db_client=db_client,
                    collection_name=collection_name,
                    jobs=jobs_batch,
                )
                if len(jobs_batch) < len(batch_ids):
                    print(
                        f"⚠️ Warning: Only {len(jobs_batch)}/{len(batch_ids)} jobs were successfully scraped in this batch."
                    )
    elif not to_remove:
        print("Collection is already up to date — no Hub detail fetches or Qdrant writes needed.")

    info = db_client.get_collection(collection_name)
    print(f"\nCollection Status: {info.status}")
    print(f"Points (Jobs) in DB: {info.points_count}")
