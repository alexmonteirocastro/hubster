"""ALE-140 follow-up: Token-length distribution for production document_text.

Scrolls JOBS_ON_THE_HUB (read-only), tokenizes each stored `document_text` with
the intfloat/multilingual-e5-small tokenizer, and reports percentile stats
against the model's 512-token context window.

Qdrant Cloud Inference prepends `passage: ` on upsert for E5 models, so counts
use that prefixed form (see Qdrant Cloud Inference docs).

Usage:

    uv run python scripts/check_e5_document_token_lengths.py
    uv run python scripts/check_e5_document_token_lengths.py --limit 100

Requires .env with QDRANT_URL, QDRANT_API_KEY, QDRANT_COLLECTION_NAME.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from huggingface_hub import hf_hub_download  # noqa: E402
from qdrant_client import QdrantClient  # noqa: E402
from tokenizers import Tokenizer  # noqa: E402

from db import get_settings  # noqa: E402

E5_MODEL = "intfloat/multilingual-e5-small"
E5_MAX_TOKENS = 512
E5_PASSAGE_PREFIX = "passage: "
SCROLL_BATCH_SIZE = 100


@dataclass
class TokenLengthStats:
    corpus_size: int
    skipped_points: int
    p50: float
    p90: float
    p99: float
    max_tokens: int
    over_limit: int
    over_limit_pct: float
    top_offenders: list[tuple[int, str, str, str]]


def _validate_config() -> None:
    settings = get_settings()
    host = urlparse(settings.qdrant_url).hostname or ""
    is_cloud_host = host not in {"", "localhost", "127.0.0.1", "::1"}
    if is_cloud_host and settings.qdrant_api_key is None:
        raise ValueError(
            f"QDRANT_URL points at Qdrant Cloud ({settings.qdrant_url}) but "
            "QDRANT_API_KEY is not set."
        )


def _get_client() -> QdrantClient:
    settings = get_settings()
    kwargs: dict[str, str | bool] = {"url": settings.qdrant_url}
    if settings.qdrant_api_key:
        kwargs["api_key"] = settings.qdrant_api_key
    return QdrantClient(**kwargs)


@lru_cache(maxsize=1)
def _load_e5_tokenizer() -> Tokenizer:
    tokenizer_path = hf_hub_download(E5_MODEL, "tokenizer.json")
    return Tokenizer.from_file(tokenizer_path)


def _percentile(values: list[int], pct: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = (len(sorted_vals) - 1) * pct / 100
    lower = math.floor(idx)
    upper = math.ceil(idx)
    if lower == upper:
        return float(sorted_vals[int(idx)])
    weight = idx - lower
    return sorted_vals[lower] * (1 - weight) + sorted_vals[upper] * weight


def _embedding_input(document_text: str) -> str:
    if document_text.startswith(E5_PASSAGE_PREFIX):
        return document_text
    return f"{E5_PASSAGE_PREFIX}{document_text}"


def _count_tokens(tokenizer: Tokenizer, document_text: str) -> int:
    return len(tokenizer.encode(_embedding_input(document_text)).ids)


def _scroll_production_corpus(
    client: QdrantClient, collection_name: str, limit: int | None
) -> tuple[list[dict], int]:
    print(f"Scrolling production collection {collection_name!r} (read-only)...")
    points: list[dict] = []
    skipped = 0
    next_offset = None
    while True:
        batch, next_offset = client.scroll(
            collection_name=collection_name,
            limit=SCROLL_BATCH_SIZE,
            offset=next_offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in batch:
            payload = point.payload or {}
            doc_text = payload.get("document_text")
            job_id = payload.get("job_url_identifier")
            if not doc_text or not job_id:
                skipped += 1
                continue
            points.append(
                {
                    "job_url_identifier": job_id,
                    "document_text": doc_text,
                    "job_title": payload.get("job_title") or "?",
                    "company": payload.get("company") or "?",
                }
            )
            if limit is not None and len(points) >= limit:
                print(f"Stopped at --limit {limit}.")
                return points, skipped
        print(f"  scrolled {len(points)} points so far...")
        if next_offset is None:
            break
    print(f"Done: {len(points)} points pulled from production (read-only).")
    return points, skipped


def analyze_token_lengths(
    production_points: list[dict], *, skipped_points: int
) -> TokenLengthStats:
    tokenizer = _load_e5_tokenizer()
    token_counts: list[int] = []
    offenders: list[tuple[int, str, str, str]] = []

    for item in production_points:
        count = _count_tokens(tokenizer, item["document_text"])
        token_counts.append(count)
        if count > E5_MAX_TOKENS:
            offenders.append(
                (
                    count,
                    item["job_url_identifier"],
                    item["job_title"],
                    item["company"],
                )
            )

    offenders.sort(reverse=True)
    over_limit = len(offenders)
    corpus_size = len(token_counts)
    return TokenLengthStats(
        corpus_size=corpus_size,
        skipped_points=skipped_points,
        p50=_percentile(token_counts, 50),
        p90=_percentile(token_counts, 90),
        p99=_percentile(token_counts, 99),
        max_tokens=max(token_counts) if token_counts else 0,
        over_limit=over_limit,
        over_limit_pct=(100.0 * over_limit / corpus_size if corpus_size else 0.0),
        top_offenders=offenders[:10],
    )


def _print_stats(stats: TokenLengthStats) -> None:
    print("\n" + "=" * 80)
    print(f"E5 passage token lengths — {E5_MODEL} (limit={E5_MAX_TOKENS})")
    print("=" * 80)
    print(f"Corpus size: {stats.corpus_size} points")
    if stats.skipped_points:
        print(f"Skipped (missing document_text/job_id): {stats.skipped_points}")
    print(
        "Input form: `passage: ` + stored document_text "
        "(Qdrant Cloud Inference upsert behavior)"
    )
    print("\nDistribution:")
    print(
        f"  p50={stats.p50:.1f}  p90={stats.p90:.1f}  "
        f"p99={stats.p99:.1f}  max={stats.max_tokens}"
    )
    print(
        f"\nOver {E5_MAX_TOKENS} tokens: {stats.over_limit} points "
        f"({stats.over_limit_pct:.2f}%)"
    )
    if stats.top_offenders:
        print("\nTop offenders (>512):")
        for count, job_id, title, company in stats.top_offenders:
            print(f"  {count:4d} tokens  {job_id}  {title} @ {company}")


def format_linear_comment(stats: TokenLengthStats, *, collection_name: str) -> str:
    if stats.over_limit == 0:
        verdict = (
            f"Verified: p99 ({stats.p99:.1f} tokens) is under the E5 512-token "
            "context window on the current production corpus. Truncation risk is "
            "low at current document_text lengths; no chunking action needed now."
        )
    else:
        verdict = (
            f"{stats.over_limit} points ({stats.over_limit_pct:.2f}%) exceed 512 "
            "tokens under E5 passage encoding. BGE-small-en-v1.5 also capped at "
            "512 tokens, so this is likely pre-existing truncation rather than a "
            "new E5 regression — but it was previously assumed, not measured. "
            "Improving coverage (chunking, summarization, etc.) is out of ALE-140 "
            "scope; open a separate spike if we want to quantify retrieval impact."
        )

    cloud_docs = "https://qdrant.tech/documentation/inference/cloud-inference/"
    return f"""## E5 document_text token-length check (ALE-140 follow-up)

Read-only scroll of `{collection_name}` ({stats.corpus_size} points with
`document_text`), tokenized with `{E5_MODEL}` using `passage: ` + stored text
(Qdrant Cloud Inference upsert behavior — see
[Cloud Inference docs]({cloud_docs})).

| Metric | Tokens |
|---|---:|
| p50 | {stats.p50:.1f} |
| p90 | {stats.p90:.1f} |
| p99 | {stats.p99:.1f} |
| max | {stats.max_tokens} |

**Over 512 tokens:** {stats.over_limit} / {stats.corpus_size} \
({stats.over_limit_pct:.2f}%)

**Finding:** {verdict}

Script: `scripts/check_e5_document_token_lengths.py` (re-runnable).
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Analyze only the first N production points (smoke test).",
    )
    parser.add_argument(
        "--print-linear-comment",
        action="store_true",
        help="Print a Markdown block suitable for a Linear ticket comment.",
    )
    args = parser.parse_args()

    try:
        _validate_config()
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    settings = get_settings()
    client = _get_client()
    production_points, skipped = _scroll_production_corpus(
        client, settings.qdrant_collection_name, args.limit
    )
    if not production_points:
        print("No points found in production collection.")
        return 1

    stats = analyze_token_lengths(production_points, skipped_points=skipped)
    _print_stats(stats)
    if args.print_linear_comment:
        comment = format_linear_comment(
            stats, collection_name=settings.qdrant_collection_name
        )
        print("\n" + comment)
    return 0


if __name__ == "__main__":
    sys.exit(main())
