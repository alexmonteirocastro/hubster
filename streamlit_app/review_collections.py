"""Qdrant collection helpers for the eval review UI (no Streamlit import).

Named review_collections (not collections) to avoid clashing with
evals.collections when grepping the repo.
"""

from __future__ import annotations

from db import get_qdrant_client

REVIEW_COLLECTION_CANDIDATES = ("JOBS_DEV", "JOBS_ON_THE_HUB")


def existing_review_collections() -> list[str]:
    """Return candidate collections that currently exist on the configured Qdrant.

    Lets connection / API errors propagate so the Review tab can show a
    "Qdrant unreachable" message instead of a false "collection missing" warning.
    """
    client = get_qdrant_client()
    return [
        name for name in REVIEW_COLLECTION_CANDIDATES if client.collection_exists(name)
    ]
