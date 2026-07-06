from pydantic import BaseModel, Field


class JobSearchHit(BaseModel):
    score: float
    job_id: str
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
    question: str = Field(..., min_length=1, description="Natural-language question about jobs")
    limit: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Maximum number of jobs to retrieve as context",
    )


class ChatSource(BaseModel):
    score: float
    job_id: str
    job_role: str
    document_text: str
    country: str | None = None
    location: str | None = None


class ChatResponse(BaseModel):
    question: str
    answer: str
    sources: list[ChatSource] = Field(default_factory=list)
    generated: bool = Field(
        description="True when the answer was produced by the Generator; False for deterministic fallback."
    )
