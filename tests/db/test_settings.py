import pytest
from pydantic import ValidationError

from db.settings import Settings, get_qdrant_client, get_settings

REQUIRED_ENV_VARS = (
    "QDRANT_URL",
    "QDRANT_API_KEY",
    "QDRANT_COLLECTION_NAME",
    "EMBEDDING_MODEL",
)

E5_MODEL = "intfloat/multilingual-e5-small"


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

    assert not hasattr(db, "client"), (
        "legacy module-level client must not be re-exported"
    )


def test_get_settings_raises_when_required_env_missing(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for var in REQUIRED_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("HUBSTER_API_KEYS", raising=False)

    with pytest.raises(ValidationError) as exc_info:
        get_settings()

    errors = exc_info.value.errors()
    missing_fields = {error["loc"][0] for error in errors}
    assert {
        "QDRANT_URL",
        "QDRANT_COLLECTION_NAME",
        "EMBEDDING_MODEL",
        "HUBSTER_API_KEYS",
    } <= missing_fields


def test_get_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("QDRANT_API_KEY", "")
    monkeypatch.setenv("QDRANT_COLLECTION_NAME", "JOBS_ON_THE_HUB")
    monkeypatch.setenv("EMBEDDING_MODEL", E5_MODEL)
    monkeypatch.setenv("HUBSTER_API_KEYS", "abc123, def456")

    settings = get_settings()

    assert settings.qdrant_url == "http://localhost:6333"
    assert settings.qdrant_api_key is None
    assert settings.qdrant_collection_name == "JOBS_ON_THE_HUB"
    assert settings.qdrant_dev_collection_name == "JOBS_DEV"
    assert settings.embedding_model == E5_MODEL
    assert settings.cors_allowed_origins == ["http://localhost:5173"]
    assert settings.chat_question_max_length == 500
    assert settings.chat_rate_limit == "10/minute"
    assert settings.chat_source_min_score == 0.85
    assert settings.hubster_api_keys == {"abc123", "def456"}


def test_get_settings_parses_cors_allowed_origins(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("QDRANT_COLLECTION_NAME", "JOBS_ON_THE_HUB")
    monkeypatch.setenv("EMBEDDING_MODEL", E5_MODEL)
    monkeypatch.setenv("HUBSTER_API_KEYS", "test-key")
    monkeypatch.setenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:5173, http://localhost:3000",
    )

    settings = get_settings()

    assert settings.cors_allowed_origins == [
        "http://localhost:5173",
        "http://localhost:3000",
    ]


def test_settings_rejects_empty_cors_allowed_origins(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("QDRANT_COLLECTION_NAME", "JOBS_ON_THE_HUB")
    monkeypatch.setenv("EMBEDDING_MODEL", E5_MODEL)
    monkeypatch.setenv("HUBSTER_API_KEYS", "test-key")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "  ,  ")

    with pytest.raises(ValidationError):
        Settings()


def test_get_qdrant_client_returns_same_instance_for_local_qdrant(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("QDRANT_COLLECTION_NAME", "JOBS_ON_THE_HUB")
    monkeypatch.setenv("EMBEDDING_MODEL", E5_MODEL)
    monkeypatch.setenv("HUBSTER_API_KEYS", "test-key")

    class FakeQdrantClient:
        def __init__(self, url: str, api_key: str | None = None, **kwargs):
            self.url = url
            self.api_key = api_key
            self.kwargs = kwargs
            self.model = None

        def set_model(self, model: str):
            self.model = model

    monkeypatch.setattr("db.settings.QdrantClient", FakeQdrantClient)

    first = get_qdrant_client()
    second = get_qdrant_client()

    assert first is second
    assert first.url == "http://localhost:6333"
    assert first.kwargs == {}
    assert first.model == E5_MODEL


def test_get_qdrant_client_enables_cloud_inference_for_qdrant_cloud(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "https://example.eu-central.aws.cloud.qdrant.io")
    monkeypatch.setenv("QDRANT_API_KEY", "cloud-key")
    monkeypatch.setenv("QDRANT_COLLECTION_NAME", "JOBS_ON_THE_HUB")
    monkeypatch.setenv("EMBEDDING_MODEL", E5_MODEL)
    monkeypatch.setenv("HUBSTER_API_KEYS", "test-key")

    class FakeQdrantClient:
        def __init__(self, url: str, api_key: str | None = None, **kwargs):
            self.url = url
            self.api_key = api_key
            self.kwargs = kwargs
            self.model = None

        def set_model(self, model: str):
            self.model = model

    monkeypatch.setattr("db.settings.QdrantClient", FakeQdrantClient)

    client = get_qdrant_client()

    assert client.url == "https://example.eu-central.aws.cloud.qdrant.io"
    assert client.api_key == "cloud-key"
    assert client.kwargs == {
        "cloud_inference": True,
        "check_compatibility": False,
    }
    assert client.model is None


def test_settings_rejects_empty_hubster_api_keys(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("QDRANT_COLLECTION_NAME", "JOBS_ON_THE_HUB")
    monkeypatch.setenv("EMBEDDING_MODEL", E5_MODEL)
    monkeypatch.setenv("HUBSTER_API_KEYS", "  ,  ")

    with pytest.raises(ValidationError):
        Settings()


def test_settings_rejects_empty_collection_name(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("QDRANT_COLLECTION_NAME", "")
    monkeypatch.setenv("EMBEDDING_MODEL", E5_MODEL)
    monkeypatch.setenv("HUBSTER_API_KEYS", "test-key")

    with pytest.raises(ValidationError):
        Settings()
