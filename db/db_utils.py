import csv
import os
from typing import List

from dotenv import load_dotenv
from qdrant_client import QdrantClient

from db import load_jobs_into_qdrant
from the_hub_client import (
    CountryCode,
    JobOpportunity,
    get_job_ids_per_page_per_country,
    get_number_of_jobs_and_pages_by_country,
    scrape_job_offer_by_id,
)

load_dotenv()

embedding_model = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")


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

            for page in range(1, country_overall.number_of_pages + 1):
                jobs_batch = []
                print(
                    f"Scraping page {page} out of {country_overall.number_of_pages} for jobs in {country.name}"
                )
                job_ids_in_page = get_job_ids_per_page_per_country(
                    page=page, country=country
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

        for page in range(1, country_overall.number_of_pages + 1):
            jobs_batch: List[JobOpportunity] = []
            print(
                f"Scraping page {page} out of {country_overall.number_of_pages} for jobs in {country.name}"
            )
            job_ids_in_page = get_job_ids_per_page_per_country(
                page=page, country=country
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

            # 3. Verify: Check the collection status
            info = db_client.get_collection(collection_name)
            print(f"\nCollection Status: {info.status}")
            print(f"Points (Jobs) in DB: {info.points_count}")
