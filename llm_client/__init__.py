from functools import lru_cache

from llm_client.base import Generator
from llm_client.context import NO_MATCHING_JOBS_MESSAGE
from llm_client.gemini import GeminiGenerator
from llm_client.ollama import OllamaGenerator
from llm_client.settings import LLMSettings, get_llm_settings

__all__ = [
    "Generator",
    "GeminiGenerator",
    "LLMSettings",
    "NO_MATCHING_JOBS_MESSAGE",
    "OllamaGenerator",
    "get_generator",
    "get_llm_settings",
    "reset_generator",
]


@lru_cache
def get_generator() -> Generator:
    settings = get_llm_settings()
    if settings.llm_provider == "ollama":
        return OllamaGenerator(settings)
    return GeminiGenerator(settings)


def reset_generator() -> None:
    get_generator.cache_clear()
    get_llm_settings.cache_clear()
