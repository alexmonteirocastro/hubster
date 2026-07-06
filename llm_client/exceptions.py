class GenerationError(Exception):
    """Base error for generation-layer failures."""


class GenerationConfigurationError(GenerationError):
    """Invalid or missing generation configuration (non-retryable)."""


class GenerationRateLimitError(GenerationError):
    """Upstream rate limit exceeded after retries."""


class GenerationUnavailableError(GenerationError):
    """Upstream provider unavailable or returned an invalid response."""
