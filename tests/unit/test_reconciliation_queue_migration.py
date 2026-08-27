import json
import sqlite3

import pytest


_SCHEMA = """
CREATE TABLE reconciliation_tasks (
    task_id TEXT PRIMARY KEY NOT NULL,
    library_root TEXT NOT NULL,
    path TEXT NOT NULL,
    kind TEXT NOT NULL,
    reason TEXT NOT NULL,
    state TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    next_attempt_at_wallclock REAL NOT NULL,
    operation_ids TEXT NOT NULL DEFAULT '[]',
    last_error_type TEXT,
    last_error TEXT,
    expected_revision INTEGER,
    observed_revision INTEGER,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    lease_expires_at_wallclock REAL,
    lease_token TEXT,
    max_attempts INTEGER NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    UNIQUE (library_root, path, kind)
);
CREATE INDEX idx_reconciliation_tasks_due
    ON reconciliation_tasks(library_root, state, next_attempt_at_wallclock);
CREATE TABLE reconciliation_queue_state (
    library_root TEXT PRIMARY KEY NOT NULL,
    generation INTEGER NOT NULL DEFAULT 0 CHECK (generation >= 0),
    updated_at REAL NOT NULL
);
"""


def _store(tmp_path):
    from AssetsManager.application import SQLiteReconciliationQueueStore

    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.executescript(_SCHEMA)
    connection.commit()
    store = SQLiteReconciliationQueueStore(
        connection=connection,
        library_root=tmp_path / "library",
        allow_unmanaged=True,
        clock=lambda: 10.0,
        wall_clock=lambda: 1000.0,
    )
    return connection, store


def _legacy_marker(tmp_path):
    from AssetsManager.application import ReconciliationQueue

    marker = tmp_path / "reconciliation-queue.json"
    queue = ReconciliationQueue(
        library_root=tmp_path / "library",
        persistence_path=marker,
        clock=lambda: 10.0,
        wall_clock=lambda: 1000.0,
    )
    task = queue.enqueue_or_merge(
        path=tmp_path / "library",
        reason="busy",
        operation_id="legacy-op",
        now=10.0,
    )
    return marker, task


def test_marker_migration_imports_and_archives_after_sqlite_commit(tmp_path):
    from AssetsManager.application import (
        ReconciliationMarkerMigrationStatus,
        migrate_reconciliation_marker,
    )

    connection, store = _store(tmp_path)
    try:
        marker, task = _legacy_marker(tmp_path)
        result = migrate_reconciliation_marker(
            marker_path=marker,
            library_root=tmp_path / "library",
            store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )

        assert result.status is ReconciliationMarkerMigrationStatus.IMPORTED
        assert result.task_count == 1
        assert not marker.exists()
        assert result.archive_path.exists()
        assert store.load()[0].task_id == task.task_id
    finally:
        connection.close()


def test_marker_migration_retries_archive_after_crash_between_commit_and_rename(
    tmp_path, monkeypatch
):
    from AssetsManager.application import (
        ReconciliationMarkerMigrationError,
        ReconciliationMarkerMigrationStatus,
        migrate_reconciliation_marker,
    )
    import AssetsManager.application.reconciliation_queue_migration as migration

    connection, store = _store(tmp_path)
    try:
        marker, task = _legacy_marker(tmp_path)
        original_rename = migration.os.rename

        def fail_rename(_source, _target):
            raise OSError("simulated archive failure")

        monkeypatch.setattr(migration.os, "rename", fail_rename)
        with pytest.raises(ReconciliationMarkerMigrationError) as error:
            migrate_reconciliation_marker(
                marker_path=marker,
                library_root=tmp_path / "library",
                store=store,
                clock=lambda: 10.0,
                wall_clock=lambda: 1000.0,
            )
        assert error.value.durable_store_updated
        assert marker.exists()
        assert store.load()[0].task_id == task.task_id

        monkeypatch.setattr(migration.os, "rename", original_rename)
        result = migrate_reconciliation_marker(
            marker_path=marker,
            library_root=tmp_path / "library",
            store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        assert result.status is ReconciliationMarkerMigrationStatus.ALREADY_DURABLE
        assert not marker.exists()
    finally:
        connection.close()


def test_marker_migration_rejects_conflicting_nonempty_durable_queue(tmp_path):
    from AssetsManager.application import (
        ReconciliationMarkerMigrationError,
        ReconciliationQueue,
        migrate_reconciliation_marker,
    )

    connection, store = _store(tmp_path)
    try:
        marker, _legacy_task = _legacy_marker(tmp_path)
        durable_queue = ReconciliationQueue(
            library_root=tmp_path / "library",
            persistence_store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        durable_queue.enqueue_or_merge(
            path=tmp_path / "library" / "other",
            reason="stale",
            now=10.0,
        )

        with pytest.raises(ReconciliationMarkerMigrationError, match="conflicts"):
            migrate_reconciliation_marker(
                marker_path=marker,
                library_root=tmp_path / "library",
                store=store,
                clock=lambda: 10.0,
                wall_clock=lambda: 1000.0,
            )
        assert marker.exists()
        assert len(store.load()) == 1
    finally:
        connection.close()


def test_marker_migration_retire_empty_marker_without_writing_queue(tmp_path):
    from AssetsManager.application import (
        ReconciliationMarkerMigrationStatus,
        migrate_reconciliation_marker,
    )

    connection, store = _store(tmp_path)
    try:
        marker = tmp_path / "reconciliation-queue.json"
        marker.write_text(
            json.dumps({"version": 2, "clock": "wallclock-deadlines", "tasks": []}),
            encoding="utf-8",
        )
        result = migrate_reconciliation_marker(
            marker_path=marker,
            library_root=tmp_path / "library",
            store=store,
            clock=lambda: 10.0,
            wall_clock=lambda: 1000.0,
        )
        assert result.status is ReconciliationMarkerMigrationStatus.RETIRED_EMPTY
        assert not marker.exists()
        assert store.load() == ()
    finally:
        connection.close()


def test_marker_migration_leaves_marker_when_sqlite_publish_fails(tmp_path):
    from AssetsManager.application import (
        ReconciliationMarkerMigrationError,
        migrate_reconciliation_marker,
    )

    connection, store = _store(tmp_path)
    try:
        marker, _task = _legacy_marker(tmp_path)

        def fail_replace(_tasks):
            raise RuntimeError("database unavailable")

        store.replace = fail_replace
        with pytest.raises(ReconciliationMarkerMigrationError) as error:
            migrate_reconciliation_marker(
                marker_path=marker,
                library_root=tmp_path / "library",
                store=store,
                clock=lambda: 10.0,
                wall_clock=lambda: 1000.0,
            )
        assert not error.value.durable_store_updated
        assert marker.exists()
    finally:
        connection.close()
