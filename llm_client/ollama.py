"""Ollama-backed Generator implementation.

Uses Ollama's native /api/chat endpoint with streaming so long CPU runs are not
cut off by the ~5 minute non-streaming server limit.
"""

import json
from urllib.parse import urlparse

import requests

from llm_client.base import Generator
from llm_client.context import build_generation_prompt
from llm_client.exceptions import GenerationUnavailableError
from llm_client.settings import LLMSettings


def native_ollama_base_url(base_url: str) -> str:
    """Map OpenAI-compatible base (…/v1) to Ollama native root.

    Assumes OLLAMA_BASE_URL is either a root (http://host:11434) or the
    documented OpenAI-compatible suffix (http://host:11434/v1). Custom path
    segments other than /v1 are not supported.
    """
    trimmed = base_url.rstrip("/")
    if trimmed.endswith("/v1"):
        return trimmed[:-3]
    parsed = urlparse(trimmed)
    if parsed.path in ("", "/"):
        return trimmed
    return f"{parsed.scheme}://{parsed.netloc}"


class OllamaGenerator(Generator):
    def __init__(
        self,
        settings: LLMSettings,
        session: requests.Session | None = None,
    ):
        self._settings = settings
        self._session = session or requests.Session()

    @property
    def settings(self) -> LLMSettings:
        return self._settings

    def max_chars_per_job(self) -> int | None:
        return self._settings.ollama_max_chars_per_job

    def generate(self, context: str, question: str) -> str:
        prompt = build_generation_prompt(context, question)
        url = f"{native_ollama_base_url(self._settings.ollama_base_url)}/api/chat"
        payload = {
            "model": self._settings.ollama_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True,
            "think": False,
            "options": {
                "num_predict": self._settings.ollama_num_predict,
            },
        }
        try:
            response = self._session.post(
                url,
                json=payload,
                timeout=self._settings.ollama_timeout_seconds,
                stream=True,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise GenerationUnavailableError(str(exc)) from exc

        if not response.ok:
            body = response.text
            raise GenerationUnavailableError(
                f"Ollama returned HTTP {response.status_code}: {body}"
            )

        text = self._collect_streamed_content(response)
        if not text:
            raise GenerationUnavailableError("Model returned an empty response.")
        return text

    @staticmethod
    def _collect_streamed_content(response: requests.Response) -> str:
        parts: list[str] = []
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            try:
                chunk = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            message = chunk.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, str) and content:
                parts.append(content)
        return "".join(parts).strip()
