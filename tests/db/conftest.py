import json
import logging
import os
from pathlib import Path

import pytest

from db.database import create_collection, drop_db, load_jobs_into_qdrant
from db.settings import get_qdrant_client, get_settings
from the_hub_client import JobOpportunity

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
RETRIEVAL_ENV_DEFAULTS = {
    "QDRANT_DEV_COLLECTION_NAME": "JOBS_DEV",
    "EMBEDDING_MODEL": "intfloat/multilingual-e5-small",
    "HUBSTER_API_KEYS": "test-api-key",
}


def _load_golden_jobs() -> list[JobOpportunity]:
    payload = json.loads(
        (FIXTURES_DIR / "golden_jobs.json").read_text(encoding="utf-8")
    )
    return [JobOpportunity.model_validate(job) for job in payload]


def _qdrant_is_reachable() -> bool:
    try:
        get_qdrant_client().get_collections()
        return True
    except Exception as exc:
        logger.debug("Qdrant reachability check failed: %s", exc)
        return False


@pytest.fixture(scope="session")
def retrieval_qdrant():
    saved_env = {key: os.environ.get(key) for key in RETRIEVAL_ENV_DEFAULTS}
    try:
        for key, value in RETRIEVAL_ENV_DEFAULTS.items():
            os.environ.setdefault(key, value)

        get_settings.cache_clear()
        get_qdrant_client.cache_clear()

        settings = get_settings()
        if settings.qdrant_dev_collection_name == settings.qdrant_collection_name:
            pytest.skip(
                "QDRANT_DEV_COLLECTION_NAME must differ from QDRANT_COLLECTION_NAME."
            )

        if not _qdrant_is_reachable():
            pytest.skip(
                f"Qdrant not reachable at {settings.qdrant_url} — "
                "start Qdrant to run retrieval tests."
            )

        client = get_qdrant_client()
        collection_name = settings.qdrant_dev_collection_name

        drop_db(client, collection_name)
        create_collection(client, collection_name)
        load_jobs_into_qdrant(
            db_client=client,
            collection_name=collection_name,
            jobs=_load_golden_jobs(),
        )

        yield client, collection_name

        drop_db(client, collection_name)
    finally:
        for key, prior in saved_env.items():
            if prior is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prior
        get_settings.cache_clear()
        get_qdrant_client.cache_clear()
