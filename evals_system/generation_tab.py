"""Generation model comparison tab (ALE-146 / ALE-147)."""

from __future__ import annotations

import streamlit as st

from evals.generation import build_generator, compare_generators
from evals.types import GenerationCaseResult, GenerationComparisonResult

PROVIDER_PRESETS = [
    "stub",
    "gemini",
    "ollama",
    "gemini:gemini-2.0-flash",
    "ollama:qwen3:8b",
]


def _render_case_result(case: GenerationCaseResult) -> None:
    header = f"[{case.case_id}] {case.generator_label} (generated={case.generated})"
    with st.expander(header, expanded=bool(case.error)):
        if case.error:
            st.warning(f"Provider error: {case.error}")
        st.write(f"Query: {case.query!r}")
        st.write(
            f"Sources: {case.source_job_ids} (expected {case.expected_source_job_ids})"
        )
        if case.missing_expected_source_ids:
            st.warning(f"Missing expected: {case.missing_expected_source_ids}")
        if case.ungrounded_urls:
            st.warning(f"Ungrounded URLs: {case.ungrounded_urls}")
        if case.ungrounded_phrases:
            st.warning(f"Ungrounded phrases: {case.ungrounded_phrases}")
        if case.answer:
            st.markdown("**Answer**")
            st.markdown(case.answer)
        elif not case.error:
            st.info("Empty answer (no provider error recorded).")


def _render_generation_result(result: GenerationComparisonResult) -> None:
    st.caption(
        f"Collection: `{result.collection_name}` · "
        f"Generators: {', '.join(result.generator_labels)}"
    )
    for case in result.results:
        _render_case_result(case)


def render_generation_tab() -> None:
    st.subheader("Compare generators")
    st.caption(
        "Seeds disposable JOBS_COMPARE_GENERATION. Explicit Run only. "
        "Per-provider failures show as warning badges via GenerationCaseResult.error."
    )
    providers = st.multiselect(
        "Providers",
        options=PROVIDER_PRESETS,
        default=["stub"],
        key="gen_providers",
    )
    col_a, col_b = st.columns(2)
    with col_a:
        top_k = st.number_input(
            "Top-k",
            min_value=1,
            max_value=50,
            value=5,
            key="gen_topk",
        )
    with col_b:
        min_score_raw = st.text_input(
            "Min score override (empty = settings default)",
            value="",
            key="gen_minscore",
        )
    keep = st.checkbox("Keep generation collection after run", key="gen_keep")

    if st.button("Run generation comparison", type="primary", key="gen_run"):
        if not providers:
            st.error("Select at least one provider.")
            return
        min_score: float | None = None
        if min_score_raw.strip():
            try:
                min_score = float(min_score_raw.strip())
            except ValueError:
                st.error("Min score must be a float.")
                return
        try:
            with st.spinner("Comparing generators..."):
                generators = {label: build_generator(label) for label in providers}
                result = compare_generators(
                    generators,
                    keep_collection=keep,
                    top_k=int(top_k),
                    min_score=min_score,
                )
            st.session_state["gen_result"] = result
        except Exception as exc:
            st.error(f"Comparison failed: {exc}")
            return

    cached = st.session_state.get("gen_result")
    if isinstance(cached, GenerationComparisonResult):
        _render_generation_result(cached)
