"""Shared structured logging setup for API and ingestion (ADR-0015).

Attaches a Grafana Cloud Loki handler when credentials are configured via
Settings. Without credentials, structured logs still go to the root logger
(stderr) so local/CI behavior is unchanged.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from db.settings import Settings, get_settings

_configured = False

CHAT_LOGGER_NAME = "hubster.chat"
INJECTION_LOGGER_NAME = "hubster.injection"

_LOKI_LABEL_PROPS = ["event", "source"]


def configure_logging(settings: Settings | None = None) -> None:
    """Idempotent logging setup for FastAPI and ingestion entrypoints."""
    global _configured
    if _configured:
        return

    if not logging.root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        )

    settings = settings or get_settings()
    url = settings.grafana_loki_url
    user_id = settings.grafana_loki_user_id
    api_key = settings.grafana_loki_api_key
    configured_count = sum(1 for value in (url, user_id, api_key) if value)

    if configured_count == 3:
        # Imported lazily so tests/CI without the dep path stay light; the
        # package is a declared runtime dependency when Loki is used.
        from logging_loki import LokiHandler

        handler = LokiHandler(
            url=url,
            tags={"app": "hubster"},
            auth=(user_id, api_key),
            props_to_labels=list(_LOKI_LABEL_PROPS),
        )
        handler.setLevel(logging.INFO)
        logging.getLogger().addHandler(handler)
    elif configured_count > 0:
        logging.getLogger(__name__).warning(
            "Partial Grafana Loki config ignored "
            "(need GRAFANA_LOKI_URL, GRAFANA_LOKI_USER_ID, and GRAFANA_LOKI_API_KEY)."
        )

    _configured = True


def reset_logging_config_for_tests() -> None:
    """Allow tests to re-run configure_logging (not for production use)."""
    global _configured
    _configured = False


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
        prompt=prompt,
        response=response,
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
        fields["question"] = question
    _emit_structured(
        logging.getLogger(INJECTION_LOGGER_NAME),
        logging.WARNING,
        event="injection_detected",
        source=source,
        **fields,
    )
