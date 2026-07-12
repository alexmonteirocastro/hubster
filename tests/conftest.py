import json
import os
import sys
from pathlib import Path

import pytest

# create_app() runs at api.main import; set auth env before collection.
os.environ.setdefault("HUBSTER_API_KEYS", "test-api-key")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture():
    def _load(name: str) -> dict:
        return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))

    return _load
