"""ALE-143: Latency probe for Cloud Inference Document dedupe (ADR-0010 Decision 7).

Compares wall-clock time for ``query_batch_points`` when the dense prefetch and
companion dense query share one ``Document`` instance (production shape) vs two
separate identical ``Document`` instances (control).

Interpretation (be honest):
- Shared meaningfully faster than control → evidence of content- or
  identity-keyed embed dedupe.
- Shared ≈ control → **ambiguous**, not proof of "no dedupe". Embedding may be
  a small fraction of free-tier latency; network noise can hide a real 2x.
- Prefer confirming with Qdrant support/Discord if results stay inconclusive.

Requires Qdrant Cloud Inference (same as production E5 path). Does not touch
``QDRANT_COLLECTION_NAME`` or ``JOBS_DEV``.

Usage:

    uv run python scripts/verify_inference_dedupe.py
    uv run python scripts/verify_inference_dedupe.py --reps 50 --keep-collection
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

from qdrant_client import models

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from db.database import (  # noqa: E402
    create_collection,
    drop_db,
    get_dense_vector_name,
    load_jobs_into_qdrant,
)
from db.settings import (  # noqa: E402
    BM25_SPARSE_MODEL,
    BM25_SPARSE_VECTOR_NAME,
    get_settings,
    uses_cloud_inference,
)
from evals.collections import (  # noqa: E402
    get_comparison_client,
    validate_qdrant_config,
)
from evals.fixtures import load_golden_jobs  # noqa: E402

DEDUPE_PROBE_COLLECTION = "JOBS_COMPARE_INFERENCE_DEDUPE"
DEFAULT_REPS = 40
# Near E5's 512-token window so embedding cost is more visible vs network RTT.
_LONG_QUERY = (
    "Looking for a senior Python backend engineer with deep FastAPI and Django "
    "experience building REST and GraphQL APIs, owning Terraform infrastructure "
    "as code on AWS, writing Go services where latency matters, mentoring the "
    "team on testing and observability, and collaborating with product on "
    "roadmap tradeoffs for Nordic remote-friendly startups. "
) * 8


def _build_batch_requests(
    *,
    query_text: str,
    embedding_model: str,
    dense_name: str,
    share_document: bool,
    limit: int = 5,
) -> list[models.QueryRequest]:
    if share_document:
        dense_query = models.Document(text=query_text, model=embedding_model)
        companion_query = dense_query
    else:
        dense_query = models.Document(text=query_text, model=embedding_model)
        companion_query = models.Document(text=query_text, model=embedding_model)

    sparse_query = models.Document(text=query_text, model=BM25_SPARSE_MODEL)
    prefetch_limit = max(limit * 4, 20)
    fused = models.QueryRequest(
        prefetch=[
            models.Prefetch(
                query=dense_query,
                using=dense_name,
                limit=prefetch_limit,
            ),
            models.Prefetch(
                query=sparse_query,
                using=BM25_SPARSE_VECTOR_NAME,
                limit=prefetch_limit,
            ),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=limit,
        with_payload=True,
    )
    companion = models.QueryRequest(
        query=companion_query,
        using=dense_name,
        limit=limit,
        with_payload=True,
    )
    return [fused, companion]


def _time_batch(
    client: object,
    collection_name: str,
    requests: list[models.QueryRequest],
) -> float:
    started = time.perf_counter()
    client.query_batch_points(  # type: ignore[attr-defined]
        collection_name=collection_name,
        requests=requests,
    )
    return time.perf_counter() - started


def _summarize(label: str, samples: list[float]) -> None:
    mean = statistics.mean(samples)
    median = statistics.median(samples)
    stdev = statistics.stdev(samples) if len(samples) > 1 else 0.0
    print(
        f"{label:>10}: n={len(samples)}  "
        f"mean={mean * 1000:7.1f}ms  "
        f"median={median * 1000:7.1f}ms  "
        f"stdev={stdev * 1000:6.1f}ms"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reps",
        type=int,
        default=DEFAULT_REPS,
        help=f"Timed repetitions per scenario (default: {DEFAULT_REPS}).",
    )
    parser.add_argument(
        "--query",
        default=_LONG_QUERY,
        help="Query text to embed (default: long string near E5 context size).",
    )
    parser.add_argument(
        "--keep-collection",
        action="store_true",
        help="Keep disposable probe collection after running (default: delete).",
    )
    args = parser.parse_args()
    if args.reps < 2:
        print("Error: --reps must be >= 2", file=sys.stderr)
        return 1

    try:
        validate_qdrant_config()
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    settings = get_settings()
    if not uses_cloud_inference(settings):
        print(
            "Error: this probe requires Qdrant Cloud Inference "
            "(QDRANT_URL + QDRANT_API_KEY). Local FastEmbed cannot measure "
            "Cloud Inference Document dedupe.",
            file=sys.stderr,
        )
        return 1

    client = get_comparison_client()
    collection_name = DEDUPE_PROBE_COLLECTION
    drop_db(client, collection_name)
    create_collection(client, collection_name)
    # One golden job is enough — we only need a collection that accepts hybrid queries.
    load_jobs_into_qdrant(client, collection_name, load_golden_jobs()[:1])
    dense_name = get_dense_vector_name(client, collection_name)

    shared_req = _build_batch_requests(
        query_text=args.query,
        embedding_model=settings.embedding_model,
        dense_name=dense_name,
        share_document=True,
    )
    control_req = _build_batch_requests(
        query_text=args.query,
        embedding_model=settings.embedding_model,
        dense_name=dense_name,
        share_document=False,
    )

    # Warmup (excluded from stats).
    _time_batch(client, collection_name, shared_req)
    _time_batch(client, collection_name, control_req)

    shared_samples: list[float] = []
    control_samples: list[float] = []
    # Interleave to reduce free-tier cold-start bias favoring whichever runs first.
    for _ in range(args.reps):
        shared_samples.append(_time_batch(client, collection_name, shared_req))
        control_samples.append(_time_batch(client, collection_name, control_req))

    print("\n" + "=" * 72)
    print("CLOUD INFERENCE DOCUMENT DEDUPE LATENCY PROBE")
    print("=" * 72)
    print(f"Collection: {collection_name}")
    print(f"Model:      {settings.embedding_model}")
    print(f"Query chars:{len(args.query)}")
    shared_prefetch = shared_req[0].prefetch
    control_prefetch = control_req[0].prefetch
    assert isinstance(shared_prefetch, list) and shared_prefetch
    assert isinstance(control_prefetch, list) and control_prefetch
    shared_same = shared_prefetch[0].query is shared_req[1].query
    control_same = control_prefetch[0].query is control_req[1].query
    print(f"Shared Document identity: {shared_same}")
    print(f"Control Document identity: {control_same}")
    _summarize("shared", shared_samples)
    _summarize("control", control_samples)
    delta = statistics.mean(control_samples) - statistics.mean(shared_samples)
    print(f"\nmean(control) - mean(shared) = {delta * 1000:+.1f}ms")
    print(
        "\nInterpretation: a clear positive delta supports dedupe; "
        "near-zero is ambiguous (see ADR-0010 Decision 7 / script docstring)."
    )

    if not args.keep_collection:
        drop_db(client, collection_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
