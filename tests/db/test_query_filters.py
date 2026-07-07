import pytest

from db.query_filters import ExtractedFilters, extract_filters_from_question, resolve_chat_filters
from the_hub_client.models import CountryCode


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Any frontend developer roles in Sweden?", CountryCode.SWEDEN),
        ("Looking for a Danish backend engineer", CountryCode.DENMARK),
        ("Python jobs in Copenhagen", CountryCode.DENMARK),
        ("Product roles near Stockholm", CountryCode.SWEDEN),
        ("Openings in Oslo for backend work", CountryCode.NORWAY),
        ("Helsinki-based analyst roles", CountryCode.FINLAND),
        ("Engineering jobs in Reykjavik", CountryCode.ICELAND),
    ],
)
def test_extract_filters_from_question_detects_country_signals(question, expected):
    result = extract_filters_from_question(question)

    assert result == ExtractedFilters(country=expected, remote=None)


@pytest.mark.parametrize(
    "question",
    [
        "Any fully remote Python jobs?",
        "Looking for work from home backend roles",
        "Is this position remote or on-site?",
        "WFH-friendly frontend openings",
    ],
)
def test_extract_filters_from_question_detects_remote_signals(question):
    result = extract_filters_from_question(question)

    assert result.country is None
    assert result.remote is True


def test_extract_filters_from_question_returns_none_when_no_signals():
    result = extract_filters_from_question("What backend roles are open right now?")

    assert result == ExtractedFilters(country=None, remote=None)


def test_resolve_chat_filters_uses_explicit_country_over_question_text():
    result = resolve_chat_filters(
        "frontend roles in Sweden",
        explicit_country=CountryCode.DENMARK,
    )

    assert result.country == CountryCode.DENMARK
    assert result.remote is None


def test_resolve_chat_filters_uses_explicit_remote_over_question_text():
    result = resolve_chat_filters(
        "remote backend roles in Denmark",
        explicit_remote=False,
    )

    assert result.country == CountryCode.DENMARK
    assert result.remote is False


def test_resolve_chat_filters_derives_from_question_when_explicit_values_missing():
    result = resolve_chat_filters(
        "remote backend python roles in Denmark",
    )

    assert result.country == CountryCode.DENMARK
    assert result.remote is True
