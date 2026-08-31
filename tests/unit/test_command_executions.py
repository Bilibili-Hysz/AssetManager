"""CommandExecutionStore — plan-hash dedup store unit tests (T8 minimal)."""
import sqlite3

import pytest

from AssetsManager.application import command_executions as ce_module
from AssetsManager.application.command_executions import (
    CommandExecutionStore,
    plan_hash,
)


@pytest.fixture
def store():
    """A migrated in-memory database with a store bound to it."""
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(database._SCHEMA)
    assert migrate(conn) == 42
    return CommandExecutionStore(lambda: conn)


def test_plan_hash_is_order_insensitive_over_targets():
    assert plan_hash("file.delete_permanent", ["b", "a"]) == \
        plan_hash("file.delete_permanent", ["a", "b"])


def test_plan_hash_changes_with_command_or_params():
    base = plan_hash("file.delete_permanent", ["a"])
    assert plan_hash("file.delete_trash", ["a"]) != base
    assert plan_hash("file.delete_permanent", ["a"], recursive=True) != base


def test_begin_fresh_plan_returns_true_and_inserts_executing_row(store):
    h = plan_hash("file.delete_permanent", ["a"])
    assert store.begin(h, "file.delete_permanent", '["a"]') is True
    conn = store._connection_provider()
    row = conn.execute(
        "SELECT command_id, status, targets_json FROM command_executions "
        "WHERE plan_hash = ?",
        (h,),
    ).fetchone()
    assert row == ("file.delete_permanent", "executing", '["a"]')


def test_begin_after_success_is_deduped(store):
    h = plan_hash("file.delete_permanent", ["a"])
    assert store.begin(h, "file.delete_permanent", '["a"]') is True
    store.mark_succeeded(h, "1 files")
    assert store.begin(h, "file.delete_permanent", '["a"]') is False


def test_in_flight_plan_is_deduped_within_ttl(store):
    h = plan_hash("file.delete_permanent", ["a"])
    assert store.begin(h, "file.delete_permanent", '["a"]') is True
    assert store.begin(h, "file.delete_permanent", '["a"]') is False


def test_stale_executing_row_is_taken_over(store):
    h = plan_hash("file.delete_permanent", ["a"])
    assert store.begin(h, "file.delete_permanent", '["a"]') is True
    conn = store._connection_provider()
    with ce_module.db_write_lock(conn):
        # Simulate a crash: rewind the executing row past the TTL.
        conn.execute(
            "UPDATE command_executions SET executed_at = executed_at - 3600"
        )
        conn.commit()
    assert store.begin(h, "file.delete_permanent", '["a"]') is True


def test_clear_allows_retry_after_failure(store):
    h = plan_hash("file.delete_permanent", ["a"])
    store.begin(h, "file.delete_permanent", '["a"]')
    store.clear(h)
    assert store.begin(h, "file.delete_permanent", '["a"]') is True


def test_mark_succeeded_then_clear_allows_retry(store):
    h = plan_hash("file.delete_permanent", ["a"])
    store.begin(h, "file.delete_permanent", '["a"]')
    store.mark_succeeded(h, "2 files")
    store.clear(h)
    assert store.begin(h, "file.delete_permanent", '["a"]') is True


def test_fail_open_when_connection_provider_raises(store):
    store._connection_provider = lambda: (_ for _ in ()).throw(
        RuntimeError("store down"))
    h = plan_hash("file.delete_permanent", ["a"])
    assert store.begin(h, "file.delete_permanent", '["a"]') is True


def test_fifo_trim_caps_rows(monkeypatch):
    from AssetsManager.core import database

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(database._SCHEMA)
    from AssetsManager.core.db_migrations import migrate
    assert migrate(conn) == 42
    monkeypatch.setattr(ce_module, "MAX_ROWS", 5)
    store = CommandExecutionStore(lambda: conn)
    for i in range(8):
        h = plan_hash("file.delete_permanent", [f"p{i}"])
        assert store.begin(h, "file.delete_permanent", f'["p{i}"]') is True
    count = conn.execute("SELECT count(*) FROM command_executions").fetchone()[0]
    assert count == 5
