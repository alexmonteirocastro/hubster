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
