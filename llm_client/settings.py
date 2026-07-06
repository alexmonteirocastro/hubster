from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gemini_api_key: str = Field(validation_alias="GEMINI_API_KEY")
    gemini_model: str = Field(
        default="gemini-2.5-flash",
        validation_alias="GEMINI_MODEL",
    )
    max_retries: int = Field(default=3, validation_alias="GEMINI_MAX_RETRIES")
    backoff_factor: float = Field(default=1.0, validation_alias="GEMINI_BACKOFF_FACTOR")
    timeout_seconds: float = Field(default=30.0, validation_alias="GEMINI_TIMEOUT")

    @field_validator("gemini_api_key", "gemini_model")
    @classmethod
    def must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("max_retries")
    @classmethod
    def max_retries_must_be_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("must be >= 0")
        return value

    @field_validator("backoff_factor", "timeout_seconds")
    @classmethod
    def must_be_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("must be > 0")
        return value


@lru_cache
def get_llm_settings() -> LLMSettings:
    return LLMSettings()
