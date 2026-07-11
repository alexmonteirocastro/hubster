import pytest

from the_hub_client.models import (
    COUNTRY_CODE_TO_HUB_COUNTRY_NAME,
    EU_COUNTRY_FILTER_EXCLUSIONS,
    CountryCode,
    country_code_to_hub_country_name,
)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (CountryCode.DENMARK, "Denmark"),
        (CountryCode.SWEDEN, "Sweden"),
        (CountryCode.NORWAY, "Norway"),
        (CountryCode.FINLAND, "Finland"),
        (CountryCode.ICELAND, "Iceland"),
        (CountryCode.EUROPE, "Europe"),
    ],
)
def test_country_code_to_hub_country_name_maps_all_codes(code, expected):
    assert country_code_to_hub_country_name(code) == expected
    assert COUNTRY_CODE_TO_HUB_COUNTRY_NAME[code] == expected


def test_country_code_to_hub_country_name_covers_every_enum_member():
    assert set(COUNTRY_CODE_TO_HUB_COUNTRY_NAME) == set(CountryCode)


def test_eu_country_filter_exclusions_cover_nordics_and_unknown():
    assert EU_COUNTRY_FILTER_EXCLUSIONS == [
        "Denmark",
        "Sweden",
        "Norway",
        "Finland",
        "Iceland",
        "N/A",
    ]
