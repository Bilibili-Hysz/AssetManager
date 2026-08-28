"""Low-severity export-service regressions: snapshot locking and quick_check.

Bug 5: the snapshot page copy must never run inside ``db_write_lock``; a
large snapshot would otherwise block every in-process DB writer for the whole
copy duration (the SQLite backup API is WAL-aware and needs no lock).

Bug 6: the backup-validation ``quick_check`` connection must use an enlarged
page cache so the full-database integrity scan stays fast; the full scan
itself is kept because ``quick_check(N)`` only caps reported problems, it
does not sample N pages.
"""
from __future__ import annotations

from contextlib import contextmanager
import sqlite3

import pytest

import AssetsManager.application.library_export_service as export_module
from AssetsManager.application import LibraryExportService
from AssetsManager.core import path_resolver


@pytest.fixture(autouse=True)
def _use_temporary_runtime_root(tmp_path, monkeypatch):
    monkeypatch.setattr(path_resolver, "runtime_root", lambda: tmp_path / "RuntimeData")


def test_snapshot_page_copy_runs_outside_db_write_lock(opened_session, tmp_path, monkeypatch):
    bootstrap, session = opened_session
    service = bootstrap.runtime_for(session).services.export_service
    destination = tmp_path / "snapshot.db"
    real_connect = export_module.sqlite3.connect
    lock_depth = [0]
    observed = {}

    @contextmanager
    def tracking_write_lock(conn=None):
        lock_depth[0] += 1
        try:
            yield
        finally:
            lock_depth[0] -= 1

    class TrackingSnapshotConnection:
        """Wrap the read-only snapshot connection to observe the copy."""

        def __init__(self, real):
            self._real = real

        def backup(self, target):
            observed["copy_under_lock"] = lock_depth[0] > 0
            return self._real.backup(target)

        def close(self):
            self._real.close()

    def tracked_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        if kwargs.get("uri"):
            return TrackingSnapshotConnection(conn)
        return conn

    monkeypatch.setattr(export_module.sqlite3, "connect", tracked_connect)
    monkeypatch.setattr(export_module, "db_write_lock", tracking_write_lock)

    service._snapshot_database(session.root, destination)

    assert observed.get("copy_under_lock") is False
    check = sqlite3.connect(str(destination))
    try:
        assert check.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        check.close()


def test_quick_check_connection_uses_enlarged_page_cache(tmp_path):
    connection = sqlite3.connect(str(tmp_path / "check.db"))
    try:
        LibraryExportService._configure_quick_check_connection(connection)
        assert LibraryExportService._QUICK_CHECK_CACHE_KIB == 32 * 1024
        assert (
            connection.execute("PRAGMA cache_size").fetchone()[0]
            == -LibraryExportService._QUICK_CHECK_CACHE_KIB
        )
        assert connection.execute("PRAGMA query_only").fetchone()[0] == 1
        assert connection.execute("PRAGMA temp_store").fetchone()[0] == 1  # FILE
        assert connection.execute("PRAGMA mmap_size").fetchone()[0] == 0
    finally:
        connection.close()


def test_quick_check_database_file_passes_healthy_database(tmp_path):
    database = tmp_path / "check.db"
    connection = sqlite3.connect(str(database))
    try:
        connection.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, payload TEXT)")
        connection.execute("INSERT INTO t VALUES (1, 'hello')")
        connection.commit()
    finally:
        connection.close()

    # Must not raise: the full scan reports "ok".
    LibraryExportService._quick_check_database_file(database)


def test_quick_check_database_file_detects_deep_corruption(tmp_path):
    database = tmp_path / "check.db"
    connection = sqlite3.connect(str(database))
    try:
        connection.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, payload TEXT)")
        for index in range(2000):
            connection.execute("INSERT INTO t VALUES (?, ?)", (index, "y" * 200))
        connection.commit()
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
    finally:
        connection.close()

    # Corrupt a page deep in the file - far away from the header - to prove
    # the scan still covers the whole database (full quick_check, not a
    # header-only check).
    with open(database, "r+b") as handle:
        handle.seek(page_size * 100)
        handle.write(b"\x00" * 512)

    with pytest.raises((ValueError, sqlite3.DatabaseError)):
        LibraryExportService._quick_check_database_file(database)
