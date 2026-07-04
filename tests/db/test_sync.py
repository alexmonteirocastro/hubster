from db.db_utils import compute_sync_diff


def test_compute_sync_diff_identifies_new_and_stale_jobs():
    live = {"job-a", "job-b", "job-c"}
    indexed = {"job-b", "job-d"}

    to_add, to_remove = compute_sync_diff(live, indexed)

    assert to_add == {"job-a", "job-c"}
    assert to_remove == {"job-d"}


def test_compute_sync_diff_no_changes():
    live = {"job-a", "job-b"}
    indexed = {"job-a", "job-b"}

    to_add, to_remove = compute_sync_diff(live, indexed)

    assert to_add == set()
    assert to_remove == set()
