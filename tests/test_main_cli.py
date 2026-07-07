import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from main import _run_main, main


def test_run_main_rejects_backfill_and_seed_together(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--backfill", "--seed"])

    with pytest.raises(SystemExit):
        _run_main()


def test_main_backfill_dev_raises_when_dev_collection_matches_production(monkeypatch):
    monkeypatch.setattr(
        "main.get_settings",
        lambda: SimpleNamespace(
            qdrant_collection_name="JOBS_ON_THE_HUB",
            qdrant_dev_collection_name="JOBS_ON_THE_HUB",
        ),
    )
    monkeypatch.setattr("main.get_qdrant_client", lambda: MagicMock())

    with pytest.raises(ValueError, match="must differ"):
        main(mode="backfill-dev")


def test_main_backfill_calls_backfill_and_skips_collection_setup(monkeypatch):
    settings = SimpleNamespace(
        qdrant_collection_name="JOBS_ON_THE_HUB",
        qdrant_dev_collection_name="JOBS_DEV",
    )
    mock_client = MagicMock()
    mock_backfill = MagicMock(return_value=(10, 0, 0))
    mock_create_collection = MagicMock()
    mock_query_jobs = MagicMock()

    monkeypatch.setattr("main.get_settings", lambda: settings)
    monkeypatch.setattr("main.get_qdrant_client", lambda: mock_client)
    monkeypatch.setattr("main.backfill_job_title_company_metadata", mock_backfill)
    monkeypatch.setattr("main.create_collection", mock_create_collection)
    monkeypatch.setattr("main.query_jobs_in_qdrant", mock_query_jobs)

    main(mode="backfill")

    mock_backfill.assert_called_once_with(mock_client, "JOBS_ON_THE_HUB")
    mock_create_collection.assert_not_called()
    mock_query_jobs.assert_not_called()
