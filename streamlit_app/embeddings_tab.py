"""Embedding model comparison tab (ALE-146 / ALE-147)."""

from __future__ import annotations

import streamlit as st

from evals.embeddings import DEFAULT_MODELS, compare_embedding_models
from evals.types import EmbeddingComparisonResult, QueryResult


def _render_embedding_result(result: EmbeddingComparisonResult) -> None:
    st.markdown("#### Summaries")
    rows = []
    for model in result.models:
        summary = result.summaries[model]
        rows.append(
            {
                "model": model,
                "missed_count": summary.missed_count,
                "min_expected_score": summary.min_expected_score,
                "max_noise_score": summary.max_noise_score,
                "separation_margin": summary.separation_margin,
                "collection": result.collection_names.get(model, ""),
            }
        )
    st.dataframe(rows, use_container_width=True)

    st.markdown("#### Per-query results")
    for model in result.models:
        with st.expander(f"Queries — {model}"):
            for qr in result.results_by_model[model]:
                _render_query_result(qr)


def _render_query_result(qr: QueryResult) -> None:
    st.markdown(f"**[{qr.query_id}]** {qr.query_text}")
    st.write(f"Expected: {qr.expected_job_ids}")
    if qr.all_missing:
        st.warning(f"Missing expected ids: {qr.all_missing}")
    st.write(f"Expected scores: {qr.expected_scores}")
    st.write(f"Top noise score: {qr.top_noise_score}")


def render_embeddings_tab() -> None:
    st.subheader("Compare embedding models")
    st.caption(
        "Seeds disposable JOBS_COMPARE_* collections. Explicit Run only — "
        "changing the model list does not auto-rerun."
    )
    models = st.multiselect(
        "Models (≥2)",
        options=list(DEFAULT_MODELS)
        + [
            "BAAI/bge-small-en-v1.5",
            "sentence-transformers/all-MiniLM-L6-v2",
        ],
        default=list(DEFAULT_MODELS),
        key="embed_models",
    )
    keep = st.checkbox("Keep comparison collections after run", key="embed_keep")

    if st.button("Run embedding comparison", type="primary", key="embed_run"):
        if len(models) < 2:
            st.error("Select at least two models.")
            return
        status = st.empty()
        try:
            with st.spinner("Comparing embedding models..."):
                result = compare_embedding_models(
                    list(models),
                    keep_collections=keep,
                    progress=lambda msg: status.write(msg),
                )
            status.empty()
            st.session_state["embed_result"] = result
        except Exception as exc:
            status.empty()
            st.error(f"Comparison failed: {exc}")
            return

    cached = st.session_state.get("embed_result")
    if isinstance(cached, EmbeddingComparisonResult):
        _render_embedding_result(cached)
