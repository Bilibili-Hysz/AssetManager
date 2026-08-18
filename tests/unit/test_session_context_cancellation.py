"""H-D1 session-close cancellation guarantees.

The deep audit (09-deep-audit-2026-08-15.md) found that closing/switching a
library session could block the UI thread for minutes because long-running
workers (directory size computation, library stats walk) keep the session
operation lease alive while ``_finish_close`` waits unboundedly for it to
drain.

The implemented fix replaces the audit's proposed ``SessionContext``-level
``threading.Event`` with the unified worker framework in
``AssetsManager/core/workers.py`` (per-owner ``CancellationToken`` +
``BoundedPool``): panelled workers poll their token and drop the session
lease immediately, and ``LibrarySession._finish_close`` bounds the drain at
``_FINISH_CLOSE_TIMEOUT_SECONDS`` so a stuck task cannot freeze the UI.

These tests pin the three guarantees:
1. cancellation tokens are thread-safe and observed by directory walks
2. a cancelled walk returns a partial total and is never persisted as a size
3. ``_finish_close`` waits at most the configured timeout, then closes anyway
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from AssetsManager.application import context as context_module
from AssetsManager.application.context import LibraryContext, LibrarySession
from AssetsManager.core import database
from AssetsManager.core.db_migrations import migrate
from AssetsManager.core.project_data import ProjectData
from AssetsManager.core.workers import CancellationToken, TaskCancelled


# ── CancellationToken ────────────────────────────────────────────


def test_cancel_token_starts_uncancelled_and_cancel_is_sticky():
    token = CancellationToken()

    assert token.is_cancelled() is False

    token.cancel()
    token.cancel()  # idempotent

    assert token.is_cancelled() is True


def test_cancel_token_is_readable_from_another_thread():
    token = CancellationToken()
    observed: list[bool] = []

    def reader() -> None:
        token.cancel()
        observed.append(token.is_cancelled())

    thread = threading.Thread(target=reader)
    thread.start()
    thread.join(timeout=5)

    assert observed == [True]


def test_cancel_token_raise_if_cancelled():
    token = CancellationToken()
    token.cancel()

    with pytest.raises(TaskCancelled):
        token.raise_if_cancelled()


# ── compute_dir_size cooperative cancellation ────────────────────


def _populate(dir_path: Path, count: int = 500, size: int = 10) -> None:
    data = b"x" * size
    for i in range(count):
        (dir_path / f"f{i:04d}.bin").write_bytes(data)


def test_compute_dir_size_returns_partial_total_on_cancellation(tmp_path):
    dir_path = tmp_path / "tree"
    dir_path.mkdir()
    _populate(dir_path, count=500, size=10)

    flips = {"n": 0}

    def token() -> bool:
        # False on the first poll (entry 0), True on the second (entry 100).
        flips["n"] += 1
        return flips["n"] > 1

    partial = ProjectData.compute_dir_size(str(dir_path), cancel_token=token)

    # The walk stopped at the 100th entry: exactly 100 entries of 10 bytes.
    assert partial == 1000
    assert flips["n"] == 2  # early exit, not a full 500-entry scan


def test_compute_dir_size_treats_always_cancelled_as_zero(tmp_path):
    dir_path = tmp_path / "tree"
    dir_path.mkdir()
    _populate(dir_path, count=50, size=5)

    size = ProjectData.compute_dir_size(str(dir_path), cancel_token=lambda: True)

    assert size == 0


def test_compute_dir_size_without_token_walks_fully(tmp_path):
    dir_path = tmp_path / "tree"
    dir_path.mkdir()
    _populate(dir_path, count=120, size=7)

    assert ProjectData.compute_dir_size(str(dir_path)) == 120 * 7


def _project_data(lib_root: Path) -> tuple[ProjectData, sqlite3.Connection]:
    """Assemble a real ProjectData on an in-memory SQLite schema."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(database._SCHEMA)
    migrate(conn)
    return ProjectData(str(lib_root), db_conn=conn), conn


def test_get_dir_size_never_persists_cancelled_partial(tmp_path):
    dir_path = tmp_path / "tree"
    dir_path.mkdir()
    _populate(dir_path, count=300, size=4)
    pd, conn = _project_data(tmp_path)
    key = str(dir_path.resolve())

    size, cached = pd.get_dir_size(key, cancel_token=lambda: True)

    assert size == 0
    assert cached is False
    row = conn.execute(
        "SELECT cached_size FROM file_meta WHERE file_path=?",
        (key,),
    ).fetchone()
    assert row is None or row[0] is None


def test_get_dir_size_caches_when_not_cancelled(tmp_path):
    dir_path = tmp_path / "tree"
    dir_path.mkdir()
    _populate(dir_path, count=50, size=4)
    pd, conn = _project_data(tmp_path)
    key = str(dir_path.resolve())

    size, cached = pd.get_dir_size(key)

    assert size == 200
    assert cached is False
    row = conn.execute(
        "SELECT cached_size FROM file_meta WHERE file_path=?",
        (key,),
    ).fetchone()
    assert row is not None and row[0] == 200


# ── LibrarySession._finish_close bounded drain ────────────────────


def _session(tmp_path: Path) -> LibrarySession:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    context = LibraryContext(
        root=tmp_path,
        data_dir=tmp_path,
        thumb_dir=tmp_path,
        db_conn=connection,
        tag_store=SimpleNamespace(),
        project_data=SimpleNamespace(),
    )
    return LibrarySession(context=context)


def test_finish_close_times_out_with_stuck_operation(monkeypatch, tmp_path, caplog):
    # Shorten the drain bound so the test observes the timeout without
    # actually waiting 30 seconds.
    monkeypatch.setattr(context_module, "_FINISH_CLOSE_TIMEOUT_SECONDS", 0.2)
    session = _session(tmp_path)

    started = threading.Event()
    release = threading.Event()

    def stuck_holder() -> None:
        with session.operation():
            started.set()
            release.wait(5)

    holder = threading.Thread(target=stuck_holder, daemon=True)
    holder.start()
    assert started.wait(2), "worker did not acquire its session lease"

    t0 = time.monotonic()
    session.close()
    elapsed = time.monotonic() - t0

    # close() must not block on the stuck lease; the bounded drain fires and
    # the session still closes (liveness is invalidated right after).
    assert elapsed < 1.0
    assert session.is_closed
    assert "timed out" in caplog.text

    # Once fully closed, new operation leases are rejected.
    with pytest.raises(RuntimeError):
        with session.operation():
            pass

    release.set()
    holder.join(timeout=2)
    with session._operation_condition:
        assert session._active_operations == 0


def test_finish_close_waits_for_lease_within_timeout(monkeypatch, tmp_path):
    monkeypatch.setattr(context_module, "_FINISH_CLOSE_TIMEOUT_SECONDS", 2.0)
    session = _session(tmp_path)

    started = threading.Event()
    released = threading.Event()

    def short_holder() -> None:
        with session.operation():
            started.set()
            released.wait(5)

    holder = threading.Thread(target=short_holder, daemon=True)
    holder.start()
    assert started.wait(2)

    released.set()  # worker finishes well within the timeout

    t0 = time.monotonic()
    session.close()
    elapsed = time.monotonic() - t0

    holder.join(timeout=2)
    assert elapsed < 1.0
    assert session.is_closed