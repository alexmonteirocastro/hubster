import requests
from fastapi import FastAPI, HTTPException, Query
from qdrant_client.http.exceptions import UnexpectedResponse

from api.schemas import JobSearchHit, JobSearchResponse
from db import get_qdrant_client, get_settings, query_jobs_in_qdrant
from the_hub_client import CountryCode, get_full_jobs_picture_by_country
from the_hub_client.models import JobOpenings

app = FastAPI(
    title="Hubster API",
    description="JSON API for job stats and semantic search over The Hub listings.",
)


def _payload_to_hit(score: float, payload: dict) -> JobSearchHit:
    return JobSearchHit(
        score=score,
        job_id=payload["job_url_identifier"],
        job_role=payload["job_role"],
        country=payload["Country"],
        location=payload["location"],
        remote=payload["Remote"],
        salary_type=payload["Salary Type"],
        salary=payload["Salary"],
        equity=payload["Equity"],
    )


@app.get("/jobs/stats", response_model=JobOpenings)
def jobs_stats(country: CountryCode) -> JobOpenings:
    try:
        return get_full_jobs_picture_by_country(country)
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail="The Hub API is unavailable.",
        ) from exc


@app.get("/jobs/search", response_model=JobSearchResponse)
def jobs_search(
    q: str = Query(..., min_length=1, description="Natural-language search query"),
    limit: int = Query(5, ge=1, le=50, description="Maximum number of results"),
) -> JobSearchResponse:
    settings = get_settings()

    try:
        client = get_qdrant_client()
        search_results = query_jobs_in_qdrant(
            db_client=client,
            collection_name=settings.qdrant_collection_name,
            query_text=q,
            limit=limit,
        )
    except (UnexpectedResponse, ConnectionError, TimeoutError, OSError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Qdrant is unavailable.",
        ) from exc

    hits = [
        _payload_to_hit(hit.score, hit.payload)
        for hit in search_results.points
        if hit.payload is not None
    ]
    return JobSearchResponse(query=q, results=hits)
