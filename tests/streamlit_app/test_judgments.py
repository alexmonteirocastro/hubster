"""Unit tests for streamlit_app.judgments (stdlib sqlite3 only)."""

from __future__ import annotations

from pathlib import Path

from streamlit_app.judgments import (
    ensure_db,
    get_judgment,
    insert_judgment,
    list_judgments,
)


def test_ensure_db_creates_schema_and_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "judgments.db"
    ensure_db(db_path)
    assert db_path.exists()
    ensure_db(db_path)
    assert list_judgments(path=db_path) == []


def test_insert_and_list_judgment(tmp_path: Path) -> None:
    db_path = tmp_path / "judgments.db"
    sources = [
        {
            "job_id": "abc",
            "score": 0.9,
            "job_url": "https://thehub.io/jobs/abc",
            "job_title": "Backend",
            "company": "Acme",
        }
    ]
    row_id = insert_judgment(
        collection_name="JOBS_DEV",
        query="backend roles?",
        answer="Here is a role.",
        sources=sources,
        tag="good",
        country="DK",
        remote=True,
        note="looks solid",
        path=db_path,
    )
    rows = list_judgments(path=db_path)
    assert len(rows) == 1
    assert rows[0].id == row_id
    assert rows[0].query == "backend roles?"
    assert rows[0].tag == "good"
    assert rows[0].country == "DK"
    assert rows[0].remote is True
    assert rows[0].sources == sources
    assert rows[0].note == "looks solid"


def test_list_judgments_filters_by_tag(tmp_path: Path) -> None:
    db_path = tmp_path / "judgments.db"
    insert_judgment(
        collection_name="JOBS_DEV",
        query="q1",
        answer="a1",
        sources=[],
        tag="good",
        path=db_path,
    )
    insert_judgment(
        collection_name="JOBS_DEV",
        query="q2",
        answer="a2",
        sources=[],
        tag="bad",
        note="wrong sources",
        path=db_path,
    )
    insert_judgment(
        collection_name="JOBS_ON_THE_HUB",
        query="q3",
        answer="a3",
        sources=[],
        tag="partial",
        path=db_path,
    )
    bad = list_judgments(tag="bad", path=db_path)
    assert len(bad) == 1
    assert bad[0].query == "q2"
    assert bad[0].tag == "bad"


def test_get_judgment_returns_replay_fields(tmp_path: Path) -> None:
    db_path = tmp_path / "judgments.db"
    row_id = insert_judgment(
        collection_name="JOBS_ON_THE_HUB",
        query="remote denmark eng?",
        answer="A few matches.",
        sources=[{"job_id": "x", "score": 0.88}],
        tag="partial",
        country="DK",
        remote=False,
        path=db_path,
    )
    found = get_judgment(row_id, path=db_path)
    assert found is not None
    assert found.collection_name == "JOBS_ON_THE_HUB"
    assert found.query == "remote denmark eng?"
    assert found.country == "DK"
    assert found.remote is False
    assert get_judgment(99999, path=db_path) is None
