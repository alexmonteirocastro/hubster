"""Load golden eval fixtures shared by comparison tooling and CLIs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from the_hub_client import JobOpportunity

_REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = _REPO_ROOT / "tests" / "fixtures"
GOLDEN_QUERIES_PATH = FIXTURES_DIR / "golden_queries.json"
GOLDEN_JOBS_PATH = FIXTURES_DIR / "golden_jobs.json"
GOLDEN_GENERATION_PATH = FIXTURES_DIR / "golden_generation.json"


def load_golden_queries() -> dict[str, Any]:
    if not GOLDEN_QUERIES_PATH.exists():
        raise FileNotFoundError(
            f"Could not find golden_queries.json at {GOLDEN_QUERIES_PATH}"
        )
    return json.loads(GOLDEN_QUERIES_PATH.read_text(encoding="utf-8"))


def load_golden_jobs() -> list[JobOpportunity]:
    if not GOLDEN_JOBS_PATH.exists():
        raise FileNotFoundError(
            f"Could not find golden_jobs.json at {GOLDEN_JOBS_PATH}"
        )
    payload = json.loads(GOLDEN_JOBS_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected a list in {GOLDEN_JOBS_PATH}")
    return [JobOpportunity.model_validate(job) for job in payload]


def load_golden_generation() -> dict[str, Any]:
    if not GOLDEN_GENERATION_PATH.exists():
        raise FileNotFoundError(
            f"Could not find golden_generation.json at {GOLDEN_GENERATION_PATH}"
        )
    return json.loads(GOLDEN_GENERATION_PATH.read_text(encoding="utf-8"))
