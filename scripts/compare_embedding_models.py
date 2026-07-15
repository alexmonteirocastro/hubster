"""ALE-138 / ALE-147: Compare candidate embedding models against the golden set.

Thin CLI over ``evals.embeddings.compare_embedding_models``. Seeds disposable
``JOBS_COMPARE_*`` collections — safe against production. See scripts/README.md.

Usage:

    uv run python scripts/compare_embedding_models.py
    uv run python scripts/compare_embedding_models.py --keep-collections
    uv run python scripts/compare_embedding_models.py \\
        --models BAAI/bge-small-en-v1.5 intfloat/multilingual-e5-small
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.embeddings import DEFAULT_MODELS, compare_embedding_models  # noqa: E402
from evals.types import EmbeddingComparisonResult, QueryResult  # noqa: E402


def _print_comparison_table(result: EmbeddingComparisonResult) -> None:
    if len(result.models) < 2:
        return
    model_a, model_b = result.models[0], result.models[1]
    results_a = result.results_by_model[model_a]
    results_b = result.results_by_model[model_b]

    print("\n" + "=" * 100)
    print(f"COMPARISON: {model_a}  vs  {model_b}")
    print("=" * 100)

    by_id_b = {r.query_id: r for r in results_b}

    for r_a in results_a:
        r_b = by_id_b.get(r_a.query_id)
        print(f"\n--- Query [{r_a.query_id}]: {r_a.query_text!r} ---")
        print(f"Expected job(s): {r_a.expected_job_ids}")

        for job_id in r_a.expected_job_ids:
            score_a = r_a.expected_scores.get(job_id)
            score_b = r_b.expected_scores.get(job_id) if r_b else None
            print(
                f"  job={job_id:<20} "
                f"{model_a}={score_a if score_a is not None else 'MISSING':<10} "
                f"{model_b}={score_b if score_b is not None else 'MISSING'}"
            )

        noise_a = r_a.top_noise_score
        noise_b = r_b.top_noise_score if r_b else None
        print(f"  top noise score:  {model_a}={noise_a}   {model_b}={noise_b}")

        if r_a.all_missing:
            print(f"  ⚠️  {model_a} MISSED: {r_a.all_missing}")
        if r_b and r_b.all_missing:
            print(f"  ⚠️  {model_b} MISSED: {r_b.all_missing}")

    # Extra models beyond the first pair (still print their summaries below).
    if len(result.models) > 2:
        for model in result.models[2:]:
            _print_single_model_results(model, result.results_by_model[model])

    print("\n" + "=" * 100)
    print("SUMMARY")
    print("=" * 100)
    for model in result.models:
        summary = result.summaries[model]
        print(f"\n{model}:")
        print(f"  Missed expected hits: {summary.missed_count}")
        print(
            f"  Min expected-hit score (CHAT_SOURCE_MIN_SCORE floor): "
            f"{summary.min_expected_score}"
        )
        print(
            f"  Max noise-hit score (should sit below the floor above): "
            f"{summary.max_noise_score}"
        )
        if summary.separation_margin is not None:
            verdict = (
                "✅ clean separation"
                if summary.separation_margin > 0
                else "⚠️  OVERLAP — recalibration will be lossy"
            )
            print(f"  Separation margin: {summary.separation_margin:.4f} {verdict}")


def _print_single_model_results(model: str, results: list[QueryResult]) -> None:
    print(f"\n--- Additional model: {model} ---")
    for result in results:
        print(f"  [{result.query_id}] missing={result.all_missing or 'none'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        nargs="+",
        default=DEFAULT_MODELS,
        metavar="MODEL",
        help=f"Embedding models to compare (2+). Default: {DEFAULT_MODELS}",
    )
    parser.add_argument(
        "--keep-collections",
        action="store_true",
        help="Keep comparison collections after running (default: delete).",
    )
    args = parser.parse_args()

    if len(args.models) < 2:
        print("Error: provide at least two --models", file=sys.stderr)
        return 1

    try:
        result = compare_embedding_models(
            args.models,
            keep_collections=args.keep_collections,
            progress=print,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    _print_comparison_table(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
