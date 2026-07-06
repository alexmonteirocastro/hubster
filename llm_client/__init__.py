from functools import lru_cache

from llm_client.base import Generator
from llm_client.context import NO_MATCHING_JOBS_MESSAGE
from llm_client.gemini import GeminiGenerator
from llm_client.settings import LLMSettings, get_llm_settings

__all__ = [
    "Generator",
    "GeminiGenerator",
    "LLMSettings",
    "NO_MATCHING_JOBS_MESSAGE",
    "get_generator",
    "get_llm_settings",
    "reset_generator",
]


@lru_cache
def get_generator() -> Generator:
    return GeminiGenerator(get_llm_settings())


def reset_generator() -> None:
    get_generator.cache_clear()
    get_llm_settings.cache_clear()
