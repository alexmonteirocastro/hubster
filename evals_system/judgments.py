"""Local SQLite persistence for human eval judgments (ALE-146)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

Tag = Literal["good", "bad", "partial"]

_DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "judgments.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS judgments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    collection_name TEXT NOT NULL,
    query TEXT NOT NULL,
    country TEXT,
    remote INTEGER,
    answer TEXT NOT NULL,
    sources_json TEXT NOT NULL,
    tag TEXT NOT NULL CHECK (tag IN ('good', 'bad', 'partial')),
    note TEXT
);

CREATE INDEX IF NOT EXISTS idx_judgments_tag ON judgments(tag);
CREATE INDEX IF NOT EXISTS idx_judgments_created_at ON judgments(created_at);
"""


@dataclass(frozen=True)
class Judgment:
    id: int
    created_at: str
    collection_name: str
    query: str
    country: str | None
    remote: bool | None
    answer: str
    sources: list[dict[str, Any]]
    tag: Tag
    note: str | None


def default_db_path() -> Path:
    return _DEFAULT_DB_PATH


def ensure_db(path: Path | None = None) -> Path:
    """Create parent directory and judgments schema if missing."""
    db_path = path if path is not None else _DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_SCHEMA)
    return db_path


def _parse_tag(raw: str) -> Tag:
    if raw == "good":
        return "good"
    if raw == "bad":
        return "bad"
    if raw == "partial":
        return "partial"
    raise ValueError(f"invalid tag in database: {raw!r}")


def _row_to_judgment(row: sqlite3.Row) -> Judgment:
    remote_raw = row["remote"]
    remote: bool | None
    if remote_raw is None:
        remote = None
    else:
        remote = bool(remote_raw)
    return Judgment(
        id=int(row["id"]),
        created_at=str(row["created_at"]),
        collection_name=str(row["collection_name"]),
        query=str(row["query"]),
        country=row["country"],
        remote=remote,
        answer=str(row["answer"]),
        sources=list(json.loads(row["sources_json"])),
        tag=_parse_tag(str(row["tag"])),
        note=row["note"],
    )


def insert_judgment(
    *,
    collection_name: str,
    query: str,
    answer: str,
    sources: list[dict[str, Any]],
    tag: Tag,
    country: str | None = None,
    remote: bool | None = None,
    note: str | None = None,
    path: Path | None = None,
) -> int:
    """Persist one judgment; return its row id."""
    if tag not in ("good", "bad", "partial"):
        raise ValueError(f"invalid tag: {tag!r}")
    db_path = ensure_db(path)
    remote_int: int | None
    if remote is None:
        remote_int = None
    else:
        remote_int = 1 if remote else 0
    created_at = datetime.now(UTC).isoformat()
    sources_json = json.dumps(sources)
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO judgments (
                created_at, collection_name, query, country, remote,
                answer, sources_json, tag, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                collection_name,
                query,
                country,
                remote_int,
                answer,
                sources_json,
                tag,
                note,
            ),
        )
        row_id = cur.lastrowid
    if row_id is None:
        raise RuntimeError("insert_judgment did not return a row id")
    return int(row_id)


def list_judgments(
    tag: Tag | None = None,
    *,
    path: Path | None = None,
) -> list[Judgment]:
    """Return judgments newest-first, optionally filtered by tag."""
    db_path = ensure_db(path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if tag is None:
            rows = conn.execute(
                "SELECT * FROM judgments ORDER BY created_at DESC"
            ).fetchall()
        else:
            if tag not in ("good", "bad", "partial"):
                raise ValueError(f"invalid tag: {tag!r}")
            rows = conn.execute(
                "SELECT * FROM judgments WHERE tag = ? ORDER BY created_at DESC",
                (tag,),
            ).fetchall()
    return [_row_to_judgment(row) for row in rows]


def get_judgment(judgment_id: int, *, path: Path | None = None) -> Judgment | None:
    """Return one judgment by id, or None if missing."""
    db_path = ensure_db(path)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM judgments WHERE id = ?",
            (judgment_id,),
        ).fetchone()
    if row is None:
        return None
    return _row_to_judgment(row)
