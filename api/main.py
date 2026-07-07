import requests
from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import ValidationError
from qdrant_client.http.exceptions import UnexpectedResponse

from api.schemas import ChatRequest, ChatResponse, ChatSource, JobSearchHit, JobSearchResponse
from db import get_qdrant_client, get_settings, query_jobs_in_qdrant
from db.query_filters import resolve_chat_filters
from llm_client import NO_MATCHING_JOBS_MESSAGE, get_generator
from llm_client.base import Generator
from llm_client.context import filter_usable_points, format_job_context
from llm_client.exceptions import (
    GenerationConfigurationError,
    GenerationRateLimitError,
    GenerationUnavailableError,
)
from the_hub_client import CountryCode, get_full_jobs_picture_by_country
from the_hub_client.models import JobOpenings

app = FastAPI(
    title="Hubster API",
    description="JSON API for job stats and semantic search over The Hub listings.",
)

_REQUIRED_HIT_PAYLOAD_FIELDS = {
    "job_id": "job_url_identifier",
    "job_role": "job_role",
    "country": "Country",
    "location": "location",
    "remote": "Remote",
    "salary_type": "Salary Type",
    "salary": "Salary",
    "equity": "Equity",
}

_OPTIONAL_HIT_PAYLOAD_FIELDS = {
    "job_title": "job_title",
    "company": "company",
}


def _payload_to_hit(score: float, payload: dict) -> JobSearchHit:
    try:
        fields = {
            field: payload[payload_key]
            for field, payload_key in _REQUIRED_HIT_PAYLOAD_FIELDS.items()
        }
        for field, payload_key in _OPTIONAL_HIT_PAYLOAD_FIELDS.items():
            fields[field] = payload.get(payload_key)
        return JobSearchHit(score=score, **fields)
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
    country: CountryCode | None = Query(
        default=None,
        description="Optional country filter (DK, SE, NO, FI, IS, EU)",
    ),
    remote: bool | None = Query(
        default=None,
        description="Optional remote-work filter (true = remote only, false = on-site only)",
    ),
) -> JobSearchResponse:
    try:
        settings = get_settings()
        client = get_qdrant_client()
        search_results = query_jobs_in_qdrant(
            db_client=client,
            collection_name=settings.qdrant_collection_name,
            query_text=q,
            limit=limit,
            country=country,
            remote=remote,
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


def get_chat_generator() -> Generator:
    return get_generator()


def _payload_to_source(score: float, payload: dict) -> ChatSource:
    try:
        return ChatSource(
            score=score,
            job_id=payload["job_url_identifier"],
            job_role=payload["job_role"],
            document_text=payload.get("document_text", ""),
            job_title=payload.get("job_title"),
            company=payload.get("company"),
            country=payload.get("Country"),
            location=payload.get("location"),
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=502,
            detail="Search result payload is missing required fields.",
        ) from exc


@app.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    generator: Generator = Depends(get_chat_generator),
) -> ChatResponse:
    try:
        settings = get_settings()
        client = get_qdrant_client()
        filters = resolve_chat_filters(
            request.question,
            explicit_country=request.country,
            explicit_remote=request.remote,
        )
        search_results = query_jobs_in_qdrant(
            db_client=client,
            collection_name=settings.qdrant_collection_name,
            query_text=request.question,
            limit=request.limit,
            country=filters.country,
            remote=filters.remote,
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

    usable_points = filter_usable_points(search_results.points)

    if not usable_points:
        return ChatResponse(
            question=request.question,
            answer=NO_MATCHING_JOBS_MESSAGE,
            sources=[],
            generated=False,
        )

    sources = [_payload_to_source(point.score, point.payload) for point in usable_points]
    context = format_job_context([point.payload for point in usable_points])

    try:
        answer = generator.generate(context=context, question=request.question)
    except GenerationRateLimitError as exc:
        raise HTTPException(
            status_code=503,
            detail="The generation service is rate-limited. Please try again shortly.",
        ) from exc
    except GenerationConfigurationError as exc:
        raise HTTPException(
            status_code=500,
            detail="Generation service configuration is invalid.",
        ) from exc
    except GenerationUnavailableError as exc:
        raise HTTPException(
            status_code=502,
            detail="The generation service is unavailable.",
        ) from exc

    return ChatResponse(
        question=request.question,
        answer=answer,
        sources=sources,
        generated=True,
    )
