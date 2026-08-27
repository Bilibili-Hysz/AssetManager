"""Regression tests for the low-batch bootstrap/session fixes.

Covers three defects:

* Bug 10: the legacy marker migration must read the JSON marker strictly
  read-only; constructing a ``ReconciliationQueue`` rewrites the marker when
  an expired running lease is recovered.
* Bug 11: ``_LanServicesHolder.get`` and ``_publish_while_live`` must not
  nest locks in opposite orders (holder -> session vs session -> holder).
* Bug 25: ``discover_plugins`` must report per-plugin failures instead of
  swallowing them and dropping an otherwise usable plugin service.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

import pytest

from AssetsManager.application import (
    ReconciliationMarkerMigrationError,
    ReconciliationMarkerMigrationStatus,
    SQLiteReconciliationQueueStore,
    migrate_reconciliation_marker,
)
from AssetsManager.application.bootstrap import (
    ApplicationBootstrap,
    LanRuntimeServices,
    _LanServicesHolder,
)
from AssetsManager.application.context import LibraryContext, LibrarySession
from AssetsManager.application.plugin_service import PluginService
from AssetsManager.core.plugins import PluginLoadResult


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


def _store(tmp_path: Path):
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


def _expired_running_marker(tmp_path: Path) -> Path:
    """Write a v2 marker whose single task is RUNNING with an expired lease.

    Loading this marker through ``ReconciliationQueue`` recovers the expired
    lease and rewrites the marker — the side effect Bug 10 eliminates.
    """
    marker = tmp_path / "reconciliation-queue.json"
    root = str(tmp_path / "library")
    payload = {
        "version": 2,
        "clock": "wallclock-deadlines",
        "library_root": root,
        "tasks": [
            {
                "task_id": "legacy-stuck-running",
                "library_root": root,
                "path": root,
                "kind": "asset_index_root_rescan",
                "reason": "busy",
                "state": "running",
                "attempts": 1,
                "next_attempt_at_wallclock": 100.0,
                "operation_ids": ["legacy-op"],
                "last_error_type": None,
                "last_error": None,
                "expected_revision": None,
                "observed_revision": None,
                "created_at": 0.0,
                "updated_at": 5.0,
                "lease_expires_at_wallclock": 50.0,
                "lease_token": "lease-1",
                "max_attempts": 5,
            }
        ],
    }
    marker.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return marker


# ── Bug 10: marker migration read must not persist ────────────────


def test_legacy_marker_read_does_not_rewrite_marker_when_publish_fails(tmp_path):
    """A failed migration must leave the marker byte-identical.

    The marker holds an expired RUNNING task: the pre-fix implementation
    rewrote it during the "read" (constructor lease recovery), so this
    assertion fails on the old code even though the migration itself aborted.
    """
    connection, store = _store(tmp_path)
    try:
        marker = _expired_running_marker(tmp_path)
        original_bytes = marker.read_bytes()

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
        assert marker.read_bytes() == original_bytes
    finally:
        connection.close()


def test_legacy_marker_read_imports_raw_snapshot_and_archives_original_bytes(tmp_path):
    """The import path retires the marker exactly as it was read.

    The archived marker must equal the original bytes (no constructor
    rewrite), and the imported task must still be raw RUNNING: lease
    recovery is deferred to the durable queue, not performed during read.
    """
    connection, store = _store(tmp_path)
    try:
        marker = _expired_running_marker(tmp_path)
        original_bytes = marker.read_bytes()
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
        assert result.archive_path.read_bytes() == original_bytes
        imported = store.load()
        assert len(imported) == 1
        assert imported[0].task_id == "legacy-stuck-running"
        assert imported[0].state == "running"
    finally:
        connection.close()


# ── Bug 11: LAN holder / session lock order ───────────────────────


class _StoreStub:
    def _bind_liveness(self, token):
        self._liveness_token = token


def _real_session(tmp_path: Path) -> LibrarySession:
    """Assemble a real LibrarySession without the full bootstrap stack."""
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    context = LibraryContext(
        root=tmp_path,
        data_dir=tmp_path,
        thumb_dir=tmp_path,
        db_conn=connection,
        tag_store=_StoreStub(),
        project_data=_StoreStub(),
    )
    return LibrarySession(context=context)


def _ready_holder(session: LibrarySession):
    holder = _LanServicesHolder(
        session,
        lambda _session: LanRuntimeServices(
            asset_service=object(),
            project_service=object(),
            search_service=object(),
        ),
    )
    return holder, holder.get()


def test_lan_holder_ready_get_checks_liveness_outside_holder_lock(
    tmp_path, monkeypatch
):
    """Deterministic lock-order check for the ready read path.

    ``is_closed`` is instrumented to detect whether the holder condition is
    held while the session lifecycle condition is acquired. The pre-fix
    implementation nested holder -> session here, which inverts the
    session -> holder order used by ``_publish_while_live`` -> ``_publish``.
    """
    session = _real_session(tmp_path)
    holder, _value = _ready_holder(session)
    holder_locked_while_checking = threading.Event()

    original_is_closed = LibrarySession.is_closed

    def instrumented_liveness(self):
        if holder._condition.acquire(blocking=False):
            holder._condition.release()
        else:
            holder_locked_while_checking.set()
        return original_is_closed.__get__(self, type(self))

    monkeypatch.setattr(LibrarySession, "is_closed", property(instrumented_liveness))
    holder.get()
    assert not holder_locked_while_checking.is_set()


def test_lan_holder_get_and_publish_while_live_no_deadlock(tmp_path):
    """Concurrent get() and publication must complete within a bounded time.

    One thread repeatedly reads the ready projection while the other runs the
    session -> holder publication path. With the unified lock order neither
    thread can wait for the other's lock; a deadlock here fails the join
    timeout instead of hanging the suite (daemon threads).
    """
    session = _real_session(tmp_path)
    holder, value = _ready_holder(session)
    iterations = 300
    errors: list[BaseException] = []

    def publisher():
        def publish_with_holder_lock():
            with holder._condition:
                return None

        try:
            for _ in range(iterations):
                with session.operation():
                    session._publish_while_live(publish_with_holder_lock)
        except BaseException as exc:  # pragma: no cover - failure path
            errors.append(exc)

    def reader():
        try:
            for _ in range(iterations):
                assert holder.get() is value
        except BaseException as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [
        threading.Thread(target=publisher, daemon=True),
        threading.Thread(target=reader, daemon=True),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert not errors, errors
    assert not any(thread.is_alive() for thread in threads), (
        "LAN holder lock-order deadlock between get() and _publish_while_live"
    )


# ── Bug 25: plugin discovery failure reporting ────────────────────


class _FakePluginService:
    def __init__(self):
        self.discover_descriptors: list = []
        self.load_results: list[PluginLoadResult] = []
        self.discover_error: BaseException | None = None
        self.load_error: BaseException | None = None

    def discover(self, search_paths=None):
        if self.discover_error is not None:
            raise self.discover_error
        return self.discover_descriptors

    def load_all_enabled(self, host_context=None):
        if self.load_error is not None:
            raise self.load_error
        return self.load_results


class _Descriptor:
    def __init__(self, plugin_id: str):
        self.id = plugin_id


def _bootstrap_with_fake_service() -> tuple[ApplicationBootstrap, _FakePluginService]:
    bootstrap = ApplicationBootstrap()
    fake = _FakePluginService()
    bootstrap.container.register(PluginService, instance=fake)
    return bootstrap, fake


def test_plugin_load_failures_initially_empty():
    bootstrap = ApplicationBootstrap()
    assert bootstrap.plugin_load_failures == ()


def test_discover_plugins_records_per_plugin_failure_but_keeps_service():
    bootstrap, fake = _bootstrap_with_fake_service()
    fake.discover_descriptors = [_Descriptor("good"), _Descriptor("broken")]
    fake.load_results = [
        PluginLoadResult(ok=True, plugin_id="good", state="active"),
        PluginLoadResult(ok=False, plugin_id="broken", state="error"),
    ]
    result = bootstrap.discover_plugins()
    assert result == fake.discover_descriptors
    assert bootstrap.plugin_service is fake
    assert bootstrap.plugin_host_context is not None
    assert "broken" in bootstrap.plugin_load_failures
    assert "good" not in bootstrap.plugin_load_failures


def test_discover_plugins_keeps_service_when_discovery_raises():
    bootstrap, fake = _bootstrap_with_fake_service()
    fake.discover_error = RuntimeError("plugin directory unreadable")
    assert bootstrap.discover_plugins() == []
    # The service itself resolved fine; only the discovery pass failed.
    assert bootstrap.plugin_service is fake
    assert "<discover>" in bootstrap.plugin_load_failures


def test_discover_plugins_keeps_service_when_loading_raises():
    bootstrap, fake = _bootstrap_with_fake_service()
    fake.discover_descriptors = [_Descriptor("broken")]
    fake.load_error = RuntimeError("loader crashed")
    assert bootstrap.discover_plugins() == fake.discover_descriptors
    assert bootstrap.plugin_service is fake
    assert "<load>" in bootstrap.plugin_load_failures


def test_discover_plugins_drops_service_only_when_container_unavailable(monkeypatch):
    bootstrap = ApplicationBootstrap()

    def broken_resolve(service_type):
        raise KeyError("container is unavailable")

    monkeypatch.setattr(bootstrap.container, "resolve", broken_resolve)
    assert bootstrap.discover_plugins() == []
    assert bootstrap.plugin_service is None
    assert "<resolve>" in bootstrap.plugin_load_failures
