import responses

from the_hub_client.models import CountryCode
from the_hub_client.utils import (
    HUB_BASE_URL,
    JOB_LISTINGS_ENDPOINT_ROUTE,
    SINGLE_JOB_ENDPOINT_ROUTE,
    get_all_job_ids_per_country,
    get_full_jobs_picture_by_country,
    get_job_ids_per_page_per_country,
    get_number_of_jobs_and_pages_by_country,
    scrape_job_offer_by_id,
)


@responses.activate
def test_scrape_job_offer_by_id_range_salary(load_fixture):
    job_id = "abc123"
    payload = load_fixture("single_job_range.json")
    responses.add(
        responses.GET,
        f"{HUB_BASE_URL}{SINGLE_JOB_ENDPOINT_ROUTE}/{job_id}",
        json=payload,
    )

    job = scrape_job_offer_by_id(job_id)

    assert job.job_id == job_id
    assert job.job_title == "Backend Engineer"
    assert job.job_role == "backenddeveloper"
    assert job.company == "Acme Corp"
    assert job.company_description == "We build things."
    assert job.job_description == "Build APIs."
    assert job.country == "Denmark"
    assert job.locality == "Copenhagen"
    assert job.remote is True
    assert job.salary_type == "range"
    assert job.salary == "Ranging from 500000 to 700000"
    assert job.equity == "0.1%"


@responses.activate
def test_scrape_job_offer_by_id_competitive_salary(load_fixture):
    job_id = "def456"
    payload = load_fixture("single_job_competitive.json")
    responses.add(
        responses.GET,
        f"{HUB_BASE_URL}{SINGLE_JOB_ENDPOINT_ROUTE}/{job_id}",
        json=payload,
    )

    job = scrape_job_offer_by_id(job_id)

    assert job.salary_type == "competitive"
    assert job.salary == "N/A"
    assert job.equity == "undisclosed"


@responses.activate
def test_scrape_job_offer_by_id_missing_fields_default_to_na(load_fixture):
    job_id = "ghi789"
    payload = load_fixture("single_job_missing_fields.json")
    responses.add(
        responses.GET,
        f"{HUB_BASE_URL}{SINGLE_JOB_ENDPOINT_ROUTE}/{job_id}",
        json=payload,
    )

    job = scrape_job_offer_by_id(job_id)

    assert job.job_title == "Analyst"
    assert job.job_role == "N/A"
    assert job.company == "Gamma Ltd"
    assert job.company_description == ""
    assert job.country == "N/A"
    assert job.locality == "N/A"
    assert job.remote is False
    assert job.salary_type == ""
    assert job.salary == "N/A"
    assert job.equity == "N/A"


@responses.activate
def test_get_job_ids_per_page_per_country(load_fixture):
    payload = load_fixture("jobs_listing_page_1.json")
    responses.add(
        responses.GET,
        f"{HUB_BASE_URL}{JOB_LISTINGS_ENDPOINT_ROUTE}?page=1&countryCode=DK",
        json=payload,
    )

    job_ids = get_job_ids_per_page_per_country(page=1, country=CountryCode.DENMARK)

    assert job_ids == ["job-id-1", "job-id-2"]


@responses.activate
def test_get_number_of_jobs_and_pages_by_country(load_fixture):
    payload = load_fixture("jobs_listing_summary.json")
    responses.add(
        responses.GET,
        f"{HUB_BASE_URL}{JOB_LISTINGS_ENDPOINT_ROUTE}?countryCode=DK",
        json=payload,
    )

    result = get_number_of_jobs_and_pages_by_country(CountryCode.DENMARK)

    assert result.total_jobs == 120
    assert result.number_of_pages == 6
    assert result.jobs_per_page == 20


@responses.activate
def test_get_full_jobs_picture_by_country_maps_role_fields(load_fixture):
    payload = load_fixture("jobs_listing_summary.json")
    responses.add(
        responses.GET,
        f"{HUB_BASE_URL}{JOB_LISTINGS_ENDPOINT_ROUTE}?countryCode=SE",
        json=payload,
    )

    result = get_full_jobs_picture_by_country(CountryCode.SWEDEN)

    assert result.total_jobs == 120
    assert result.remote_jobs == 30
    assert result.paid_jobs == 100
    assert result.unpaid_jobs == 20
    assert result.jobs_per_role.cxo == 1
    assert result.jobs_per_role.human_resources == 2
    assert result.jobs_per_role.business_development == 10
    assert result.jobs_per_role.ux_ui_designer == 15
    assert result.jobs_per_role.backend_developer == 19
    assert result.jobs_per_role.other == 24


@responses.activate
def test_get_all_job_ids_per_country(load_fixture):
    responses.add(
        responses.GET,
        f"{HUB_BASE_URL}{JOB_LISTINGS_ENDPOINT_ROUTE}?page=1&countryCode=NO",
        json=load_fixture("jobs_listing_page_1.json"),
    )
    responses.add(
        responses.GET,
        f"{HUB_BASE_URL}{JOB_LISTINGS_ENDPOINT_ROUTE}?page=2&countryCode=NO",
        json=load_fixture("jobs_listing_page_2.json"),
    )

    job_ids = get_all_job_ids_per_country(
        country=CountryCode.NORWAY,
        pages_in_country=2,
        total_jobs_in_country=4,
    )

    assert job_ids == ["job-id-1", "job-id-2", "job-id-3", "job-id-4"]
    assert len(responses.calls) == 2
