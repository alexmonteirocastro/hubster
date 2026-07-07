from enum import Enum

from pydantic import BaseModel


class CountryCode(str, Enum):
    DENMARK = "DK"
    SWEDEN = "SE"
    NORWAY = "NO"
    FINLAND = "FI"
    ICELAND = "IS"
    EUROPE = "EU"


# Maps API country codes to the exact `Country` strings stored in Qdrant payloads
# (sourced from The Hub's `location.country` field on each job).
COUNTRY_CODE_TO_PAYLOAD_COUNTRY: dict[CountryCode, str] = {
    CountryCode.DENMARK: "Denmark",
    CountryCode.SWEDEN: "Sweden",
    CountryCode.NORWAY: "Norway",
    CountryCode.FINLAND: "Finland",
    CountryCode.ICELAND: "Iceland",
    # EU is a Hub listing meta-code; individual job payloads use nation names above.
    CountryCode.EUROPE: "Europe",
}


def country_code_to_payload_country(country: CountryCode) -> str:
    return COUNTRY_CODE_TO_PAYLOAD_COUNTRY[country]


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
