from unittest.mock import MagicMock

import pytest
import requests
import responses

from llm_client.exceptions import GenerationUnavailableError
from llm_client.ollama import OllamaGenerator
from llm_client.settings import LLMSettings

_CHAT_COMPLETIONS_URL = "http://localhost:11434/v1/chat/completions"


def _settings(**overrides) -> LLMSettings:
    defaults = {
        "llm_provider": "ollama",
        "gemini_api_key": "",
        "gemini_model": "gemini-2.5-flash",
        "max_retries": 3,
        "backoff_factor": 1.0,
        "timeout_seconds": 30.0,
        "ollama_base_url": "http://localhost:11434/v1",
        "ollama_model": "qwen3:8b",
        "ollama_timeout_seconds": 60.0,
    }
    defaults.update(overrides)
    return LLMSettings.model_construct(**defaults)


@responses.activate
def test_ollama_generate_returns_trimmed_text():
    responses.add(
        responses.POST,
        _CHAT_COMPLETIONS_URL,
        json={"choices": [{"message": {"content": "  hello world  "}}]},
    )
    generator = OllamaGenerator(_settings())

    answer = generator.generate("job context", "what roles?")

    assert answer == "hello world"
    assert len(responses.calls) == 1
    request_body = responses.calls[0].request.body
    assert b"qwen3:8b" in request_body
    assert b"job context" in request_body


def test_ollama_connection_refused_raises_unavailable():
    session = MagicMock()
    session.post.side_effect = requests.ConnectionError("Connection refused")
    generator = OllamaGenerator(_settings(), session=session)

    with pytest.raises(GenerationUnavailableError, match="Connection refused"):
        generator.generate("job context", "what roles?")


def test_ollama_timeout_raises_unavailable():
    session = MagicMock()
    session.post.side_effect = requests.Timeout("timed out")
    generator = OllamaGenerator(_settings(), session=session)

    with pytest.raises(GenerationUnavailableError, match="timed out"):
        generator.generate("job context", "what roles?")


@responses.activate
def test_ollama_non_2xx_raises_unavailable():
    responses.add(
        responses.POST,
        _CHAT_COMPLETIONS_URL,
        status=500,
        body="server error",
    )
    generator = OllamaGenerator(_settings())

    with pytest.raises(GenerationUnavailableError, match="HTTP 500"):
        generator.generate("job context", "what roles?")


@responses.activate
def test_ollama_raises_when_response_is_empty():
    responses.add(
        responses.POST,
        _CHAT_COMPLETIONS_URL,
        json={"choices": [{"message": {"content": "   "}}]},
    )
    generator = OllamaGenerator(_settings())

    with pytest.raises(GenerationUnavailableError, match="empty response"):
        generator.generate("job context", "what roles?")


@responses.activate
def test_ollama_raises_when_response_shape_is_invalid():
    responses.add(
        responses.POST,
        _CHAT_COMPLETIONS_URL,
        json={"choices": []},
    )
    generator = OllamaGenerator(_settings())

    with pytest.raises(GenerationUnavailableError, match="invalid response"):
        generator.generate("job context", "what roles?")
