import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from llm_client.base import Generator

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def _load_golden_generation() -> dict:
    return json.loads((FIXTURES_DIR / "golden_generation.json").read_text(encoding="utf-8"))


class ScriptedGenerator(Generator):
    def __init__(self, answer: str):
        self.answer = answer
        self.calls: list[tuple[str, str]] = []

    def generate(self, context: str, question: str) -> str:
        self.calls.append((context, question))
        return self.answer


@pytest.mark.generation
def test_golden_generation_cases(retrieval_qdrant):
    client, collection_name = retrieval_qdrant
    golden_set = _load_golden_generation()
    api_client = TestClient(app)

    for case in golden_set["cases"]:
        expected_answer = (
            f"Mocked grounded answer mentioning {case['mock_answer_substring']}."
        )
        scripted = ScriptedGenerator(answer=expected_answer)
        settings = SimpleNamespace(qdrant_collection_name=collection_name)

        with (
            patch("api.main.get_qdrant_client", return_value=client),
            patch("api.main.get_settings", return_value=settings),
            patch("api.main.get_generator", return_value=scripted),
        ):
            response = api_client.post("/chat", json={"question": case["query"]})

        assert response.status_code == 200, case["id"]
        body = response.json()
        assert body["generated"] is True, case["id"]
        assert body["answer"] == expected_answer, case["id"]
        returned_job_ids = [source["job_id"] for source in body["sources"]]
        for job_id in case["expected_source_job_ids"]:
            assert job_id in returned_job_ids, (
                f"Golden generation case '{case['id']}' missed expected source job {job_id}. "
                f"Returned: {returned_job_ids}"
            )
        assert len(scripted.calls) == 1, case["id"]
        context, question = scripted.calls[0]
        assert question == case["query"], case["id"]
        assert context.strip(), case["id"]
