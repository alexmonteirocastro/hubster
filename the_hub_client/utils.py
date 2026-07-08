from markdownify import markdownify as md

from the_hub_client.http import hub_get
from the_hub_client.models import (
    CountryCode,
    JobOpenings,
    JobOpportunity,
    JobRoles,
    JobsAndPages,
)

HUB_BASE_URL = "https://thehub.io"
JOB_LISTINGS_ENDPOINT_ROUTE = "/api/v2/jobs"
SINGLE_JOB_ENDPOINT_ROUTE = "/api/jobs/single/"


def get_number_of_jobs_and_pages_by_country(country: CountryCode) -> JobsAndPages:
    response = hub_get(
        f"{HUB_BASE_URL}{JOB_LISTINGS_ENDPOINT_ROUTE}?countryCode={country.value}"
    )
    jobs_listing_response = response.json()

    return JobsAndPages(
        total_jobs=jobs_listing_response.get("total", 0),
        number_of_pages=jobs_listing_response.get("pages", 0),
        jobs_per_page=jobs_listing_response.get("limit", 0),
    )


def get_full_jobs_picture_by_country(country: CountryCode) -> JobOpenings:
    response = hub_get(
        f"{HUB_BASE_URL}{JOB_LISTINGS_ENDPOINT_ROUTE}?countryCode={country.value}"
    )
    jobs_listing_response = response.json()
    job_roles = jobs_listing_response.get("suggestions", {}).get("jobRoles", {})

    return JobOpenings(
        total_jobs=jobs_listing_response.get("total", 0),
        number_of_pages=jobs_listing_response.get("pages", 0),
        jobs_per_page=jobs_listing_response.get("limit", 0),
        remote_jobs=jobs_listing_response.get("suggestions", {}).get("remote", 0),
        paid_jobs=jobs_listing_response.get("suggestions", {}).get("paid", 0),
        unpaid_jobs=jobs_listing_response.get("total", 0)
        - jobs_listing_response.get("suggestions", {}).get("paid", 0),
        jobs_per_role=JobRoles(
            cxo=job_roles.get("cxo", 0),
            human_resources=job_roles.get("humanresources", 0),
            finance=job_roles.get("finance", 0),
            legal=job_roles.get("legal", 0),
            marketing=job_roles.get("marketing", 0),
            sales=job_roles.get("sales", 0),
            customer_service=job_roles.get("customerservice", 0),
            customer_success=job_roles.get("customersuccess", 0),
            analyst=job_roles.get("analyst", 0),
            business_development=job_roles.get("busines_development", 0),
            operations=job_roles.get("operations", 0),
            product_management=job_roles.get("productmanagement", 0),
            project_management=job_roles.get("projectmanagement", 0),
            design=job_roles.get("design", 0),
            ux_ui_designer=job_roles.get("uxuidesigner", 0),
            engineer=job_roles.get("engineer", 0),
            full_stack_developer=job_roles.get("fullstackdeveloper", 0),
            frontend_developer=job_roles.get("frontenddeveloper", 0),
            backend_developer=job_roles.get("backenddeveloper", 0),
            mobile_development=job_roles.get("mobiledevelopment", 0),
            quality_assurance=job_roles.get("qualityassurance", 0),
            devops=job_roles.get("devops", 0),
            data_science=job_roles.get("datascience", 0),
            other=job_roles.get("other", 0),
        ),
    )


def get_job_ids_per_page_per_country(page: int, country: CountryCode) -> list[str]:
    response = hub_get(
        f"{HUB_BASE_URL}{JOB_LISTINGS_ENDPOINT_ROUTE}?page={page}&countryCode={country.value}"
    )
    jobs_listing_response = response.json()
    jobs_list = jobs_listing_response.get("docs", [])
    job_ids = [job.get("id", "") for job in jobs_list]

    return job_ids


def scrape_job_offer_by_id(job_id: str) -> JobOpportunity:
    response = hub_get(f"{HUB_BASE_URL}{SINGLE_JOB_ENDPOINT_ROUTE}/{job_id}")
    single_job_response = response.json()
    job_salary_type = single_job_response.get("salary", "")

    salary = "N/A"

    if job_salary_type == "range":
        salary_range = single_job_response.get("salaryRange", "N/A")
        salary = (
            f"Ranging from {salary_range.get('min', None)} "
            f"to {salary_range.get('max', None)}"
        )

    return JobOpportunity(
        job_id=job_id,
        job_title=single_job_response.get("title", ""),
        job_role=single_job_response.get("jobRole", "N/A"),
        company=single_job_response.get("company", {}).get("name", ""),
        company_description=md(
            single_job_response.get("company", {}).get("whatWeDo", "")
        ),
        job_description=md(single_job_response.get("description", "")),
        country=single_job_response.get("location", {}).get("country", "N/A"),
        locality=single_job_response.get("location", {}).get("locality", "N/A"),
        remote=single_job_response.get("isRemote", False),
        salary_type=job_salary_type,
        salary=salary,
        equity=single_job_response.get("equity", "N/A"),
    )


def get_all_job_ids_per_country(
    country: CountryCode, pages_in_country: int, total_jobs_in_country: int
) -> list[str]:
    all_job_ids_in_country: list[str] = list()

    for page in range(1, pages_in_country + 1):
        print(
            f"Scraping page {page} out of {pages_in_country} for jobs in {country.name}"
        )
        job_ids_in_page = get_job_ids_per_page_per_country(page=page, country=country)
        print(
            f"So far we have found {len(all_job_ids_in_country)} job ids "
            f"out of {total_jobs_in_country}"
        )
        print(f"Page {page} has {len(job_ids_in_page)} job ids")
        for job_id in job_ids_in_page:
            all_job_ids_in_country.append(job_id)

    if len(all_job_ids_in_country) != total_jobs_in_country:
        print(f"We couldn't get all job ID's in {country.name}")

    return all_job_ids_in_country


def get_all_live_job_ids() -> set[str]:
    """Collect unique job IDs currently listed on The Hub (listing API only)."""
    live_job_ids: set[str] = set()

    for country in CountryCode:
        country_overall = get_number_of_jobs_and_pages_by_country(country)
        country_job_ids = get_all_job_ids_per_country(
            country=country,
            pages_in_country=country_overall.number_of_pages,
            total_jobs_in_country=country_overall.total_jobs,
        )
        live_job_ids.update(country_job_ids)

    return live_job_ids
