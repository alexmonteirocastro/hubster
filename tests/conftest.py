import json
import os
import sys
from pathlib import Path

import pytest

# create_app() runs at api.main import time — set required Settings env before
# collection. Matches CI unit-test env; .env is dockerignored so Compose tests
# cannot load Cloud credentials from a file.
os.environ.setdefault("HUBSTER_API_KEYS", "test-api-key")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_COLLECTION_NAME", "JOBS_ON_THE_HUB")
os.environ.setdefault("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture():
    def _load(name: str) -> dict:
        return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))

    return _load
