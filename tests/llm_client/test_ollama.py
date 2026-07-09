import json
from unittest.mock import MagicMock

import pytest
import requests
import responses

from llm_client.exceptions import GenerationUnavailableError
from llm_client.ollama import OllamaGenerator, native_ollama_base_url
from llm_client.settings import LLMSettings

_CHAT_URL = "http://localhost:11434/api/chat"


def _settings(**overrides) -> LLMSettings:
    defaults = {
        "llm_provider": "ollama",
        "gemini_api_key": "",
        "gemini_model": "gemini-2.5-flash",
        "max_retries": 3,
        "backoff_factor": 1.0,
        "timeout_seconds": 30.0,
        "ollama_base_url": "http://localhost:11434/v1",
        "ollama_model": "qwen3:4b",
        "ollama_timeout_seconds": 60.0,
        "ollama_max_chars_per_job": 1200,
        "ollama_num_predict": 256,
    }
    defaults.update(overrides)
    return LLMSettings.model_construct(**defaults)


def _stream_body(chunks: list[str]) -> str:
    lines = [
        json.dumps({"message": {"role": "assistant", "content": chunk}, "done": False})
        for chunk in chunks
    ]
    lines.append(
        json.dumps({"message": {"role": "assistant", "content": ""}, "done": True})
    )
    return "\n".join(lines) + "\n"


def test_native_ollama_base_url_strips_v1_suffix():
    assert (
        native_ollama_base_url("http://localhost:11434/v1") == "http://localhost:11434"
    )


@responses.activate
def test_ollama_generate_returns_trimmed_text():
    responses.add(
        responses.POST,
        _CHAT_URL,
        body=_stream_body(["  hello ", "world  "]),
        stream=True,
        content_type="application/x-ndjson",
    )
    generator = OllamaGenerator(_settings())

    answer = generator.generate("job context", "what roles?")

    assert answer == "hello world"
    assert len(responses.calls) == 1
    request_body = json.loads(responses.calls[0].request.body)
    assert request_body["model"] == "qwen3:4b"
    assert request_body["stream"] is True
    assert request_body["think"] is False
    assert request_body["options"]["num_predict"] == 256
    assert "job context" in request_body["messages"][0]["content"]


@responses.activate
def test_ollama_generate_respects_custom_num_predict():
    responses.add(
        responses.POST,
        _CHAT_URL,
        body=_stream_body(["ok"]),
        stream=True,
        content_type="application/x-ndjson",
    )
    generator = OllamaGenerator(_settings(ollama_num_predict=128))

    generator.generate("job context", "what roles?")

    request_body = json.loads(responses.calls[0].request.body)
    assert request_body["options"]["num_predict"] == 128


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
        _CHAT_URL,
        status=500,
        body="server error",
        stream=True,
    )
    generator = OllamaGenerator(_settings())

    with pytest.raises(GenerationUnavailableError, match="HTTP 500"):
        generator.generate("job context", "what roles?")


@responses.activate
def test_ollama_raises_when_response_is_empty():
    responses.add(
        responses.POST,
        _CHAT_URL,
        body=_stream_body(["   "]),
        stream=True,
        content_type="application/x-ndjson",
    )
    generator = OllamaGenerator(_settings())

    with pytest.raises(GenerationUnavailableError, match="empty response"):
        generator.generate("job context", "what roles?")


@responses.activate
def test_ollama_raises_when_response_shape_is_invalid():
    responses.add(
        responses.POST,
        _CHAT_URL,
        body='{"unexpected": true}\n',
        stream=True,
        content_type="application/x-ndjson",
    )
    generator = OllamaGenerator(_settings())

    with pytest.raises(GenerationUnavailableError, match="empty response"):
        generator.generate("job context", "what roles?")
