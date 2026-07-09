"""Ollama-backed Generator implementation.

Calls Ollama's OpenAI-compatible chat completions endpoint via requests.
"""

import requests

from llm_client.base import Generator
from llm_client.context import build_generation_prompt
from llm_client.exceptions import GenerationUnavailableError
from llm_client.settings import LLMSettings


class OllamaGenerator(Generator):
    def __init__(
        self,
        settings: LLMSettings,
        session: requests.Session | None = None,
    ):
        self._settings = settings
        self._session = session or requests.Session()

    def generate(self, context: str, question: str) -> str:
        prompt = build_generation_prompt(context, question)
        url = f"{self._settings.ollama_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self._settings.ollama_model,
            "messages": [{"role": "user", "content": prompt}],
        }
        try:
            response = self._session.post(
                url,
                json=payload,
                timeout=self._settings.ollama_timeout_seconds,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise GenerationUnavailableError(str(exc)) from exc

        if not response.ok:
            raise GenerationUnavailableError(
                f"Ollama returned HTTP {response.status_code}: {response.text}"
            )

        try:
            data = response.json()
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise GenerationUnavailableError(
                "Ollama returned an invalid response."
            ) from exc

        if not text or not text.strip():
            raise GenerationUnavailableError("Model returned an empty response.")
        return text.strip()
