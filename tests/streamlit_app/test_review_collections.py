"""Unit tests for review-tab collection discovery (no Streamlit / Qdrant needed)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from streamlit_app.review import (
    REVIEW_COLLECTION_CANDIDATES,
    _existing_review_collections,
)


def test_existing_review_collections_filters_to_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    client.collection_exists.side_effect = lambda name: name == "JOBS_ON_THE_HUB"
    monkeypatch.setattr("streamlit_app.review.get_qdrant_client", lambda: client)

    assert _existing_review_collections() == ["JOBS_ON_THE_HUB"]
    assert client.collection_exists.call_count == len(REVIEW_COLLECTION_CANDIDATES)


def test_existing_review_collections_propagates_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    client.collection_exists.side_effect = ConnectionError("qdrant down")
    monkeypatch.setattr("streamlit_app.review.get_qdrant_client", lambda: client)

    with pytest.raises(ConnectionError, match="qdrant down"):
        _existing_review_collections()
