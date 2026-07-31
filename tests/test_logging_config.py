import json
import logging
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, patch

from db.settings import get_settings
from logging_config import (
    CHAT_LOGGER_NAME,
    INJECTION_LOGGER_NAME,
    LOG_TEXT_MAX_CHARS,
    configure_logging,
    log_chat_request,
    log_injection_detected,
    reset_logging_config_for_tests,
)


def _full_loki_settings() -> SimpleNamespace:
    return SimpleNamespace(
        grafana_loki_url="https://logs-prod.example/loki/api/v1/push",
        grafana_loki_user_id="123456",
        grafana_loki_api_key="glc_token",
    )


def test_log_chat_request_emits_json_payload(caplog):
    with caplog.at_level(logging.INFO, logger=CHAT_LOGGER_NAME):
        log_chat_request(
            prompt="hello",
            response="world",
            retrieved_jobs=[{"job_id": "j1", "score": 0.91}],
            latency_ms=12,
            status="ok",
            error_type=None,
            generated=True,
            provider="stub",
        )

    assert len(caplog.records) == 1
    payload = json.loads(caplog.records[0].getMessage())
    assert payload["event"] == "chat_request"
    assert payload["prompt"] == "hello"
    assert payload["error_type"] is None
    assert caplog.records[0].event == "chat_request"


def test_log_injection_detected_sets_event_and_source_extras(caplog):
    with caplog.at_level(logging.WARNING, logger=INJECTION_LOGGER_NAME):
        log_injection_detected(
            source="ingestion",
            pattern="###",
            job_id="job-1",
        )

    assert len(caplog.records) == 1
    record = caplog.records[0]
    payload = json.loads(record.getMessage())
    assert payload["event"] == "injection_detected"
    assert payload["source"] == "ingestion"
    assert payload["pattern"] == "###"
    assert payload["job_id"] == "job-1"
    assert record.event == "injection_detected"
    assert record.source == "ingestion"


def test_log_chat_request_truncates_oversized_prompt_and_response(caplog):
    oversized = "x" * (LOG_TEXT_MAX_CHARS + 50)
    with caplog.at_level(logging.INFO, logger=CHAT_LOGGER_NAME):
        log_chat_request(
            prompt=oversized,
            response=oversized,
            retrieved_jobs=[],
            latency_ms=1,
            status="error",
            error_type="QuestionTooLong",
            generated=None,
            provider=None,
        )

    payload = json.loads(caplog.records[0].getMessage())
    assert payload["prompt"] is not None
    assert payload["response"] is not None
    assert len(payload["prompt"]) == LOG_TEXT_MAX_CHARS + len("…[truncated]")
    assert payload["prompt"].endswith("…[truncated]")
    assert payload["response"].endswith("…[truncated]")


def test_configure_logging_warns_on_partial_config(caplog):
    reset_logging_config_for_tests()
    settings = SimpleNamespace(
        grafana_loki_url="https://logs-prod.example/loki/api/v1/push",
        grafana_loki_user_id=None,
        grafana_loki_api_key=None,
    )

    with caplog.at_level(logging.WARNING, logger="logging_config"):
        configure_logging(settings)

    assert "Partial Grafana Loki config ignored" in caplog.text
    assert not any(
        type(handler).__name__ in {"LokiHandler", "LokiQueueHandler"}
        for handler in logging.getLogger().handlers
    )


def test_configure_logging_attaches_queue_handler_when_fully_configured():
    reset_logging_config_for_tests()
    mock_handler = MagicMock()
    mock_handler.level = logging.INFO
    mock_handler.listener = MagicMock()

    with patch("logging_loki.LokiQueueHandler", return_value=mock_handler) as mock_cls:
        configure_logging(_full_loki_settings())

    mock_cls.assert_called_once_with(
        ANY,
        url="https://logs-prod.example/loki/api/v1/push",
        tags={"app": "hubster"},
        auth=("123456", "glc_token"),
        props_to_labels=["event", "source"],
    )
    assert mock_handler in logging.getLogger().handlers


def test_configure_logging_is_idempotent():
    reset_logging_config_for_tests()
    mock_handler = MagicMock()
    mock_handler.level = logging.INFO
    mock_handler.listener = MagicMock()

    with patch("logging_loki.LokiQueueHandler", return_value=mock_handler) as mock_cls:
        configure_logging(_full_loki_settings())
        configure_logging(_full_loki_settings())

    assert mock_cls.call_count == 1
    assert logging.getLogger().handlers.count(mock_handler) == 1


def test_reset_logging_config_allows_reconfigure():
    reset_logging_config_for_tests()
    mock_handler = MagicMock()
    mock_handler.level = logging.INFO
    mock_handler.listener = MagicMock()

    with patch("logging_loki.LokiQueueHandler", return_value=mock_handler):
        configure_logging(_full_loki_settings())

    reset_logging_config_for_tests()
    assert mock_handler not in logging.getLogger().handlers
    mock_handler.listener.stop.assert_called()

    # get_settings cache is unrelated; ensure flag reset alone is enough.
    get_settings.cache_clear()
