from typing import Any, cast

import requests
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from qdrant_client.http.exceptions import UnexpectedResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.schemas import (
    ChatRequest,
    ChatResponse,
    ChatSource,
    JobSearchHit,
    JobSearchResponse,
)
from db import get_qdrant_client, get_settings, query_jobs_in_qdrant
from db.query_filters import resolve_chat_filters
from llm_client import NO_MATCHING_JOBS_MESSAGE, get_generator, get_llm_settings
from llm_client.base import Generator
from llm_client.context import filter_usable_points, format_job_context
from llm_client.exceptions import (
    GenerationConfigurationError,
    GenerationRateLimitError,
    GenerationUnavailableError,
)
from the_hub_client import CountryCode, get_full_jobs_picture_by_country
from the_hub_client.models import JobOpenings

limiter = Limiter(key_func=get_remote_address)


def _chat_rate_limit() -> str:
    return get_settings().chat_rate_limit


def _chat_rate_limit_exceeded_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RateLimitExceeded):
        raise exc
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Too many chat requests. Please wait before trying again.",
        },
    )


def _question_too_long_detail(question: str, max_length: int) -> list[dict[str, Any]]:
    """Pydantic-compatible 422 detail for configurable max question length."""
    return [
        {
            "type": "string_too_long",
            "loc": ["body", "question"],
            "msg": f"String should have at most {max_length} characters",
            "input": question,
            "ctx": {"max_length": max_length},
        }
    ]


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="Hubster API",
        description="JSON API for job stats and semantic search over The Hub listings.",
    )
    application.state.limiter = limiter
    application.add_exception_handler(
        RateLimitExceeded, _chat_rate_limit_exceeded_handler
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Accept"],
    )
    return application


app = create_app()

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

# Not guaranteed present until the ALE-81 backfill runs — see ADR-0003.
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
        description=(
            "Optional remote-work filter (true = remote only, false = on-site only)"
        ),
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

    # _payload_to_hit raises HTTPException on its own; kept outside try so it
    # isn't swallowed.
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
@limiter.limit(_chat_rate_limit)
def chat(
    request: Request,
    chat_request: ChatRequest,
    generator: Generator = Depends(get_chat_generator),
) -> ChatResponse:
    try:
        settings = get_settings()
        if len(chat_request.question) > settings.chat_question_max_length:
            raise HTTPException(
                status_code=422,
                detail=_question_too_long_detail(
                    chat_request.question,
                    settings.chat_question_max_length,
                ),
            )
        client = get_qdrant_client()
        filters = resolve_chat_filters(
            chat_request.question,
            explicit_country=chat_request.country,
            explicit_remote=chat_request.remote,
        )
        search_results = query_jobs_in_qdrant(
            db_client=client,
            collection_name=settings.qdrant_collection_name,
            query_text=chat_request.question,
            limit=chat_request.limit,
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
            question=chat_request.question,
            answer=NO_MATCHING_JOBS_MESSAGE,
            sources=[],
            generated=False,
            applied_country=filters.country,
            applied_remote=filters.remote,
        )

    sources = [
        _payload_to_source(point.score, cast(dict[str, Any], point.payload))
        for point in usable_points
    ]
    llm_settings = get_llm_settings()
    context = format_job_context(
        [cast(dict[str, Any], point.payload) for point in usable_points],
        max_chars_per_job=(
            llm_settings.ollama_max_chars_per_job
            if llm_settings.llm_provider == "ollama"
            else None
        ),
    )

    try:
        answer = generator.generate(context=context, question=chat_request.question)
    except GenerationRateLimitError as exc:
        raise HTTPException(
            status_code=429,
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
        question=chat_request.question,
        answer=answer,
        sources=sources,
        generated=True,
        applied_country=filters.country,
        applied_remote=filters.remote,
    )
