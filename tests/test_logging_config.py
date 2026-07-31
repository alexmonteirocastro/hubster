import json
import logging

from logging_config import (
    CHAT_LOGGER_NAME,
    INJECTION_LOGGER_NAME,
    log_chat_request,
    log_injection_detected,
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
