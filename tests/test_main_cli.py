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


def test_run_main_rejects_reset_without_seed(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--reset"])

    with pytest.raises(SystemExit):
        _run_main()


def test_main_seed_reset_drops_collection_before_create_and_seed(monkeypatch):
    settings = SimpleNamespace(
        qdrant_collection_name="JOBS_ON_THE_HUB",
        qdrant_dev_collection_name="JOBS_DEV",
    )
    mock_client = MagicMock()
    mock_drop_db = MagicMock()
    mock_create_collection = MagicMock()
    mock_seed = MagicMock()
    mock_query_jobs = MagicMock(return_value=SimpleNamespace(points=[]))
    call_order: list[str] = []

    mock_drop_db.side_effect = lambda *args, **kwargs: call_order.append("drop")
    mock_create_collection.side_effect = lambda *args, **kwargs: call_order.append(
        "create"
    )
    mock_seed.side_effect = lambda *args, **kwargs: call_order.append("seed")

    monkeypatch.setattr("main.get_settings", lambda: settings)
    monkeypatch.setattr("main.get_qdrant_client", lambda: mock_client)
    monkeypatch.setattr("main.drop_db", mock_drop_db)
    monkeypatch.setattr("main.create_collection", mock_create_collection)
    monkeypatch.setattr("main.seed_qdrant_db", mock_seed)
    monkeypatch.setattr("main.query_jobs_in_qdrant", mock_query_jobs)

    main(mode="seed", reset=True)

    mock_drop_db.assert_called_once_with(mock_client, "JOBS_ON_THE_HUB")
    mock_create_collection.assert_called_once_with(mock_client, "JOBS_ON_THE_HUB")
    mock_seed.assert_called_once_with(mock_client, "JOBS_ON_THE_HUB")
    assert call_order == ["drop", "create", "seed"]


def test_main_seed_without_reset_skips_drop(monkeypatch):
    settings = SimpleNamespace(
        qdrant_collection_name="JOBS_ON_THE_HUB",
        qdrant_dev_collection_name="JOBS_DEV",
    )
    mock_client = MagicMock()
    mock_drop_db = MagicMock()
    mock_create_collection = MagicMock()
    mock_seed = MagicMock()
    mock_query_jobs = MagicMock(return_value=SimpleNamespace(points=[]))

    monkeypatch.setattr("main.get_settings", lambda: settings)
    monkeypatch.setattr("main.get_qdrant_client", lambda: mock_client)
    monkeypatch.setattr("main.drop_db", mock_drop_db)
    monkeypatch.setattr("main.create_collection", mock_create_collection)
    monkeypatch.setattr("main.seed_qdrant_db", mock_seed)
    monkeypatch.setattr("main.query_jobs_in_qdrant", mock_query_jobs)

    main(mode="seed", reset=False)

    mock_drop_db.assert_not_called()
    mock_create_collection.assert_called_once_with(mock_client, "JOBS_ON_THE_HUB")
    mock_seed.assert_called_once_with(mock_client, "JOBS_ON_THE_HUB")


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
