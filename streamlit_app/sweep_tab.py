"""CHAT_SOURCE_MIN_SCORE sweep tab — seed/collect once, slider free (ALE-146)."""

from __future__ import annotations

import streamlit as st

from db import get_settings
from evals.collections import (
    MIN_SCORE_SWEEP_COLLECTION,
    delete_collections,
    get_comparison_client,
    seed_collection_for_model,
    validate_qdrant_config,
)
from evals.fixtures import load_golden_queries
from evals.hyperparameters import (
    DEFAULT_THRESHOLDS,
    collect_sweep_case_scores,
    evaluate_threshold,
    sweep_from_case_scores,
)
from evals.types import MinScoreSweepResult, SweepCaseScores


def _run_retrieval() -> list[SweepCaseScores]:
    """Seed once and collect hit scores — do not call sweep_chat_source_min_score."""
    validate_qdrant_config()
    settings = get_settings()
    model = settings.embedding_model
    collection_name = MIN_SCORE_SWEEP_COLLECTION
    client = get_comparison_client()
    golden_set = load_golden_queries()

    if client.collection_exists(collection_name):
        client.delete_collection(collection_name)
    seed_collection_for_model(client, collection_name, model)
    cases = collect_sweep_case_scores(client, collection_name, model, golden_set)

    st.session_state["sweep_cases"] = cases
    st.session_state["sweep_collection"] = collection_name
    return cases


def _render_sweep_table(result: MinScoreSweepResult) -> None:
    rows = [
        {
            "threshold": row.threshold,
            "expected_survivors": row.expected_survivors,
            "expected_total": row.expected_total,
            "missed_expected": row.missed_expected,
            "confuser_survivors": row.confuser_survivors,
            "confuser_total": row.confuser_total,
        }
        for row in result.rows
    ]
    st.dataframe(rows, use_container_width=True)
    suggested = result.suggested_max_safe_threshold
    if suggested is None:
        st.warning("No safe threshold found (every candidate misses expected hits).")
    else:
        st.success(f"Suggested max safe threshold: `{suggested}`")


def render_sweep_tab() -> None:
    st.subheader("Min-score sweep")
    st.caption(
        "Run retrieval once (seeds JOBS_COMPARE_MIN_SCORE_SWEEP + caches scores). "
        "The threshold slider then evaluates in-memory only — no Qdrant reseed."
    )

    if st.button("Run retrieval", type="primary", key="sweep_run"):
        try:
            with st.spinner("Seeding collection and collecting scores..."):
                seeded = _run_retrieval()
            st.success(f"Cached scores for {len(seeded)} cases.")
        except Exception as exc:
            st.error(f"Retrieval failed: {exc}")
            return

    cached = st.session_state.get("sweep_cases")
    if not isinstance(cached, list) or not cached:
        st.info("Click Run retrieval to seed scores before adjusting the threshold.")
        return
    cases: list[SweepCaseScores] = cached

    st.markdown("#### Live threshold")
    threshold = st.slider(
        "CHAT_SOURCE_MIN_SCORE",
        min_value=0.70,
        max_value=0.95,
        value=0.85,
        step=0.01,
        key="sweep_threshold",
    )
    live = evaluate_threshold(cases, float(threshold))
    st.write(
        f"Expected survivors: **{live.expected_survivors}/{live.expected_total}** "
        f"(missed {live.missed_expected}) · "
        f"Confuser survivors: **{live.confuser_survivors}/{live.confuser_total}**"
    )

    st.markdown("#### Full grid (cached)")
    grid = sweep_from_case_scores(
        cases,
        DEFAULT_THRESHOLDS,
        collection_name=st.session_state.get("sweep_collection", ""),
    )
    _render_sweep_table(grid)

    if st.button("Delete disposable sweep collection", key="sweep_cleanup"):
        collection = st.session_state.get("sweep_collection")
        if not collection:
            st.warning("No collection name in session.")
            return
        try:
            client = get_comparison_client()
            delete_collections(client, [collection])
            st.success(f"Deleted `{collection}`.")
        except Exception as exc:
            st.error(f"Cleanup failed: {exc}")
