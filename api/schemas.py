from pydantic import BaseModel, Field

from the_hub_client.models import CountryCode


class JobSearchHit(BaseModel):
    score: float
    job_id: str
    job_title: str | None = None
    company: str | None = None
    job_role: str
    country: str
    location: str
    remote: bool
    salary_type: str
    salary: str
    equity: str


class JobSearchResponse(BaseModel):
    query: str
    results: list[JobSearchHit] = Field(default_factory=list)


class ChatRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=1,
        description="Natural-language question about jobs",
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum number of jobs to retrieve as context",
    )
    country: CountryCode | None = Field(
        default=None,
        description="Optional country filter (DK, SE, NO, FI, IS, EU)",
    )
    remote: bool | None = Field(
        default=None,
        description=(
            "Optional remote-work filter (true = remote only, false = on-site only)"
        ),
    )


class ChatSource(BaseModel):
    score: float
    job_id: str
    job_role: str
    document_text: str
    job_title: str | None = None
    company: str | None = None
    country: str | None = None
    location: str | None = None


class ChatResponse(BaseModel):
    question: str
    answer: str
    sources: list[ChatSource] = Field(default_factory=list)
    generated: bool = Field(
        description=(
            "True when the answer was produced by the Generator; "
            "False for deterministic fallback."
        )
    )
    applied_country: CountryCode | None = Field(
        default=None,
        description=(
            "Country filter actually applied to retrieval (explicit or derived); "
            "null when none resolved."
        ),
    )
    applied_remote: bool | None = Field(
        default=None,
        description=(
            "Remote filter actually applied to retrieval (explicit or derived); "
            "null when none resolved."
        ),
    )
