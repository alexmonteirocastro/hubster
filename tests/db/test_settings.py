import pytest
from pydantic import ValidationError

from db.settings import Settings, get_qdrant_client, get_settings

REQUIRED_ENV_VARS = (
    "QDRANT_URL",
    "QDRANT_API_KEY",
    "QDRANT_COLLECTION_NAME",
    "EMBEDDING_MODEL",
)


@pytest.fixture(autouse=True)
def clear_settings_caches():
    get_settings.cache_clear()
    get_qdrant_client.cache_clear()
    yield
    get_settings.cache_clear()
    get_qdrant_client.cache_clear()


def test_importing_db_does_not_require_env(monkeypatch):
    for var in REQUIRED_ENV_VARS:
        monkeypatch.delenv(var, raising=False)

    import db  # noqa: F401


def test_db_public_api_matches_all_and_drops_legacy_client(monkeypatch):
    for var in REQUIRED_ENV_VARS:
        monkeypatch.delenv(var, raising=False)

    import db

    for name in db.__all__:
        assert hasattr(db, name), f"db.{name} is listed in __all__ but not exported"

    assert not hasattr(db, "client"), "legacy module-level client must not be re-exported"


def test_get_settings_raises_when_required_env_missing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for var in REQUIRED_ENV_VARS:
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(ValidationError) as exc_info:
        get_settings()

    errors = exc_info.value.errors()
    missing_fields = {error["loc"][0] for error in errors}
    assert {"QDRANT_URL", "QDRANT_COLLECTION_NAME", "EMBEDDING_MODEL"} <= missing_fields


def test_get_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("QDRANT_API_KEY", "")
    monkeypatch.setenv("QDRANT_COLLECTION_NAME", "JOBS_ON_THE_HUB")
    monkeypatch.setenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")

    settings = get_settings()

    assert settings.qdrant_url == "http://localhost:6333"
    assert settings.qdrant_api_key is None
    assert settings.qdrant_collection_name == "JOBS_ON_THE_HUB"
    assert settings.embedding_model == "BAAI/bge-small-en-v1.5"


def test_get_qdrant_client_returns_same_instance(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("QDRANT_COLLECTION_NAME", "JOBS_ON_THE_HUB")
    monkeypatch.setenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")

    class FakeQdrantClient:
        def __init__(self, url: str, api_key: str | None = None):
            self.url = url
            self.api_key = api_key
            self.model = None

        def set_model(self, model: str):
            self.model = model

    monkeypatch.setattr("db.settings.QdrantClient", FakeQdrantClient)

    first = get_qdrant_client()
    second = get_qdrant_client()

    assert first is second
    assert first.url == "http://localhost:6333"
    assert first.model == "BAAI/bge-small-en-v1.5"


def test_settings_rejects_empty_collection_name(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("QDRANT_COLLECTION_NAME", "")
    monkeypatch.setenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")

    with pytest.raises(ValidationError):
        Settings()
