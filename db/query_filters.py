import re

from pydantic import BaseModel

from the_hub_client.models import CountryCode

# Country names, adjectives, and major cities → CountryCode.
# Matched with word boundaries. When multiple distinct countries appear, no filter
# is applied ("when uncertain, don't guess" — see ADR-0002 Decision 3).
COUNTRY_ALIASES: list[tuple[str, CountryCode]] = [
    ("denmark", CountryCode.DENMARK),
    ("danish", CountryCode.DENMARK),
    ("copenhagen", CountryCode.DENMARK),
    ("sweden", CountryCode.SWEDEN),
    ("swedish", CountryCode.SWEDEN),
    ("stockholm", CountryCode.SWEDEN),
    ("norway", CountryCode.NORWAY),
    ("norwegian", CountryCode.NORWAY),
    ("oslo", CountryCode.NORWAY),
    ("finland", CountryCode.FINLAND),
    ("finnish", CountryCode.FINLAND),
    ("helsinki", CountryCode.FINLAND),
    ("iceland", CountryCode.ICELAND),
    ("icelandic", CountryCode.ICELAND),
    ("reykjavik", CountryCode.ICELAND),
    # TODO(ALE-82): add ("europe", EU) and ("european", EU) once verified against live Hub payloads.
]

REMOTE_FALSE_PHRASES = (
    "not remote",
    "no remote",
    "non-remote",
    "non remote",
    "don't want remote",
    "on-site only",
    "on site only",
    "in-office",
    "in office",
    "must be on-site",
    "must be on site",
)

REMOTE_PHRASES = (
    "work from home",
    "work-from-home",
    "fully remote",
    "remote work",
)

REMOTE_WORDS = (
    "remote",
    "wfh",
    "telecommute",
)

_COUNTRY_PATTERNS: list[tuple[re.Pattern[str], CountryCode]] = [
    (re.compile(rf"\b{re.escape(term)}\b"), code) for term, code in COUNTRY_ALIASES
]
_REMOTE_WORD_PATTERNS = [re.compile(rf"\b{re.escape(word)}\b") for word in REMOTE_WORDS]


class ExtractedFilters(BaseModel):
    country: CountryCode | None = None
    remote: bool | None = None


def _find_country_match(question: str) -> CountryCode | None:
    lowered = question.lower()
    earliest_by_code: dict[CountryCode, int] = {}

    for pattern, code in _COUNTRY_PATTERNS:
        match = pattern.search(lowered)
        if match is None:
            continue
        position = match.start()
        if code not in earliest_by_code or position < earliest_by_code[code]:
            earliest_by_code[code] = position

    if not earliest_by_code:
        return None
    if len(earliest_by_code) > 1:
        return None

    return next(iter(earliest_by_code))


def _detect_remote(question: str) -> bool | None:
    lowered = question.lower()

    for phrase in REMOTE_FALSE_PHRASES:
        if phrase in lowered:
            return False

    for phrase in REMOTE_PHRASES:
        if phrase in lowered:
            return True

    for pattern in _REMOTE_WORD_PATTERNS:
        if pattern.search(lowered):
            return True

    return None


def extract_filters_from_question(question: str) -> ExtractedFilters:
    return ExtractedFilters(
        country=_find_country_match(question),
        remote=_detect_remote(question),
    )


def resolve_chat_filters(
    question: str,
    *,
    explicit_country: CountryCode | None = None,
    explicit_remote: bool | None = None,
) -> ExtractedFilters:
    """Apply explicit caller filters over question-text extraction (ADR-0002 Decision 3)."""
    extracted = extract_filters_from_question(question)
    return ExtractedFilters(
        country=explicit_country if explicit_country is not None else extracted.country,
        remote=explicit_remote if explicit_remote is not None else extracted.remote,
    )
