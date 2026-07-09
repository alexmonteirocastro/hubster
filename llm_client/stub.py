"""Deterministic Generator for local UI and integration testing.

Returns instantly with markdown-shaped text so the chat UI can be exercised
without calling Gemini or Ollama.
"""

import re

from llm_client.base import Generator

_JOB_URL_RE = re.compile(r"url:\s*(https://[^\s)]+)")


def _first_job_title(context: str) -> str | None:
    match = re.search(r"Job Title:\s*(.+)", context)
    return match.group(1).strip() if match else None


def _first_job_url(context: str) -> str | None:
    match = _JOB_URL_RE.search(context)
    return match.group(1) if match else None


class StubGenerator(Generator):
    def generate(self, context: str, question: str) -> str:
        title = _first_job_title(context)
        job_url = _first_job_url(context)
        if title and job_url:
            lead = f"[{title}]({job_url}) looks like the closest match."
        elif title:
            lead = f"**{title}** looks like the closest match."
        else:
            lead = "Here are roles that match your question."
        stub_note = (
            "_Stub generator response — set LLM_PROVIDER=stub in .env "
            "for instant UI testing._"
        )
        return (
            f"{lead}\n\n"
            f"Question: {question}\n\n"
            "- **Senior Backend Engineer** at Example Co (Copenhagen)\n"
            "- **Platform Engineer** at Nordic Startup (remote)\n\n"
            f"{stub_note}"
        )
