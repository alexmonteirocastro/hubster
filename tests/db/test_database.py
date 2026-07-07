from types import SimpleNamespace
from unittest.mock import MagicMock, call

from qdrant_client import models

from db.database import create_collection, query_jobs_in_qdrant
from the_hub_client.models import CountryCode


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
        config=SimpleNamespace(params=SimpleNamespace(vectors={"fast-bge-small-en": object()}))
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
        config=SimpleNamespace(params=SimpleNamespace(vectors={"fast-bge-small-en": object()}))
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
