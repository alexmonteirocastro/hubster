import pytest

from db.settings import get_qdrant_client, get_settings
from llm_client import get_llm_settings, reset_generator
from tests.api_auth import TEST_API_KEY


@pytest.fixture(autouse=True)
def api_test_env(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("QDRANT_COLLECTION_NAME", "JOBS_ON_THE_HUB")
    monkeypatch.setenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("HUBSTER_API_KEYS", TEST_API_KEY)


@pytest.fixture(autouse=True)
def clear_settings_caches():
    get_settings.cache_clear()
    get_qdrant_client.cache_clear()
    get_llm_settings.cache_clear()
    reset_generator()
    yield
    get_settings.cache_clear()
    get_qdrant_client.cache_clear()
    get_llm_settings.cache_clear()
    reset_generator()


@pytest.fixture(autouse=True)
def reset_chat_rate_limiter():
    from api.main import limiter

    limiter.reset()
    yield
    limiter.reset()
