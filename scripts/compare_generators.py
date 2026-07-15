"""ALE-147: Compare generation models against golden_generation.json.

Thin CLI over ``evals.generation.compare_generators``. Seeds a disposable
``JOBS_COMPARE_GENERATION`` collection. See scripts/README.md.

``mock_answer_substring`` in the fixture is for pytest ScriptedGenerator only
and is not checked against live Gemini/Ollama output.

Usage:

    uv run python scripts/compare_generators.py --providers stub
    uv run python scripts/compare_generators.py --providers gemini ollama:qwen3:8b
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from evals.generation import build_generator, compare_generators  # noqa: E402
from evals.types import GenerationComparisonResult  # noqa: E402


def _print_results(result: GenerationComparisonResult) -> None:
    print("\n" + "=" * 100)
    print("GENERATION COMPARISON")
    print("=" * 100)
    print(f"Collection: {result.collection_name}")
    print(f"Generators: {', '.join(result.generator_labels)}")

    for case_result in result.results:
        print(
            f"\n--- [{case_result.case_id}] {case_result.generator_label} "
            f"(generated={case_result.generated}) ---"
        )
        print(f"  query: {case_result.query!r}")
        print(
            f"  sources: {case_result.source_job_ids} "
            f"(expected {case_result.expected_source_job_ids})"
        )
        if case_result.missing_expected_source_ids:
            print(
                f"  ⚠️  missing expected sources: "
                f"{case_result.missing_expected_source_ids}"
            )
        if case_result.ungrounded_urls:
            print(f"  ⚠️  ungrounded urls: {case_result.ungrounded_urls}")
        if case_result.ungrounded_phrases:
            print(f"  ⚠️  ungrounded phrases: {case_result.ungrounded_phrases}")
        preview = case_result.answer.replace("\n", " ")[:200]
        print(f"  answer: {preview}{'…' if len(case_result.answer) > 200 else ''}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--providers",
        nargs="+",
        required=True,
        metavar="LABEL",
        help=("Generator labels: gemini, gemini:<model>, ollama, ollama:<model>, stub"),
    )
    parser.add_argument(
        "--keep-collection",
        action="store_true",
        help="Keep JOBS_COMPARE_GENERATION after running (default: delete).",
    )
    args = parser.parse_args()

    try:
        generators = {label: build_generator(label) for label in args.providers}
        result = compare_generators(
            generators,
            keep_collection=args.keep_collection,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    _print_results(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
