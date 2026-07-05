"""Outbound HTTP client for The Hub API.

Wraps ``requests`` with retry, exponential backoff, client-side pacing, and
fail-fast on 4xx. All Hub API calls in ``the_hub_client.utils`` go through
``hub_get()``.

Known limitations (conscious deferrals — revisit before scaling ingestion):

* **Sequential-only pacing.** Module-level ``_session``, ``_config``, and
  ``_last_request_at`` are not thread-safe. Ingestion today is strictly
  sequential (``_scrape_jobs`` fetches one job at a time), so pacing is correct.
  If ingestion is parallelized (e.g. ``ThreadPoolExecutor`` per country or
  batch), revisit this module: add a ``threading.Lock`` around pacing and/or
  per-worker sessions — do not assume the current globals survive concurrency.

* **No backoff jitter.** ``Retry.backoff_factor`` produces deterministic retry
  timing. Fine for a single-process script; multiple parallel workers can
  thundering-herd the upstream API. Add random jitter before running concurrent
  ingestion workers.

* **Single timeout for connect and read.** ``timeout_seconds`` is passed as a
  scalar to ``requests`` (same limit for both phases). Split into
  ``timeout=(connect, read)`` if hangs need finer diagnosis.

* **Config loaded once per process.** ``get_hub_client_config()`` caches env
  on first use (same pattern as ``get_qdrant_client()``). Mid-process env
  changes have no effect until ``configure_hub_client()`` /
  ``reset_hub_client()`` is called.

Follow-up (not in scope for ALE-71): retry/backoff metrics so degrading upstream
API health is visible before outright failures.
"""

import os
import time
from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

RETRYABLE_STATUS_CODES = (500, 502, 503, 504)


@dataclass(frozen=True)
class HubClientConfig:
    max_retries: int = 3
    backoff_factor: float = 1.0
    request_delay_seconds: float = 0.25
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "HubClientConfig":
        return cls(
            max_retries=int(os.getenv("HUB_CLIENT_MAX_RETRIES", "3")),
            backoff_factor=float(os.getenv("HUB_CLIENT_BACKOFF_FACTOR", "1.0")),
            request_delay_seconds=float(os.getenv("HUB_CLIENT_REQUEST_DELAY", "0.25")),
            timeout_seconds=float(os.getenv("HUB_CLIENT_TIMEOUT", "30.0")),
        )


_session: requests.Session | None = None
_config: HubClientConfig | None = None
_last_request_at: float | None = None


def get_hub_client_config() -> HubClientConfig:
    """Return cached config, loading from env on first call."""
    global _config
    if _config is None:
        _config = HubClientConfig.from_env()
    return _config


def configure_hub_client(config: HubClientConfig | None = None) -> None:
    """Replace client config and drop cached session (used in tests).

    Pass ``None`` to reload from env on the next ``hub_get()`` call.
    """
    global _config, _session, _last_request_at
    _config = config
    _session = None
    _last_request_at = None


def reset_hub_client() -> None:
    configure_hub_client(None)


def _build_session(config: HubClientConfig) -> requests.Session:
    retry = Retry(
        total=config.max_retries,
        connect=config.max_retries,
        read=config.max_retries,
        backoff_factor=config.backoff_factor,
        status_forcelist=list(RETRYABLE_STATUS_CODES),
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = _build_session(get_hub_client_config())
    return _session


def _apply_pacing(config: HubClientConfig) -> None:
    """Enforce minimum delay between requests. Sequential ingestion only — see module docstring."""
    global _last_request_at
    if config.request_delay_seconds <= 0:
        return
    now = time.monotonic()
    if _last_request_at is not None:
        elapsed = now - _last_request_at
        if elapsed < config.request_delay_seconds:
            time.sleep(config.request_delay_seconds - elapsed)
    _last_request_at = time.monotonic()


def hub_get(url: str) -> requests.Response:
    """GET with retry, exponential backoff, pacing, and fail-fast on 4xx."""
    config = get_hub_client_config()
    _apply_pacing(config)
    response = _get_session().get(url, timeout=config.timeout_seconds)
    response.raise_for_status()
    return response
