from enum import Enum

from pydantic import BaseModel


class CountryCode(str, Enum):
    DENMARK = "DK"
    SWEDEN = "SE"
    NORWAY = "NO"
    FINLAND = "FI"
    ICELAND = "IS"
    EUROPE = "EU"


# Maps CountryCode values to the exact country name strings returned by The Hub API
# in `location.country` on each job (see scrape_job_offer_by_id).
COUNTRY_CODE_TO_HUB_COUNTRY_NAME: dict[CountryCode, str] = {
    CountryCode.DENMARK: "Denmark",
    CountryCode.SWEDEN: "Sweden",
    CountryCode.NORWAY: "Norway",
    CountryCode.FINLAND: "Finland",
    CountryCode.ICELAND: "Iceland",
    # EU is a Hub listing meta-code (countryCode=EU), not a per-job location.country
    # value — verify against a live Hub payload before relying on this filter.
    # TODO: confirm whether any job's location.country is literally "Europe".
    CountryCode.EUROPE: "Europe",
}


def country_code_to_hub_country_name(country: CountryCode) -> str:
    return COUNTRY_CODE_TO_HUB_COUNTRY_NAME[country]


class JobsAndPages(BaseModel):
    total_jobs: int
    number_of_pages: int
    jobs_per_page: int


class JobRoles(BaseModel):
    cxo: int
    human_resources: int
    finance: int
    legal: int
    marketing: int
    sales: int
    customer_service: int
    customer_success: int
    analyst: int
    business_development: int
    operations: int
    product_management: int
    project_management: int
    design: int
    ux_ui_designer: int
    engineer: int
    full_stack_developer: int
    frontend_developer: int
    backend_developer: int
    mobile_development: int
    quality_assurance: int
    devops: int
    data_science: int
    other: int


class JobOpenings(JobsAndPages):
    jobs_per_role: JobRoles
    remote_jobs: int
    paid_jobs: int
    unpaid_jobs: int


class JobOpportunity(BaseModel):
    job_id: str
    job_title: str
    company: str
    job_role: str
    company_description: str
    job_description: str
    country: str
    locality: str
    remote: bool
    salary_type: str
    salary: str
    equity: str
