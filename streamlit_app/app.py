"""ALE-146: Human-aided eval review UI (Streamlit).

Local-only tool. Bootstrap repo root on sys.path so ``db`` / ``evals`` /
``llm_client`` import the same way as scripts/*.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import streamlit as st

from streamlit_app.embeddings_tab import render_embeddings_tab
from streamlit_app.generation_tab import render_generation_tab
from streamlit_app.judgments import ensure_db
from streamlit_app.review import render_review_tab
from streamlit_app.sweep_tab import render_sweep_tab

st.set_page_config(
    page_title="Hubster eval review",
    layout="wide",
)

ensure_db()

st.title("Hubster eval review")
st.caption(
    "Local human-in-the-loop review + ALE-147 harness tabs. "
    "Read-only against chosen Qdrant collections (except disposable JOBS_COMPARE_*)."
)

with st.sidebar:
    st.markdown("### Notes")
    st.markdown(
        "- Review uses `query_jobs_in_qdrant` + `get_generator` "
        "(not HTTP `/chat`).\n"
        "- Sweep: **Run retrieval** once, then drag the threshold slider "
        "against cached scores.\n"
        "- Judgments: `streamlit_app/data/judgments.db` (gitignored)."
    )

tab_review, tab_embed, tab_gen, tab_sweep = st.tabs(
    ["Review", "Embeddings", "Generation", "Min-score sweep"]
)

with tab_review:
    render_review_tab()
with tab_embed:
    render_embeddings_tab()
with tab_gen:
    render_generation_tab()
with tab_sweep:
    render_sweep_tab()
