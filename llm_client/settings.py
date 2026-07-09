from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_provider: Literal["gemini", "ollama", "stub"] = Field(
        default="gemini",
        validation_alias="LLM_PROVIDER",
    )
    gemini_api_key: str = Field(default="", validation_alias="GEMINI_API_KEY")
    gemini_model: str = Field(
        default="gemini-2.5-flash",
        validation_alias="GEMINI_MODEL",
    )
    max_retries: int = Field(default=3, validation_alias="GEMINI_MAX_RETRIES")
    backoff_factor: float = Field(default=1.0, validation_alias="GEMINI_BACKOFF_FACTOR")
    timeout_seconds: float = Field(default=30.0, validation_alias="GEMINI_TIMEOUT")
    ollama_base_url: str = Field(
        default="http://localhost:11434/v1",
        validation_alias="OLLAMA_BASE_URL",
    )
    ollama_model: str = Field(
        default="qwen3:4b",
        validation_alias="OLLAMA_MODEL",
    )
    ollama_timeout_seconds: float = Field(
        default=60.0,
        validation_alias="OLLAMA_TIMEOUT_SECONDS",
    )
    ollama_max_chars_per_job: int = Field(
        default=1200,
        validation_alias="OLLAMA_MAX_CHARS_PER_JOB",
    )
    ollama_num_predict: int = Field(
        default=256,
        validation_alias="OLLAMA_NUM_PREDICT",
    )

    @field_validator("gemini_model", "ollama_base_url", "ollama_model")
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

    @field_validator("backoff_factor", "timeout_seconds", "ollama_timeout_seconds")
    @classmethod
    def must_be_positive(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("must be > 0")
        return value

    @field_validator("ollama_max_chars_per_job", "ollama_num_predict")
    @classmethod
    def must_be_positive_int(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be > 0")
        return value

    @model_validator(mode="after")
    def validate_provider_requirements(self) -> Self:
        if self.llm_provider == "gemini" and not self.gemini_api_key.strip():
            raise ValueError(
                "GEMINI_API_KEY must not be empty when LLM_PROVIDER is gemini"
            )
        return self


@lru_cache
def get_llm_settings() -> LLMSettings:
    return LLMSettings()
