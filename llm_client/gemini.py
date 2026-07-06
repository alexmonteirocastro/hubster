"""Gemini-backed Generator implementation.

Wraps the Google GenAI SDK with retry, exponential backoff, and fail-fast on
non-retryable client errors (4xx other than 429).
"""

import time

from google import genai
from google.genai import errors as genai_errors

from llm_client.base import Generator
from llm_client.context import build_generation_prompt
from llm_client.exceptions import (
    GenerationConfigurationError,
    GenerationError,
    GenerationRateLimitError,
    GenerationUnavailableError,
)
from llm_client.settings import LLMSettings

RETRYABLE_CLIENT_STATUS_CODES = {429}


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, genai_errors.ServerError):
        return True
    if isinstance(exc, genai_errors.ClientError):
        return exc.code in RETRYABLE_CLIENT_STATUS_CODES
    return isinstance(exc, (ConnectionError, TimeoutError, OSError))


def _translate_error(exc: Exception) -> GenerationError:
    if isinstance(exc, genai_errors.ClientError):
        if exc.code in RETRYABLE_CLIENT_STATUS_CODES:
            return GenerationRateLimitError(str(exc))
        return GenerationConfigurationError(str(exc))
    if isinstance(exc, genai_errors.ServerError):
        return GenerationUnavailableError(str(exc))
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return GenerationUnavailableError(str(exc))
    return GenerationUnavailableError(str(exc))


class GeminiGenerator(Generator):
    def __init__(self, settings: LLMSettings, client: genai.Client | None = None):
        self._settings = settings
        self._client = client or genai.Client(
            api_key=settings.gemini_api_key,
            # google-genai HttpOptions.timeout is in milliseconds (see genai.types.HttpOptions).
            http_options={"timeout": int(settings.timeout_seconds * 1000)},
        )

    def generate(self, context: str, question: str) -> str:
        prompt = build_generation_prompt(context, question)
        return self._generate_with_retry(prompt)

    def _generate_with_retry(self, prompt: str) -> str:
        last_exc: Exception | None = None
        for attempt in range(self._settings.max_retries + 1):
            try:
                response = self._client.models.generate_content(
                    model=self._settings.gemini_model,
                    contents=prompt,
                )
                text = response.text
                if not text or not text.strip():
                    raise GenerationUnavailableError("Model returned an empty response.")
                return text.strip()
            except GenerationError:
                raise
            except Exception as exc:
                if not _is_retryable(exc) or attempt >= self._settings.max_retries:
                    raise _translate_error(exc) from exc
                last_exc = exc
                if self._settings.backoff_factor > 0:
                    time.sleep(self._settings.backoff_factor * (2**attempt))

        raise GenerationUnavailableError("Generation failed after retries.") from last_exc
