"""Unit tests for review collection discovery (no Streamlit needed)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from streamlit_app.review_collections import (
    REVIEW_COLLECTION_CANDIDATES,
    existing_review_collections,
)


def test_existing_review_collections_filters_to_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    client.collection_exists.side_effect = lambda name: name == "JOBS_ON_THE_HUB"
    monkeypatch.setattr(
        "streamlit_app.review_collections.get_qdrant_client",
        lambda: client,
    )

    assert existing_review_collections() == ["JOBS_ON_THE_HUB"]
    assert client.collection_exists.call_count == len(REVIEW_COLLECTION_CANDIDATES)


def test_existing_review_collections_propagates_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    client.collection_exists.side_effect = ConnectionError("qdrant down")
    monkeypatch.setattr(
        "streamlit_app.review_collections.get_qdrant_client",
        lambda: client,
    )

    with pytest.raises(ConnectionError, match="qdrant down"):
        existing_review_collections()
