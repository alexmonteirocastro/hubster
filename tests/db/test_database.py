from types import SimpleNamespace
from unittest.mock import MagicMock, call

import pytest
from qdrant_client import models
from qdrant_client.http.models import Distance, VectorParams

from db.database import (
    create_collection,
    get_vector_name,
    load_jobs_into_qdrant,
    query_jobs_in_qdrant,
)
from the_hub_client.models import (
    EU_COUNTRY_FILTER_EXCLUSIONS,
    CountryCode,
    JobOpportunity,
)


def _sample_job() -> JobOpportunity:
    return JobOpportunity(
        job_id="job-123",
        job_title="Backend Engineer",
        company="Acme Corp",
        job_role="backenddeveloper",
        company_description="We build things.",
        job_description="Build APIs.",
        country="Denmark",
        locality="Copenhagen",
        remote=True,
        salary_type="range",
        salary="Competitive",
        equity="Yes",
    )


def test_load_jobs_into_qdrant_includes_job_title_and_company_in_payload(monkeypatch):
    db_client = MagicMock()
    db_client.get_collection.return_value = SimpleNamespace(
        config=SimpleNamespace(
            params=SimpleNamespace(vectors={"fast-bge-small-en": object()})
        )
    )
    monkeypatch.setattr(
        "db.database.get_settings",
        lambda: SimpleNamespace(embedding_model="BAAI/bge-small-en-v1.5"),
    )

    load_jobs_into_qdrant(db_client, "JOBS_DEV", [_sample_job()])

    db_client.upsert.assert_called_once()
    _, kwargs = db_client.upsert.call_args
    payload = kwargs["points"][0].payload
    assert payload["job_title"] == "Backend Engineer"
    assert payload["company"] == "Acme Corp"


def test_load_jobs_into_qdrant_raises_when_parallel_lists_length_mismatch(
    monkeypatch,
):
    """strict zip fails fast instead of silently dropping misaligned ingest data."""
    import builtins

    db_client = MagicMock()
    db_client.get_collection.return_value = SimpleNamespace(
        config=SimpleNamespace(
            params=SimpleNamespace(vectors={"fast-bge-small-en": object()})
        )
    )
    monkeypatch.setattr(
        "db.database.get_settings",
        lambda: SimpleNamespace(embedding_model="BAAI/bge-small-en-v1.5"),
    )

    real_zip = zip

    def zip_with_short_ids(*iterables, strict=False):
        if strict and len(iterables) == 3:
            iterables = (iterables[0][:0], iterables[1], iterables[2])
        return real_zip(*iterables, strict=strict)

    monkeypatch.setattr(builtins, "zip", zip_with_short_ids)

    with pytest.raises(ValueError, match="zip"):
        load_jobs_into_qdrant(db_client, "JOBS_DEV", [_sample_job()])


def _collection_with_vectors(vectors: object) -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(params=SimpleNamespace(vectors=vectors))
    )


def test_get_vector_name_raises_when_vectors_is_none():
    db_client = MagicMock()
    db_client.get_collection.return_value = _collection_with_vectors(None)

    with pytest.raises(ValueError, match="no vector config"):
        get_vector_name(db_client, "JOBS_DEV")


def test_get_vector_name_returns_named_vector_key():
    db_client = MagicMock()
    db_client.get_collection.return_value = _collection_with_vectors(
        {"fast-bge-small-en": object()}
    )

    assert get_vector_name(db_client, "JOBS_DEV") == "fast-bge-small-en"


def test_get_vector_name_returns_empty_string_for_unnamed_vector():
    db_client = MagicMock()
    db_client.get_collection.return_value = _collection_with_vectors(
        VectorParams(size=384, distance=Distance.COSINE)
    )

    assert get_vector_name(db_client, "JOBS_DEV") == ""


def test_get_vector_name_raises_on_unsupported_vector_config():
    db_client = MagicMock()
    db_client.get_collection.return_value = _collection_with_vectors("unexpected")

    with pytest.raises(ValueError, match="Unsupported vector config"):
        get_vector_name(db_client, "JOBS_DEV")


def test_create_collection_creates_payload_indexes_for_country_and_remote():
    db_client = MagicMock()
    db_client.collection_exists.return_value = False
    db_client.get_fastembed_vector_params.return_value = object()

    create_collection(db_client, "JOBS_DEV")

    db_client.create_collection.assert_called_once()
    db_client.create_payload_index.assert_has_calls(
        [
            call(
                collection_name="JOBS_DEV",
                field_name="Country",
                field_schema=models.PayloadSchemaType.KEYWORD,
            ),
            call(
                collection_name="JOBS_DEV",
                field_name="Remote",
                field_schema=models.PayloadSchemaType.BOOL,
            ),
        ]
    )


def test_create_collection_skips_indexes_when_collection_already_exists():
    db_client = MagicMock()
    db_client.collection_exists.return_value = True

    create_collection(db_client, "JOBS_DEV")

    db_client.create_collection.assert_not_called()
    db_client.create_payload_index.assert_not_called()


def test_query_jobs_in_qdrant_passes_country_filter_when_supplied(monkeypatch):
    db_client = MagicMock()
    db_client.get_collection.return_value = SimpleNamespace(
        config=SimpleNamespace(
            params=SimpleNamespace(vectors={"fast-bge-small-en": object()})
        )
    )
    db_client.query_points.return_value = SimpleNamespace(points=[])

    monkeypatch.setattr(
        "db.database.get_settings",
        lambda: SimpleNamespace(embedding_model="BAAI/bge-small-en-v1.5"),
    )

    query_jobs_in_qdrant(
        db_client=db_client,
        collection_name="JOBS_DEV",
        query_text="backend developer",
        limit=3,
        country=CountryCode.DENMARK,
    )

    _, kwargs = db_client.query_points.call_args
    assert kwargs["query_filter"] == models.Filter(
        must=[
            models.FieldCondition(
                key="Country",
                match=models.MatchValue(value="Denmark"),
            )
        ]
    )


def test_query_jobs_in_qdrant_omits_filter_when_country_not_supplied(monkeypatch):
    db_client = MagicMock()
    db_client.get_collection.return_value = SimpleNamespace(
        config=SimpleNamespace(
            params=SimpleNamespace(vectors={"fast-bge-small-en": object()})
        )
    )
    db_client.query_points.return_value = SimpleNamespace(points=[])

    monkeypatch.setattr(
        "db.database.get_settings",
        lambda: SimpleNamespace(embedding_model="BAAI/bge-small-en-v1.5"),
    )

    query_jobs_in_qdrant(
        db_client=db_client,
        collection_name="JOBS_DEV",
        query_text="backend developer",
    )

    _, kwargs = db_client.query_points.call_args
    assert kwargs["query_filter"] is None


def test_query_jobs_in_qdrant_passes_remote_filter_when_supplied(monkeypatch):
    db_client = MagicMock()
    db_client.get_collection.return_value = SimpleNamespace(
        config=SimpleNamespace(
            params=SimpleNamespace(vectors={"fast-bge-small-en": object()})
        )
    )
    db_client.query_points.return_value = SimpleNamespace(points=[])

    monkeypatch.setattr(
        "db.database.get_settings",
        lambda: SimpleNamespace(embedding_model="BAAI/bge-small-en-v1.5"),
    )

    query_jobs_in_qdrant(
        db_client=db_client,
        collection_name="JOBS_DEV",
        query_text="backend developer",
        remote=True,
    )

    _, kwargs = db_client.query_points.call_args
    assert kwargs["query_filter"] == models.Filter(
        must=[
            models.FieldCondition(
                key="Remote",
                match=models.MatchValue(value=True),
            )
        ]
    )


def test_query_jobs_in_qdrant_combines_country_and_remote_filters(monkeypatch):
    db_client = MagicMock()
    db_client.get_collection.return_value = SimpleNamespace(
        config=SimpleNamespace(
            params=SimpleNamespace(vectors={"fast-bge-small-en": object()})
        )
    )
    db_client.query_points.return_value = SimpleNamespace(points=[])

    monkeypatch.setattr(
        "db.database.get_settings",
        lambda: SimpleNamespace(embedding_model="BAAI/bge-small-en-v1.5"),
    )

    query_jobs_in_qdrant(
        db_client=db_client,
        collection_name="JOBS_DEV",
        query_text="backend developer",
        country=CountryCode.SWEDEN,
        remote=True,
    )

    _, kwargs = db_client.query_points.call_args
    assert kwargs["query_filter"] == models.Filter(
        must=[
            models.FieldCondition(
                key="Country",
                match=models.MatchValue(value="Sweden"),
            ),
            models.FieldCondition(
                key="Remote",
                match=models.MatchValue(value=True),
            ),
        ]
    )


def test_query_jobs_in_qdrant_uses_match_except_for_europe_country_filter(monkeypatch):
    db_client = MagicMock()
    db_client.get_collection.return_value = SimpleNamespace(
        config=SimpleNamespace(
            params=SimpleNamespace(vectors={"fast-bge-small-en": object()})
        )
    )
    db_client.query_points.return_value = SimpleNamespace(points=[])

    monkeypatch.setattr(
        "db.database.get_settings",
        lambda: SimpleNamespace(embedding_model="BAAI/bge-small-en-v1.5"),
    )

    query_jobs_in_qdrant(
        db_client=db_client,
        collection_name="JOBS_DEV",
        query_text="backend developer",
        country=CountryCode.EUROPE,
    )

    _, kwargs = db_client.query_points.call_args
    assert kwargs["query_filter"] == models.Filter(
        must=[
            models.FieldCondition(
                key="Country",
                match=models.MatchExcept(**{"except": EU_COUNTRY_FILTER_EXCLUSIONS}),
            )
        ]
    )


def test_query_jobs_in_qdrant_combines_europe_and_remote_filters(monkeypatch):
    db_client = MagicMock()
    db_client.get_collection.return_value = SimpleNamespace(
        config=SimpleNamespace(
            params=SimpleNamespace(vectors={"fast-bge-small-en": object()})
        )
    )
    db_client.query_points.return_value = SimpleNamespace(points=[])

    monkeypatch.setattr(
        "db.database.get_settings",
        lambda: SimpleNamespace(embedding_model="BAAI/bge-small-en-v1.5"),
    )

    query_jobs_in_qdrant(
        db_client=db_client,
        collection_name="JOBS_DEV",
        query_text="backend developer",
        country=CountryCode.EUROPE,
        remote=True,
    )

    _, kwargs = db_client.query_points.call_args
    assert kwargs["query_filter"] == models.Filter(
        must=[
            models.FieldCondition(
                key="Country",
                match=models.MatchExcept(**{"except": EU_COUNTRY_FILTER_EXCLUSIONS}),
            ),
            models.FieldCondition(
                key="Remote",
                match=models.MatchValue(value=True),
            ),
        ]
    )
