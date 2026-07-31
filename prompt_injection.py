"""Closed-set prompt-injection pattern matching (ADR-0012 / ADR-0015).

Shared by ingestion sanitization (strip-and-log) and `/chat` user-query
detection (log-only, never alters the request).
"""

from __future__ import annotations

import re

# ADR-0012 Decision 3: closed deterministic injection patterns.
INJECTION_PATTERNS: tuple[str, ...] = (
    "ignore previous instructions",
    "ignore all previous instructions",
    "disregard the above",
    "disregard all previous instructions",
    "system:",
    "assistant:",
    "###",
)

_INJECTION_PATTERN_REGEX = re.compile(
    "|".join(re.escape(pattern) for pattern in INJECTION_PATTERNS),
    re.IGNORECASE,
)


def _canonical_pattern(matched: str) -> str:
    return next(
        (
            pattern
            for pattern in INJECTION_PATTERNS
            if matched.casefold() == pattern.casefold()
        ),
        matched,
    )


def find_injection_patterns(text: str) -> list[str]:
    """Return canonical patterns found in ``text`` (detect-only, no mutation)."""
    matched_patterns: list[str] = []
    for match in _INJECTION_PATTERN_REGEX.finditer(text):
        canonical = _canonical_pattern(match.group(0))
        if canonical not in matched_patterns:
            matched_patterns.append(canonical)
    return matched_patterns


def sanitize_document_text(document_text: str) -> tuple[str, list[str]]:
    """Strip obvious injection patterns from document_text.

    Returns sanitized text and the canonical matched patterns (ADR-0012 Decisions 3–4).
    """
    matched_patterns: list[str] = []

    def _record_and_strip(match: re.Match[str]) -> str:
        matched_patterns.append(_canonical_pattern(match.group(0)))
        return ""

    sanitized = _INJECTION_PATTERN_REGEX.sub(_record_and_strip, document_text)
    return sanitized, matched_patterns
