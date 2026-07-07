import pytest

from the_hub_client.models import (
    COUNTRY_CODE_TO_PAYLOAD_COUNTRY,
    CountryCode,
    country_code_to_payload_country,
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
def test_country_code_to_payload_country_maps_all_codes(code, expected):
    assert country_code_to_payload_country(code) == expected
    assert COUNTRY_CODE_TO_PAYLOAD_COUNTRY[code] == expected


def test_country_code_to_payload_country_covers_every_enum_member():
    assert set(COUNTRY_CODE_TO_PAYLOAD_COUNTRY) == set(CountryCode)
