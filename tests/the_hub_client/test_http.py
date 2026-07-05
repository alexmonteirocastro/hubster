import requests
import responses

from db.db_utils import _scrape_jobs
from the_hub_client.http import HubClientConfig, configure_hub_client
from the_hub_client.utils import (
    HUB_BASE_URL,
    SINGLE_JOB_ENDPOINT_ROUTE,
    scrape_job_offer_by_id,
)


@responses.activate
def test_hub_get_retries_transient_500_before_succeeding(load_fixture):
    job_id = "retry-job"
    url = f"{HUB_BASE_URL}{SINGLE_JOB_ENDPOINT_ROUTE}/{job_id}"
    payload = load_fixture("single_job_competitive.json")

    responses.add(responses.GET, url, status=500)
    responses.add(responses.GET, url, status=500)
    responses.add(responses.GET, url, json=payload)

    job = scrape_job_offer_by_id(job_id)

    assert job.job_id == job_id
    assert len(responses.calls) == 3


@responses.activate
def test_hub_get_does_not_retry_404():
    job_id = "missing-job"
    url = f"{HUB_BASE_URL}{SINGLE_JOB_ENDPOINT_ROUTE}/{job_id}"
    responses.add(responses.GET, url, status=404)

    try:
        scrape_job_offer_by_id(job_id)
        raise AssertionError("expected HTTPError")
    except requests.HTTPError as exc:
        assert exc.response.status_code == 404

    assert len(responses.calls) == 1


@responses.activate
def test_hub_get_gives_up_after_bounded_retries():
    job_id = "always-fails"
    url = f"{HUB_BASE_URL}{SINGLE_JOB_ENDPOINT_ROUTE}/{job_id}"

    configure_hub_client(
        HubClientConfig(max_retries=2, backoff_factor=0, request_delay_seconds=0)
    )
    responses.add(responses.GET, url, status=500)
    responses.add(responses.GET, url, status=500)
    responses.add(responses.GET, url, status=500)

    try:
        scrape_job_offer_by_id(job_id)
        raise AssertionError("expected HTTPError")
    except requests.HTTPError as exc:
        assert exc.response.status_code == 500

    # 1 initial attempt + 2 retries
    assert len(responses.calls) == 3


@responses.activate
def test_scrape_jobs_skips_persistently_failing_job_and_continues(load_fixture):
    good_id = "good-job"
    bad_id = "bad-job"
    good_url = f"{HUB_BASE_URL}{SINGLE_JOB_ENDPOINT_ROUTE}/{good_id}"
    bad_url = f"{HUB_BASE_URL}{SINGLE_JOB_ENDPOINT_ROUTE}/{bad_id}"
    payload = load_fixture("single_job_competitive.json")

    configure_hub_client(
        HubClientConfig(max_retries=1, backoff_factor=0, request_delay_seconds=0)
    )
    responses.add(responses.GET, bad_url, status=500)
    responses.add(responses.GET, bad_url, status=500)
    responses.add(responses.GET, good_url, json=payload)

    jobs = _scrape_jobs([bad_id, good_id])

    assert len(jobs) == 1
    assert jobs[0].job_id == good_id
