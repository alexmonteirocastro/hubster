import logging
import re
import uuid
from typing import cast
from uuid import UUID

from qdrant_client import QdrantClient, models
from qdrant_client.http.models import QueryResponse, VectorParams

from db.settings import (
    BM25_SPARSE_MODEL,
    BM25_SPARSE_VECTOR_NAME,
    MISSING_DENSE_SCORE,
    get_settings,
)
from the_hub_client import JobOpportunity
from the_hub_client.models import (
    EU_COUNTRY_FILTER_EXCLUSIONS,
    CountryCode,
    country_code_to_hub_country_name,
)

logger = logging.getLogger(__name__)

# ADR-0012 Decision 3: closed deterministic injection patterns stripped at ingestion.
INJECTION_PATTERNS: tuple[str, ...] = (
    "ignore previous instructions",
    "ignore all previous instructions",
    "disregard the above",
    "disregard all previous instructions",
    "system:",
    "assistant:",
    "###",
)

_INJECTION_PATTERN_REGEX = re.compile(
    "|".join(re.escape(pattern) for pattern in INJECTION_PATTERNS),
    re.IGNORECASE,
)


def sanitize_document_text(document_text: str) -> tuple[str, list[str]]:
    """Strip obvious injection patterns from document_text.

    Returns sanitized text and the canonical matched patterns (ADR-0012 Decisions 3–4).
    """
    matched_patterns: list[str] = []

    def _record_and_strip(match: re.Match[str]) -> str:
        matched = match.group(0)
        canonical = next(
            (
                pattern
                for pattern in INJECTION_PATTERNS
                if matched.casefold() == pattern.casefold()
            ),
            matched,
        )
        matched_patterns.append(canonical)
        return ""

    sanitized = _INJECTION_PATTERN_REGEX.sub(_record_and_strip, document_text)
    return sanitized, matched_patterns


def _build_document_text(job: JobOpportunity) -> str:
    return (
        f"Job Title: {job.job_title}\n"
        f"Company: {job.company}\n"
        f"Company Description: {job.company_description}\n"
        f"Job Description: {job.job_description}"
    )


def job_id_to_point_id(job_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, job_id))


def create_collection(db_client: QdrantClient, collection_name: str) -> None:
    """Create collection with dense + BM25 sparse vectors if missing; ensure sparse."""
    if not db_client.collection_exists(collection_name):
        db_client.create_collection(
            collection_name=collection_name,
            vectors_config=db_client.get_fastembed_vector_params(),
            sparse_vectors_config={
                BM25_SPARSE_VECTOR_NAME: models.SparseVectorParams(
                    modifier=models.Modifier.IDF
                )
            },
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
    else:
        ensure_sparse_bm25_vector(db_client, collection_name)


def ensure_sparse_bm25_vector(db_client: QdrantClient, collection_name: str) -> bool:
    """Add the BM25 sparse named vector in place if the collection lacks it.

    Returns True when the vector was created, False when it already existed.
    """
    coll_info = db_client.get_collection(collection_name)
    sparse_vectors = coll_info.config.params.sparse_vectors or {}
    if BM25_SPARSE_VECTOR_NAME in sparse_vectors:
        return False

    db_client.create_vector_name(
        collection_name=collection_name,
        vector_name=BM25_SPARSE_VECTOR_NAME,
        vector_name_config=models.SparseVectorNameConfig(
            sparse=models.SparseVectorConfig(modifier=models.Modifier.IDF)
        ),
    )
    return True


def get_dense_vector_name(db_client: QdrantClient, collection_name: str) -> str:
    """Return the dense named-vector key (or '' for an unnamed dense vector)."""
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


def get_vector_name(db_client: QdrantClient, collection_name: str) -> str:
    """Alias for get_dense_vector_name (backward-compatible name)."""
    return get_dense_vector_name(db_client, collection_name)


def get_sparse_vector_name(db_client: QdrantClient, collection_name: str) -> str:
    """Return the BM25 sparse vector name; raises if the collection lacks it."""
    coll_info = db_client.get_collection(collection_name)
    sparse_vectors = coll_info.config.params.sparse_vectors or {}
    if BM25_SPARSE_VECTOR_NAME not in sparse_vectors:
        raise ValueError(
            f"Collection {collection_name!r} has no sparse vector "
            f"{BM25_SPARSE_VECTOR_NAME!r}; run ensure_sparse_bm25_vector / "
            "backfill first."
        )
    return BM25_SPARSE_VECTOR_NAME


def load_jobs_into_qdrant(
    db_client: QdrantClient, collection_name: str, jobs: list[JobOpportunity]
) -> None:
    embedding_model = get_settings().embedding_model

    jobs_documents: list[str] = []
    for job in jobs:
        doc_text, matched_patterns = sanitize_document_text(_build_document_text(job))
        if matched_patterns:
            for pattern in matched_patterns:
                logger.warning(
                    "Stripped injection pattern from document_text for job %s: %r",
                    job.job_id,
                    pattern,
                )
        jobs_documents.append(doc_text)

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

    dense_vector_name = get_dense_vector_name(db_client, collection_name)
    sparse_vector_name = BM25_SPARSE_VECTOR_NAME

    points = [
        models.PointStruct(
            id=job_id,
            vector={
                dense_vector_name: models.Document(
                    text=doc_text, model=embedding_model
                ),
                sparse_vector_name: models.Document(
                    text=doc_text, model=BM25_SPARSE_MODEL
                ),
            },
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


def _build_country_remote_filter(
    country: CountryCode | None,
    remote: bool | None,
) -> models.Filter | None:
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

    return models.Filter(must=filter_conditions) if filter_conditions else None


def _attach_dense_scores_to_fused_hits(
    fused_points: list[models.ScoredPoint],
    dense_scores_by_id: dict[str | int | UUID, float],
) -> list[models.ScoredPoint]:
    """Rewrite RRF-ordered hits to carry dense cosine scores (ADR-0010 Decision 7).

    Hits present in the fused ranking but absent from the companion dense query
    receive MISSING_DENSE_SCORE so CHAT_SOURCE_MIN_SCORE excludes them.
    """
    merged: list[models.ScoredPoint] = []
    for point in fused_points:
        dense_score = dense_scores_by_id.get(point.id)
        score = dense_score if dense_score is not None else MISSING_DENSE_SCORE
        merged.append(point.model_copy(update={"score": score}))
    return merged


def query_jobs_in_qdrant(
    db_client: QdrantClient,
    collection_name: str,
    query_text: str,
    *,
    limit: int = 5,
    country: CountryCode | None = None,
    remote: bool | None = None,
) -> QueryResponse:
    """Hybrid dense+BM25 RRF retrieval with dense scores for the chat floor.

    Ranks via a single fused query (Decision 3). Attaches dense cosine scores via
    a companion dense query in the same ``query_batch_points`` request, reusing
    one E5 ``Document`` instance for the dense prefetch and companion legs as a
    best-effort client-side shape (Cloud Inference request-level dedupe is not
    confirmed — see ADR-0010 Decision 7). Ranking stays RRF; scoring for
    ``CHAT_SOURCE_MIN_SCORE`` stays dense cosine (Decision 7).
    """
    embedding_model = get_settings().embedding_model
    dense_vector_name = get_dense_vector_name(db_client, collection_name)
    sparse_vector_name = BM25_SPARSE_VECTOR_NAME
    query_filter = _build_country_remote_filter(country, remote)

    # Shared Document instance — best-effort; server-side embed dedupe unconfirmed.
    dense_query = models.Document(text=query_text, model=embedding_model)
    sparse_query = models.Document(text=query_text, model=BM25_SPARSE_MODEL)
    # Prefetch wider than final limit so RRF sees BM25-strong hits that sit
    # outside the dense top-k; companion dense limit stays == limit (Decision 7).
    prefetch_limit = max(limit * 4, 20)

    fused_request = models.QueryRequest(
        prefetch=[
            models.Prefetch(
                query=dense_query,
                using=dense_vector_name,
                filter=query_filter,
                limit=prefetch_limit,
            ),
            models.Prefetch(
                query=sparse_query,
                using=sparse_vector_name,
                filter=query_filter,
                limit=prefetch_limit,
            ),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        filter=query_filter,
        limit=limit,
        with_payload=True,
    )
    # intentionally not padded — see ADR-0010 Decision 7 missing-dense rule
    companion_request = models.QueryRequest(
        query=dense_query,
        using=dense_vector_name,
        filter=query_filter,
        limit=limit,
        with_payload=True,
    )

    fused_response, companion_response = db_client.query_batch_points(
        collection_name=collection_name,
        requests=[fused_request, companion_request],
    )

    dense_scores_by_id = {
        point.id: float(point.score) for point in companion_response.points
    }
    merged_points = _attach_dense_scores_to_fused_hits(
        list(fused_response.points),
        dense_scores_by_id,
    )
    return QueryResponse(points=merged_points)


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
