"""Disposable JOBS_COMPARE_* collection helpers for eval comparison tooling.

Safe against production: never writes to QDRANT_COLLECTION_NAME. Seeding may
temporarily mutate the cached Settings.embedding_model — that pattern is
documented as embeddings-only and must not spread to Generator construction.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import urlparse

from fastembed import TextEmbedding
from qdrant_client import QdrantClient

from db import (
    create_collection,
    drop_db,
    get_qdrant_client,
    get_settings,
    load_jobs_into_qdrant,
)
from db.settings import uses_cloud_inference
from evals.fixtures import load_golden_jobs
from the_hub_client import JobOpportunity

# Shorthand / ticket names -> local FastEmbed registry name.
_FASTEMBED_ALIASES: dict[str, str] = {
    "all-minilm-l6-v2": "sentence-transformers/all-MiniLM-L6-v2",
    "sentence-transformers/all-minilm-l6-v2": "sentence-transformers/all-MiniLM-L6-v2",
}

# Shorthand / ticket names -> Qdrant Cloud Inference API name.
# Cloud rejects bare `all-MiniLM-L6-v2`; use sentence-transformers/... instead.
_CLOUD_INFERENCE_ALIASES: dict[str, str] = {
    "all-minilm-l6-v2": "sentence-transformers/all-MiniLM-L6-v2",
    "sentence-transformers/all-minilm-l6-v2": "sentence-transformers/all-MiniLM-L6-v2",
}

GENERATION_COMPARE_COLLECTION = "JOBS_COMPARE_GENERATION"
MIN_SCORE_SWEEP_COLLECTION = "JOBS_COMPARE_MIN_SCORE_SWEEP"


def collection_name_for_model(model: str) -> str:
    """Build a disposable collection name from an embedding model id.

    Single slugifier for JOBS_COMPARE_* naming: ``/`` and ``.`` → ``_``, then
    uppercased. Do not reimplement elsewhere.
    """
    safe = model.replace("/", "_").replace(".", "_")
    return f"JOBS_COMPARE_{safe.upper()}"


def is_local_qdrant() -> bool:
    settings = get_settings()
    host = urlparse(settings.qdrant_url).hostname or ""
    return settings.qdrant_api_key is None and host in {"localhost", "127.0.0.1", "::1"}


def validate_qdrant_config() -> None:
    settings = get_settings()
    if uses_cloud_inference(settings) or is_local_qdrant():
        return
    raise ValueError(
        f"QDRANT_URL points at Qdrant Cloud ({settings.qdrant_url}) but "
        "QDRANT_API_KEY is not set. Add your cluster API key to .env, or "
        "point QDRANT_URL at local Qdrant (http://localhost:6333) for "
        "FastEmbed-only comparison."
    )


def get_comparison_client() -> QdrantClient:
    """Return a Qdrant client configured for embedding comparison paths."""
    settings = get_settings()
    if uses_cloud_inference(settings):
        return QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            cloud_inference=True,
            check_compatibility=False,
        )
    return get_qdrant_client()


def fastembed_supported_models() -> set[str]:
    return {entry["model"] for entry in TextEmbedding.list_supported_models()}


def resolve_model_name(model: str, *, cloud_mode: bool) -> str:
    if cloud_mode:
        alias = _CLOUD_INFERENCE_ALIASES.get(model.lower())
        return alias if alias else model

    supported = fastembed_supported_models()
    if model in supported:
        return model

    alias = _FASTEMBED_ALIASES.get(model.lower())
    if alias and alias in supported:
        return alias

    raise ValueError(
        f"Model {model!r} is not available in local FastEmbed. "
        f"Supported locally: {sorted(supported)}. "
        "Point QDRANT_URL/QDRANT_API_KEY at Qdrant Cloud to use "
        "intfloat/multilingual-e5-small and other Cloud Inference models."
    )


@contextmanager
def embedding_model_override(model: str) -> Iterator[None]:
    """Temporarily mutate cached Settings.embedding_model for seeding/querying.

    NOTE: get_settings() is an lru_cache'd singleton. This is a deliberate,
    narrow hack for disposable comparison tooling — do not reuse inside the
    application itself, and do not use for Generator / LLMSettings.
    """
    settings = get_settings()
    original_model = settings.embedding_model
    settings.embedding_model = model
    try:
        yield
    finally:
        settings.embedding_model = original_model


def seed_collection_for_model(
    client: QdrantClient,
    collection_name: str,
    model: str,
    *,
    jobs: list[JobOpportunity] | None = None,
) -> None:
    """Create + seed a throwaway collection using ``model`` for embedding."""
    with embedding_model_override(model):
        drop_db(client, collection_name)
        create_collection(client, collection_name)
        corpus = jobs if jobs is not None else load_golden_jobs()
        load_jobs_into_qdrant(
            db_client=client,
            collection_name=collection_name,
            jobs=corpus,
        )


def delete_collections(
    client: QdrantClient,
    collection_names: list[str],
) -> None:
    for name in collection_names:
        if client.collection_exists(name):
            client.delete_collection(name)
