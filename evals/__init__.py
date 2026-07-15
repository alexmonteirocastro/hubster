"""Importable comparison / sweep harness for embedding, generation, and hyperparameters.

ALE-147. CLIs under ``scripts/`` and the future Streamlit UI (ALE-146) should
call these functions rather than re-implementing sweep logic.
"""

from evals.embeddings import compare_embedding_models, summarize_query_results
from evals.generation import build_generator, compare_generators
from evals.hyperparameters import (
    evaluate_threshold,
    sweep_chat_source_min_score,
    sweep_from_case_scores,
)
from evals.types import (
    EmbeddingComparisonResult,
    GenerationCaseResult,
    GenerationComparisonResult,
    MinScoreSweepResult,
    MinScoreSweepRow,
    ModelSummary,
    QueryResult,
)

__all__ = [
    "EmbeddingComparisonResult",
    "GenerationCaseResult",
    "GenerationComparisonResult",
    "MinScoreSweepResult",
    "MinScoreSweepRow",
    "ModelSummary",
    "QueryResult",
    "build_generator",
    "compare_embedding_models",
    "compare_generators",
    "evaluate_threshold",
    "summarize_query_results",
    "sweep_chat_source_min_score",
    "sweep_from_case_scores",
]
