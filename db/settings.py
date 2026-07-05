from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from qdrant_client import QdrantClient


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    qdrant_url: str = Field(validation_alias="QDRANT_URL")
    qdrant_api_key: str | None = Field(default=None, validation_alias="QDRANT_API_KEY")
    qdrant_collection_name: str = Field(validation_alias="QDRANT_COLLECTION_NAME")
    embedding_model: str = Field(validation_alias="EMBEDDING_MODEL")

    @field_validator("qdrant_url", "qdrant_collection_name", "embedding_model")
    @classmethod
    def must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("qdrant_api_key", mode="before")
    @classmethod
    def empty_api_key_is_none(cls, value: str | None) -> str | None:
        if value == "" or value is None:
            return None
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_qdrant_client() -> QdrantClient:
    settings = get_settings()
    if settings.qdrant_api_key:
        client = QdrantClient(
            url=settings.qdrant_url, api_key=settings.qdrant_api_key
        )
    else:
        client = QdrantClient(url=settings.qdrant_url)
    client.set_model(settings.embedding_model)
    return client
