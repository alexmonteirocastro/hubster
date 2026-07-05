import requests
from fastapi import FastAPI, HTTPException, Query
from pydantic import ValidationError
from qdrant_client.http.exceptions import UnexpectedResponse

from api.schemas import JobSearchHit, JobSearchResponse
from db import get_qdrant_client, get_settings, query_jobs_in_qdrant
from the_hub_client import CountryCode, get_full_jobs_picture_by_country
from the_hub_client.models import JobOpenings

app = FastAPI(
    title="Hubster API",
    description="JSON API for job stats and semantic search over The Hub listings.",
)

_PAYLOAD_FIELDS = {
    "job_id": "job_url_identifier",
    "job_role": "job_role",
    "country": "Country",
    "location": "location",
    "remote": "Remote",
    "salary_type": "Salary Type",
    "salary": "Salary",
    "equity": "Equity",
}


def _payload_to_hit(score: float, payload: dict) -> JobSearchHit:
    try:
        return JobSearchHit(
            score=score,
            **{field: payload[payload_key] for field, payload_key in _PAYLOAD_FIELDS.items()},
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=502,
            detail="Search result payload is missing required fields.",
        ) from exc


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
    try:
        settings = get_settings()
        client = get_qdrant_client()
        search_results = query_jobs_in_qdrant(
            db_client=client,
            collection_name=settings.qdrant_collection_name,
            query_text=q,
            limit=limit,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=500,
            detail="Server configuration is invalid.",
        ) from exc
    except (UnexpectedResponse, ConnectionError, TimeoutError, OSError) as exc:
        raise HTTPException(
            status_code=503,
            detail="Qdrant is unavailable.",
        ) from exc

    # _payload_to_hit raises HTTPException on its own; kept outside try so it isn't swallowed.
    hits = []
    for hit in search_results.points:
        if hit.payload is None:
            continue
        hits.append(_payload_to_hit(hit.score, hit.payload))
    return JobSearchResponse(query=q, results=hits)
