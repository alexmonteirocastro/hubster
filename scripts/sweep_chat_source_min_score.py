"""ALE-147: Sweep CHAT_SOURCE_MIN_SCORE against the golden retrieval set.

Thin CLI over ``evals.hyperparameters.sweep_chat_source_min_score``. Uses
``queries`` and ``role_confusion_cases`` only (not tech_stack_adversarial_cases).
See scripts/README.md.

Usage:

    uv run python scripts/sweep_chat_source_min_score.py
    uv run python scripts/sweep_chat_source_min_score.py \\
        --thresholds 0.80 0.85 0.90
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.hyperparameters import (  # noqa: E402
    DEFAULT_THRESHOLDS,
    sweep_chat_source_min_score,
)
from evals.types import MinScoreSweepResult  # noqa: E402


def _print_results(result: MinScoreSweepResult) -> None:
    print("\n" + "=" * 100)
    print("CHAT_SOURCE_MIN_SCORE SWEEP")
    print("=" * 100)
    print(f"Collection: {result.collection_name}")
    print(f"{'threshold':>10}  {'exp_ok':>10}  {'exp_miss':>8}  {'conf_ok':>10}")
    for row in result.rows:
        print(
            f"{row.threshold:10.3f}  "
            f"{row.expected_survivors:4d}/{row.expected_total:<4d}  "
            f"{row.missed_expected:8d}  "
            f"{row.confuser_survivors:4d}/{row.confuser_total:<4d}"
        )
    suggested = result.suggested_max_safe_threshold
    if suggested is not None:
        print(f"\nSuggested max safe floor (all expected hits survive): {suggested}")
    else:
        print(
            "\nNo threshold retained every expected hit — "
            "lower the floor or inspect retrieval first."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--thresholds",
        nargs="+",
        type=float,
        default=DEFAULT_THRESHOLDS,
        metavar="T",
        help=f"Candidate floors. Default: {DEFAULT_THRESHOLDS}",
    )
    parser.add_argument(
        "--keep-collection",
        action="store_true",
        help="Keep disposable sweep collection after running (default: delete).",
    )
    args = parser.parse_args()

    try:
        result = sweep_chat_source_min_score(
            args.thresholds,
            keep_collection=args.keep_collection,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    _print_results(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
