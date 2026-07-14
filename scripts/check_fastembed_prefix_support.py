"""ALE-138: Check FastEmbed's own metadata for query/passage prefix handling.

This answers, without touching Qdrant at all, whether FastEmbed knows
`intfloat/multilingual-e5-small` needs "query: " / "passage: " prefixes and
applies them automatically when you call the model-aware embed methods
(the ones qdrant-client's `models.Document(text=..., model=...)` integration
uses under the hood).

Usage:

    uv run python scripts/check_fastembed_prefix_support.py

Requires `fastembed` to be installed locally (already a transitive dep via
`qdrant-client[fastembed]`), but does NOT require a running Qdrant instance
or network access to Qdrant Cloud — this only inspects FastEmbed's local
model registry.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastembed import TextEmbedding

CANDIDATE_MODELS = [
    "BAAI/bge-small-en-v1.5",  # current model, for comparison
    "sentence-transformers/all-MiniLM-L6-v2",
    "intfloat/multilingual-e5-small",
]


def main() -> None:
    supported = TextEmbedding.list_supported_models()
    by_name = {entry["model"]: entry for entry in supported}

    print("=" * 90)
    print("FastEmbed model metadata — looking for query/passage prefix fields")
    print("=" * 90)

    for model_name in CANDIDATE_MODELS:
        entry = by_name.get(model_name)
        if entry is None:
            print(f"\n{model_name}: NOT FOUND in FastEmbed's supported models list.")
            print("  (Qdrant Cloud Inference's own hosted version may still work at")
            print("   query time even if this exact name isn't in local FastEmbed's")
            print("   registry — this check only covers local/client-side inference.)")
            continue

        print(f"\n{model_name}:")
        print(json.dumps(entry, indent=2, default=str))

        prefix_fields = {k: v for k, v in entry.items() if "prefix" in k.lower()}
        if prefix_fields:
            print(f"  -> Prefix-related fields found: {prefix_fields}")
            print(
                "  -> If these are non-empty, FastEmbed applies them automatically "
                "when using model.embed() vs model.query_embed() (or the "
                "qdrant-client Document-based integration, which calls the "
                "correct one for you)."
            )
        else:
            print(
                "  -> No prefix-related metadata field found. This suggests either "
                "(a) this model doesn't need prefixing, or (b) FastEmbed's metadata "
                "for this model doesn't expose it under an obviously-named field — "
                "worth also doing the empirical check "
                "(scripts/compare_embedding_models.py) rather than trusting this "
                "alone."
            )

    print("\n" + "=" * 90)
    print(
        "NOTE: this only tells you what LOCAL FastEmbed does. Hubster on Render "
        "would use Qdrant CLOUD Inference (server-side), which may or may not "
        "apply the same prefix logic — the empirical golden-query comparison "
        "(compare_embedding_models.py) is the authoritative check for actual "
        "production behavior, this script is a fast first-pass sanity check."
    )
    print("=" * 90)


if __name__ == "__main__":
    main()
