"""One-shot screenshot capture for GUIDE.md (JOBS_DEV / golden fixtures).

Run while Streamlit is up:
  uv run --with playwright python evals_system/assets/_capture_screenshots.py
"""

from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8502"
OUT = Path(__file__).resolve().parent
VIEWPORT = {"width": 1400, "height": 900}


def _wait_ready(page) -> None:
    page.goto(BASE, wait_until="domcontentloaded")
    page.get_by_text("Hubster eval review").first.wait_for(timeout=60_000)
    time.sleep(1.5)


def _click_tab(page, name: str) -> None:
    page.get_by_role("tab", name=name).click()
    time.sleep(0.8)


def _shot(page, name: str) -> None:
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    print(f"wrote {path.name}")


def _hide_streamlit_chrome(page) -> None:
    page.add_style_tag(
        content="""
        [data-testid="stStatusWidget"],
        [data-testid="stToolbar"],
        .stDeployButton,
        header[data-testid="stHeader"] { display: none !important; }
        """
    )


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport=VIEWPORT)
        _wait_ready(page)
        _hide_streamlit_chrome(page)

        _shot(page, "01-overview-review-form")

        page.get_by_role("textbox", name="Query").fill(
            "remote backend engineer building APIs in Copenhagen Denmark"
        )
        page.get_by_role("button", name="Run query").click()
        try:
            page.get_by_text("Judgment", exact=True).wait_for(timeout=120_000)
        except Exception:
            _shot(page, "debug-review-failed")
            raise
        time.sleep(1.0)
        _shot(page, "02-review-sources-answer")

        _click_tab(page, "Embeddings")
        _hide_streamlit_chrome(page)
        _shot(page, "03-embeddings-form")
        page.get_by_role("button", name="Run embedding comparison").click()
        try:
            page.get_by_text("Summaries", exact=True).wait_for(timeout=600_000)
        except Exception:
            _shot(page, "debug-embeddings-failed")
            raise
        time.sleep(1.0)
        _shot(page, "04-embeddings-results")

        _click_tab(page, "Generation")
        _hide_streamlit_chrome(page)
        _shot(page, "05-generation-form")
        page.get_by_role("button", name="Run generation comparison").click()
        try:
            page.get_by_text("Collection:", exact=False).first.wait_for(timeout=300_000)
        except Exception:
            _shot(page, "debug-generation-failed")
            raise
        time.sleep(1.0)
        _shot(page, "06-generation-results")

        _click_tab(page, "Min-score sweep")
        _hide_streamlit_chrome(page)
        _shot(page, "07-sweep-form")
        page.get_by_role("button", name="Run retrieval").click()
        try:
            page.get_by_text("Live threshold", exact=True).wait_for(timeout=300_000)
        except Exception:
            _shot(page, "debug-sweep-failed")
            raise
        time.sleep(1.0)
        _shot(page, "08-sweep-results")

        browser.close()


if __name__ == "__main__":
    main()
