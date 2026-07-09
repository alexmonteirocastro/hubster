from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from qdrant_client import QdrantClient

_DEFAULT_CORS_ORIGINS = ("http://localhost:5173",)
DEFAULT_CHAT_QUESTION_MAX_LENGTH = 500
DEFAULT_CHAT_RATE_LIMIT = "10/minute"
# Calibrated against tests/fixtures/golden_queries.json (BAAI/bge-small-en-v1.5):
# keeps all expected golden hits (min ~0.71) while dropping weak noise (~0.55–0.63).
DEFAULT_CHAT_SOURCE_MIN_SCORE = 0.70


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    qdrant_url: str = Field(validation_alias="QDRANT_URL")
    qdrant_api_key: str | None = Field(default=None, validation_alias="QDRANT_API_KEY")
    qdrant_collection_name: str = Field(validation_alias="QDRANT_COLLECTION_NAME")
    qdrant_dev_collection_name: str = Field(
        default="JOBS_DEV", validation_alias="QDRANT_DEV_COLLECTION_NAME"
    )
    embedding_model: str = Field(validation_alias="EMBEDDING_MODEL")
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(_DEFAULT_CORS_ORIGINS),
        validation_alias="CORS_ALLOWED_ORIGINS",
    )
    chat_question_max_length: int = Field(
        default=DEFAULT_CHAT_QUESTION_MAX_LENGTH,
        ge=1,
        validation_alias="CHAT_QUESTION_MAX_LENGTH",
        description=(
            "Maximum characters accepted in POST /chat question text "
            "(bounds token cost and latency before retrieval or generation)."
        ),
    )
    chat_rate_limit: str = Field(
        default=DEFAULT_CHAT_RATE_LIMIT,
        validation_alias="CHAT_RATE_LIMIT",
        description=(
            "Per-client rate limit for POST /chat only (slowapi/limits string, "
            "e.g. 10/minute). In-memory, single-process."
        ),
    )
    chat_source_min_score: float = Field(
        default=DEFAULT_CHAT_SOURCE_MIN_SCORE,
        ge=0.0,
        le=1.0,
        validation_alias="CHAT_SOURCE_MIN_SCORE",
        description=(
            "Minimum cosine similarity for a retrieval hit to be included in "
            "POST /chat sources and generation context; weaker matches are omitted."
        ),
    )

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str] | None) -> list[str]:
        # Empty env var means unset — fall back to the local dev default.
        # Whitespace-only values (e.g. "  ,  ") are treated as explicit garbage.
        if value is None or value == "":
            return list(_DEFAULT_CORS_ORIGINS)
        if isinstance(value, str):
            origins = [origin.strip() for origin in value.split(",") if origin.strip()]
            if not origins:
                raise ValueError("must contain at least one origin")
            return origins
        return value

    @field_validator(
        "qdrant_url",
        "qdrant_collection_name",
        "qdrant_dev_collection_name",
        "embedding_model",
    )
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
        client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    else:
        client = QdrantClient(url=settings.qdrant_url)
    client.set_model(settings.embedding_model)
    return client
