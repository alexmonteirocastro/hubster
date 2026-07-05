import pytest

from the_hub_client.http import HubClientConfig, configure_hub_client, reset_hub_client


@pytest.fixture(autouse=True)
def fast_hub_client():
    configure_hub_client(
        HubClientConfig(
            max_retries=3,
            backoff_factor=0,
            request_delay_seconds=0,
            timeout_seconds=5,
        )
    )
    yield
    reset_hub_client()
