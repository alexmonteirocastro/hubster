import re

from pydantic import BaseModel

from the_hub_client.models import CountryCode

# Country names, adjectives, and major cities → CountryCode.
# Matched with word boundaries; earliest match in the question wins.
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
    ("europe", CountryCode.EUROPE),
    ("european", CountryCode.EUROPE),
]

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


class ExtractedFilters(BaseModel):
    country: CountryCode | None = None
    remote: bool | None = None


def _find_earliest_country_match(question: str) -> CountryCode | None:
    lowered = question.lower()
    best: tuple[int, CountryCode] | None = None

    for term, code in COUNTRY_ALIASES:
        match = re.search(rf"\b{re.escape(term)}\b", lowered)
        if match is None:
            continue
        position = match.start()
        if best is None or position < best[0]:
            best = (position, code)

    return best[1] if best else None


def _detect_remote(question: str) -> bool | None:
    lowered = question.lower()

    for phrase in REMOTE_PHRASES:
        if phrase in lowered:
            return True

    for word in REMOTE_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            return True

    return None


def extract_filters_from_question(question: str) -> ExtractedFilters:
    return ExtractedFilters(
        country=_find_earliest_country_match(question),
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
