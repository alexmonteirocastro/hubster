"""Shared structured logging setup for API and ingestion (ADR-0015).

Attaches a Grafana Cloud Loki queue handler when credentials are configured via
Settings. Without credentials, structured logs still go to the root logger
(stderr) so local/CI behavior is unchanged.
"""

from __future__ import annotations

import json
import logging
from queue import Queue
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from db.settings import Settings

_configured = False
_loki_handler: logging.Handler | None = None

CHAT_LOGGER_NAME = "hubster.chat"
INJECTION_LOGGER_NAME = "hubster.injection"

_LOKI_LABEL_PROPS = ["event", "source"]
# Bound free-text fields shipped to Loki (prompt/response/question), independent
# of request validation, so oversized payloads cannot inflate log volume.
LOG_TEXT_MAX_CHARS = 1000


def configure_logging(settings: Settings | None = None) -> None:
    """Idempotent logging setup for FastAPI and ingestion entrypoints."""
    global _configured, _loki_handler
    if _configured:
        return

    if not logging.root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        )

    if settings is None:
        from db.settings import get_settings

        settings = get_settings()
    url = settings.grafana_loki_url
    user_id = settings.grafana_loki_user_id
    api_key = settings.grafana_loki_api_key
    configured_count = sum(1 for value in (url, user_id, api_key) if value)

    if configured_count == 3:
        # Queue-based delivery keeps Loki HTTP off the request/ingestion path
        # (ADR-0015 Decision 1 — direct push, no Collector).
        from logging_loki import LokiQueueHandler

        handler = LokiQueueHandler(
            Queue(-1),
            url=url,
            tags={"app": "hubster"},
            auth=(user_id, api_key),
            props_to_labels=list(_LOKI_LABEL_PROPS),
        )
        handler.setLevel(logging.INFO)
        logging.getLogger().addHandler(handler)
        _loki_handler = handler
    elif configured_count > 0:
        logging.getLogger(__name__).warning(
            "Partial Grafana Loki config ignored "
            "(need GRAFANA_LOKI_URL, GRAFANA_LOKI_USER_ID, and GRAFANA_LOKI_API_KEY)."
        )

    _configured = True


def reset_logging_config_for_tests() -> None:
    """Allow tests to re-run configure_logging (not for production use)."""
    global _configured, _loki_handler
    if _loki_handler is not None:
        root = logging.getLogger()
        root.removeHandler(_loki_handler)
        listener = getattr(_loki_handler, "listener", None)
        if listener is not None:
            listener.stop()
        _loki_handler = None
    _configured = False


def _truncate_log_text(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) <= LOG_TEXT_MAX_CHARS:
        return value
    return f"{value[:LOG_TEXT_MAX_CHARS]}…[truncated]"


def _emit_structured(
    logger: logging.Logger,
    level: int,
    *,
    event: str,
    source: str | None = None,
    **fields: Any,
) -> None:
    payload: dict[str, Any] = {"event": event, **fields}
    if source is not None:
        payload["source"] = source
    extra: dict[str, Any] = {"event": event}
    if source is not None:
        extra["source"] = source
    logger.log(level, json.dumps(payload, ensure_ascii=False, default=str), extra=extra)


def log_chat_request(
    *,
    prompt: str,
    response: str | None,
    retrieved_jobs: list[dict[str, Any]],
    latency_ms: int,
    status: str,
    error_type: str | None,
    generated: bool | None,
    provider: str | None,
) -> None:
    """Emit one structured log entry per `/chat` request (ADR-0015 Decision 2)."""
    _emit_structured(
        logging.getLogger(CHAT_LOGGER_NAME),
        logging.INFO,
        event="chat_request",
        prompt=_truncate_log_text(prompt),
        response=_truncate_log_text(response),
        retrieved_jobs=retrieved_jobs,
        latency_ms=latency_ms,
        status=status,
        error_type=error_type,
        generated=generated,
        provider=provider,
    )


def log_injection_detected(
    *,
    source: str,
    pattern: str,
    job_id: str | None = None,
    question: str | None = None,
) -> None:
    """Log a closed-set injection match (ADR-0015 Decisions 5–6)."""
    fields: dict[str, Any] = {"pattern": pattern}
    if job_id is not None:
        fields["job_id"] = job_id
    if question is not None:
        fields["question"] = _truncate_log_text(question)
    _emit_structured(
        logging.getLogger(INJECTION_LOGGER_NAME),
        logging.WARNING,
        event="injection_detected",
        source=source,
        **fields,
    )
