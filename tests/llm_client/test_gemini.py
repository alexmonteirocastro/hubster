from unittest.mock import MagicMock, patch

import pytest
from google.genai import errors as genai_errors

from llm_client.exceptions import (
    GenerationConfigurationError,
    GenerationUnavailableError,
)
from llm_client.gemini import GeminiGenerator
from llm_client.settings import LLMSettings


def _settings(**overrides) -> LLMSettings:
    defaults = {
        "gemini_api_key": "test-key",
        "gemini_model": "gemini-2.5-flash",
        "max_retries": 2,
        "backoff_factor": 0,
        "timeout_seconds": 30.0,
    }
    defaults.update(overrides)
    return LLMSettings.model_construct(**defaults)


def _mock_response(text: str):
    response = MagicMock()
    response.text = text
    return response


@patch("llm_client.gemini.genai.Client")
def test_gemini_client_uses_millisecond_http_timeout(mock_client_cls):
    GeminiGenerator(_settings(timeout_seconds=30.0))

    mock_client_cls.assert_called_once_with(
        api_key="test-key",
        http_options={"timeout": 30000},
    )


def test_gemini_generate_returns_trimmed_text():
    client = MagicMock()
    client.models.generate_content.return_value = _mock_response("  hello world  ")
    generator = GeminiGenerator(_settings(), client=client)

    answer = generator.generate("job context", "what roles?")

    assert answer == "hello world"
    client.models.generate_content.assert_called_once()


def test_gemini_retries_transient_server_error_before_succeeding():
    client = MagicMock()
    client.models.generate_content.side_effect = [
        genai_errors.ServerError(503, {"error": {"message": "unavailable"}}, None),
        _mock_response("recovered"),
    ]
    generator = GeminiGenerator(_settings(), client=client)

    answer = generator.generate("job context", "what roles?")

    assert answer == "recovered"
    assert client.models.generate_content.call_count == 2


def test_gemini_retries_rate_limit_before_succeeding():
    client = MagicMock()
    client.models.generate_content.side_effect = [
        genai_errors.ClientError(429, {"error": {"message": "rate limited"}}, None),
        _mock_response("after limit"),
    ]
    generator = GeminiGenerator(_settings(), client=client)

    answer = generator.generate("job context", "what roles?")

    assert answer == "after limit"
    assert client.models.generate_content.call_count == 2


def test_gemini_does_not_retry_invalid_api_key():
    client = MagicMock()
    client.models.generate_content.side_effect = genai_errors.ClientError(
        403, {"error": {"message": "invalid key"}}, None
    )
    generator = GeminiGenerator(_settings(max_retries=3), client=client)

    with pytest.raises(GenerationConfigurationError):
        generator.generate("job context", "what roles?")

    assert client.models.generate_content.call_count == 1


def test_gemini_gives_up_after_bounded_retries():
    client = MagicMock()
    client.models.generate_content.side_effect = genai_errors.ServerError(
        503, {"error": {"message": "unavailable"}}, None
    )
    generator = GeminiGenerator(_settings(max_retries=2), client=client)

    with pytest.raises(GenerationUnavailableError):
        generator.generate("job context", "what roles?")

    assert client.models.generate_content.call_count == 3


def test_gemini_raises_when_response_is_empty():
    client = MagicMock()
    client.models.generate_content.return_value = _mock_response("   ")
    generator = GeminiGenerator(_settings(), client=client)

    with pytest.raises(GenerationUnavailableError):
        generator.generate("job context", "what roles?")


@patch("llm_client.gemini.time.sleep")
def test_gemini_applies_exponential_backoff(mock_sleep):
    client = MagicMock()
    client.models.generate_content.side_effect = [
        genai_errors.ServerError(503, {"error": {"message": "unavailable"}}, None),
        _mock_response("ok"),
    ]
    generator = GeminiGenerator(
        _settings(max_retries=2, backoff_factor=1.5), client=client
    )

    generator.generate("job context", "what roles?")

    mock_sleep.assert_called_once_with(1.5)
