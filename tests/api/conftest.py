import pytest

from db.settings import get_qdrant_client, get_settings


@pytest.fixture(autouse=True)
def clear_settings_caches():
    get_settings.cache_clear()
    get_qdrant_client.cache_clear()
    yield
    get_settings.cache_clear()
    get_qdrant_client.cache_clear()
