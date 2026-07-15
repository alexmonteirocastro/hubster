"""Human review tab: run retrieval + generation, tag, history, replay."""

from __future__ import annotations

from typing import Any, cast

import streamlit as st
from qdrant_client.http.exceptions import UnexpectedResponse

from db import get_qdrant_client, get_settings, query_jobs_in_qdrant
from evals.generation import format_context_for_generator
from llm_client import NO_MATCHING_JOBS_MESSAGE, get_generator
from llm_client.context import filter_chat_retrieval_points, sanitize_answer_links
from llm_client.exceptions import (
    GenerationConfigurationError,
    GenerationRateLimitError,
    GenerationUnavailableError,
)
from streamlit_app.judgments import (
    Judgment,
    Tag,
    ensure_db,
    get_judgment,
    insert_judgment,
    list_judgments,
)
from the_hub_client.models import CountryCode
from the_hub_client.utils import build_job_url

REVIEW_COLLECTIONS = ("JOBS_DEV", "JOBS_ON_THE_HUB")


def _payload_source(score: float, payload: dict[str, Any]) -> dict[str, Any]:
    job_id = str(payload.get("job_url_identifier", ""))
    return {
        "job_id": job_id,
        "score": float(score),
        "job_url": build_job_url(job_id) if job_id else "",
        "job_title": payload.get("job_title"),
        "company": payload.get("company"),
        "document_text": payload.get("document_text", ""),
        "job_role": payload.get("job_role"),
        "country": payload.get("Country"),
        "location": payload.get("location"),
    }


def _compact_sources_for_storage(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "job_id": s.get("job_id"),
            "score": s.get("score"),
            "job_url": s.get("job_url"),
            "job_title": s.get("job_title"),
            "company": s.get("company"),
        }
        for s in sources
    ]


def run_review_query(
    *,
    query: str,
    collection_name: str,
    country: CountryCode | None,
    remote: bool | None,
    limit: int,
) -> dict[str, Any]:
    """Retrieve + generate against an explicit collection (mirrors /chat)."""
    settings = get_settings()
    client = get_qdrant_client()
    search_results = query_jobs_in_qdrant(
        db_client=client,
        collection_name=collection_name,
        query_text=query,
        limit=limit,
        country=country,
        remote=remote,
    )
    usable_points = filter_chat_retrieval_points(
        search_results.points,
        min_score=settings.chat_source_min_score,
    )
    sources = [
        _payload_source(point.score, dict(point.payload or {}))
        for point in usable_points
    ]
    if not usable_points:
        return {
            "answer": NO_MATCHING_JOBS_MESSAGE,
            "sources": sources,
            "generated": False,
        }

    payloads = [dict(point.payload or {}) for point in usable_points]
    generator = get_generator()
    context = format_context_for_generator(payloads, generator)
    answer = generator.generate(context=context, question=query)
    allowed_urls = {str(s["job_url"]) for s in sources if s.get("job_url")}
    answer = sanitize_answer_links(answer, allowed_urls)
    return {
        "answer": answer,
        "sources": sources,
        "generated": True,
    }


def _render_sources(sources: list[dict[str, Any]]) -> None:
    if not sources:
        st.info("No sources above the min-score floor.")
        return
    for src in sources:
        title = src.get("job_title") or src.get("job_role") or src.get("job_id")
        company = src.get("company") or "?"
        score = src.get("score")
        if isinstance(score, float):
            st.markdown(f"**{title}** @ {company} — score `{score:.4f}`")
        else:
            st.markdown(f"**{title}** @ {company}")
        url = src.get("job_url")
        if url:
            st.caption(str(url))
        doc = src.get("document_text")
        if isinstance(doc, str) and doc.strip():
            with st.expander("document_text"):
                st.text(doc)


def _source_id_score_pairs(
    sources: list[dict[str, Any]],
) -> list[tuple[str, float | None]]:
    pairs: list[tuple[str, float | None]] = []
    for s in sources:
        job_id = str(s.get("job_id", ""))
        score_raw = s.get("score")
        score = float(score_raw) if isinstance(score_raw, (int, float)) else None
        pairs.append((job_id, score))
    return pairs


def _diff_sources(
    stored: list[dict[str, Any]],
    current: list[dict[str, Any]],
) -> None:
    stored_pairs = _source_id_score_pairs(stored)
    current_pairs = _source_id_score_pairs(current)
    stored_ids = [p[0] for p in stored_pairs]
    current_ids = [p[0] for p in current_pairs]
    if stored_ids == current_ids:
        st.success("Source job ids match stored judgment.")
    else:
        st.warning(f"Source ids differ.\nStored: {stored_ids}\nCurrent: {current_ids}")
    score_lines: list[str] = []
    stored_by_id = {jid: score for jid, score in stored_pairs}
    for jid, score in current_pairs:
        old = stored_by_id.get(jid)
        if old is not None and score is not None and abs(old - score) > 1e-6:
            score_lines.append(f"{jid}: {old:.4f} → {score:.4f}")
    if score_lines:
        st.write("Score changes:")
        for line in score_lines:
            st.write(f"- {line}")


def render_review_tab() -> None:
    ensure_db()

    st.subheader("Run a review query")
    query = st.text_area("Query", height=80, key="review_query")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        collection_name = st.selectbox(
            "Collection",
            options=list(REVIEW_COLLECTIONS),
            key="review_collection",
        )
    with col_b:
        country_label = st.selectbox(
            "Country (optional)",
            options=["(none)", *[c.value for c in CountryCode]],
            key="review_country",
        )
    with col_c:
        remote_label = st.selectbox(
            "Remote (optional)",
            options=["(none)", "true", "false"],
            key="review_remote",
        )
    limit = st.number_input(
        "Limit",
        min_value=1,
        max_value=50,
        value=5,
        key="review_limit",
    )

    country: CountryCode | None = None
    if country_label != "(none)":
        country = CountryCode(country_label)
    remote: bool | None = None
    if remote_label == "true":
        remote = True
    elif remote_label == "false":
        remote = False

    if st.button("Run query", type="primary", key="review_run"):
        if not query.strip():
            st.error("Query is required.")
        else:
            try:
                with st.spinner("Retrieving and generating..."):
                    result = run_review_query(
                        query=query.strip(),
                        collection_name=collection_name,
                        country=country,
                        remote=remote,
                        limit=int(limit),
                    )
                st.session_state["review_result"] = {
                    **result,
                    "query": query.strip(),
                    "collection_name": collection_name,
                    "country": country.value if country else None,
                    "remote": remote,
                }
            except (UnexpectedResponse, ConnectionError, TimeoutError, OSError) as exc:
                st.error(f"Qdrant error: {exc}")
            except (
                GenerationRateLimitError,
                GenerationConfigurationError,
                GenerationUnavailableError,
            ) as exc:
                st.error(f"Generation error: {exc}")
            except Exception as exc:
                st.error(f"Run failed: {exc}")

    result_state = st.session_state.get("review_result")
    if isinstance(result_state, dict):
        result = cast(dict[str, Any], result_state)
        left, right = st.columns(2)
        with left:
            st.markdown("#### Sources")
            _render_sources(result["sources"])
        with right:
            st.markdown("#### Answer")
            generated = result.get("generated", False)
            st.caption("generated" if generated else "fallback (no matching jobs)")
            st.markdown(result["answer"])

        st.markdown("#### Judgment")
        tag = st.radio(
            "Tag",
            options=["good", "bad", "partial"],
            horizontal=True,
            key="review_tag",
        )
        note = st.text_area("Note (optional)", key="review_note", height=60)
        if st.button("Save judgment", key="review_save"):
            row_id = insert_judgment(
                collection_name=result["collection_name"],
                query=result["query"],
                answer=result["answer"],
                sources=_compact_sources_for_storage(result["sources"]),
                tag=cast(Tag, tag),
                country=result.get("country"),
                remote=result.get("remote"),
                note=note.strip() or None,
            )
            st.success(f"Saved judgment #{row_id}")

    st.divider()
    st.subheader("History")
    filter_tag = st.selectbox(
        "Filter by tag",
        options=["(all)", "good", "bad", "partial"],
        key="history_tag_filter",
    )
    tag_filter: Tag | None = None
    if filter_tag != "(all)":
        tag_filter = cast(Tag, filter_tag)
    history = list_judgments(tag=tag_filter)
    if not history:
        st.caption("No judgments yet.")
        return

    for item in history:
        _render_history_row(item)


def _render_history_row(item: Judgment) -> None:
    header = (
        f"#{item.id} [{item.tag}] {item.created_at[:19]} — "
        f"{item.collection_name} — {item.query[:60]}"
    )
    with st.expander(header):
        st.write(f"Country: `{item.country}` · Remote: `{item.remote}`")
        if item.note:
            st.write(f"Note: {item.note}")
        st.markdown("**Stored answer**")
        st.markdown(item.answer)
        st.markdown("**Stored sources**")
        for s in item.sources:
            st.write(
                f"- `{s.get('job_id')}` score={s.get('score')} "
                f"{s.get('job_title')} @ {s.get('company')}"
            )
        if st.button("Replay", key=f"replay_{item.id}"):
            stored = get_judgment(item.id)
            if stored is None:
                st.error("Judgment disappeared.")
                return
            country = CountryCode(stored.country) if stored.country else None
            try:
                with st.spinner("Replaying..."):
                    current = run_review_query(
                        query=stored.query,
                        collection_name=stored.collection_name,
                        country=country,
                        remote=stored.remote,
                        limit=5,
                    )
            except Exception as exc:
                st.error(f"Replay failed: {exc}")
                return
            st.markdown("**Current answer**")
            st.markdown(current["answer"])
            if current["answer"] == stored.answer:
                st.success("Answer text matches stored judgment.")
            else:
                st.warning("Answer text differs from stored judgment.")
            st.markdown("**Source diff**")
            _diff_sources(stored.sources, current["sources"])
