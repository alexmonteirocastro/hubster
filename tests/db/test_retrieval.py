import json
from pathlib import Path

import pytest

from db.database import query_jobs_in_qdrant

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def _load_golden_queries() -> dict:
    return json.loads((FIXTURES_DIR / "golden_queries.json").read_text(encoding="utf-8"))


def _job_ids_from_hits(hits) -> list[str]:
    return [hit.payload["job_url_identifier"] for hit in hits]


@pytest.mark.retrieval
def test_golden_queries_hit_expected_jobs_in_top_k(retrieval_qdrant):
    client, collection_name = retrieval_qdrant
    golden_set = _load_golden_queries()
    top_k = golden_set["top_k"]

    for case in golden_set["queries"]:
        results = query_jobs_in_qdrant(
            db_client=client,
            collection_name=collection_name,
            query_text=case["query"],
            limit=top_k,
        )
        returned_job_ids = _job_ids_from_hits(results.points)
        missing = [
            job_id
            for job_id in case["expected_job_ids"]
            if job_id not in returned_job_ids
        ]

        assert not missing, (
            f"Golden query '{case['id']}' missed expected job(s) {missing} in top-{top_k}. "
            f"Returned: {returned_job_ids}"
        )
