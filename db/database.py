import uuid
from typing import cast
from uuid import UUID

from qdrant_client import QdrantClient, models
from qdrant_client.http.models import QueryResponse, VectorParams

from db.settings import get_settings
from the_hub_client import JobOpportunity
from the_hub_client.models import (
    EU_COUNTRY_FILTER_EXCLUSIONS,
    CountryCode,
    country_code_to_hub_country_name,
)


def job_id_to_point_id(job_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, job_id))


def create_collection(db_client: QdrantClient, collection_name: str) -> None:
    """check if collection exists, if not, create one"""
    if not db_client.collection_exists(collection_name):
        db_client.create_collection(
            collection_name=collection_name,
            vectors_config=db_client.get_fastembed_vector_params(),
        )
        db_client.create_payload_index(
            collection_name=collection_name,
            field_name="Country",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
        db_client.create_payload_index(
            collection_name=collection_name,
            field_name="Remote",
            field_schema=models.PayloadSchemaType.BOOL,
        )


def get_vector_name(db_client: QdrantClient, collection_name: str) -> str:
    coll_info = db_client.get_collection(collection_name)
    vectors = coll_info.config.params.vectors
    if vectors is None:
        raise ValueError(f"Collection {collection_name!r} has no vector config.")
    if isinstance(vectors, dict):
        available_vector_names = list(vectors.keys())
    elif isinstance(vectors, VectorParams):
        available_vector_names = [""]
    else:
        raise ValueError(f"Unsupported vector config for {collection_name!r}.")

    return available_vector_names[0]


def load_jobs_into_qdrant(
    db_client: QdrantClient, collection_name: str, jobs: list[JobOpportunity]
) -> None:
    embedding_model = get_settings().embedding_model

    jobs_documents = [
        (
            f"Job Title: {job.job_title}\n"
            f"Company: {job.company}\n"
            f"Company Description: {job.company_description}\n"
            f"Job Description: {job.job_description}"
        )
        for job in jobs
    ]

    jobs_metadata = [
        {
            "job_url_identifier": job.job_id,
            "job_title": job.job_title,
            "company": job.company,
            "job_role": job.job_role,
            "Country": job.country,
            "location": job.locality,
            "Remote": job.remote,
            "Salary Type": job.salary_type,
            "Salary": job.salary,
            "Equity": job.equity,
        }
        for job in jobs
    ]

    jobs_ids = [job_id_to_point_id(job.job_id) for job in jobs]

    vector_name = get_vector_name(db_client, collection_name)

    points = [
        models.PointStruct(
            id=job_id,
            vector={vector_name: models.Document(text=doc_text, model=embedding_model)},
            payload={**metadata, "document_text": doc_text},
        )
        for job_id, doc_text, metadata in zip(
            jobs_ids,
            jobs_documents,
            jobs_metadata,
            strict=True,
        )
    ]

    db_client.upsert(collection_name=collection_name, points=points)

    print(f"{len(jobs_documents)} jobs ingested into the vector database")


def get_indexed_job_ids(db_client: QdrantClient, collection_name: str) -> set[str]:
    """Return Hub job IDs currently stored in Qdrant (via scroll, not search)."""
    indexed_job_ids: set[str] = set()
    offset = None

    while True:
        points, next_offset = db_client.scroll(
            collection_name=collection_name,
            limit=100,
            offset=offset,
            with_payload=["job_url_identifier"],
            with_vectors=False,
        )

        for point in points:
            payload = point.payload or {}
            job_id = payload.get("job_url_identifier")
            if job_id:
                indexed_job_ids.add(job_id)

        if next_offset is None:
            break
        offset = next_offset

    return indexed_job_ids


def delete_jobs_from_qdrant(
    db_client: QdrantClient, collection_name: str, job_ids: list[str]
) -> None:
    if not job_ids:
        return

    point_ids = [job_id_to_point_id(job_id) for job_id in job_ids]
    db_client.delete(
        collection_name=collection_name,
        points_selector=models.PointIdsList(
            points=cast(list[int | str | UUID], point_ids)
        ),
    )
    print(f"{len(point_ids)} stale jobs removed from the vector database")


def query_jobs_in_qdrant(
    db_client: QdrantClient,
    collection_name: str,
    query_text: str,
    *,
    limit: int = 5,
    country: CountryCode | None = None,
    remote: bool | None = None,
) -> QueryResponse:
    embedding_model = get_settings().embedding_model
    vector_name = get_vector_name(db_client, collection_name)

    filter_conditions: list[models.FieldCondition] = []
    if country is not None:
        # Hub's location.country string is stored verbatim in the Qdrant Country field.
        if country == CountryCode.EUROPE:
            filter_conditions.append(
                models.FieldCondition(
                    key="Country",
                    match=models.MatchExcept(
                        **{"except": EU_COUNTRY_FILTER_EXCLUSIONS}
                    ),
                )
            )
        else:
            filter_conditions.append(
                models.FieldCondition(
                    key="Country",
                    match=models.MatchValue(
                        value=country_code_to_hub_country_name(country)
                    ),
                )
            )
    if remote is not None:
        filter_conditions.append(
            models.FieldCondition(
                key="Remote",
                match=models.MatchValue(value=remote),
            )
        )

    query_filter = models.Filter(must=filter_conditions) if filter_conditions else None

    search_results = db_client.query_points(
        collection_name=collection_name,
        query=models.Document(text=query_text, model=embedding_model),
        using=vector_name,
        limit=limit,
        query_filter=query_filter,
    )

    return search_results


def drop_db(db_client: QdrantClient, collection_name: str) -> None:
    if db_client.collection_exists(collection_name):
        db_client.delete_collection(collection_name=collection_name)
        print(f"🔥 Collection '{collection_name}' deleted completely.")
    else:
        print("Nothing to delete.")


def clear_db(db_client: QdrantClient, collection_name: str) -> None:
    if db_client.collection_exists(collection_name):
        db_client.delete(
            collection_name=collection_name,
            points_selector=models.FilterSelector(filter=models.Filter()),
        )
        print(f"🧹 All jobs cleared from '{collection_name}'.")
