import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from AssetsManager.application import ApplicationBootstrap
from AssetsManager.application.context import LibrarySession
from AssetsManager.application.library_service import LibraryService
from AssetsManager.application.runtime import LibraryRuntime


def test_runtime_is_cached_for_exact_session_and_services(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")

    first = bootstrap.runtime_for(session)
    second = bootstrap.runtime_for(session)

    assert isinstance(first, LibraryRuntime)
    assert first is second
    assert first.session is session
    assert first.services is second.services
    assert first.services_snapshot is first.services
    assert second.services_snapshot is second.services
    assert bootstrap.runtime_for(session).services is first.services


def test_runtime_reuses_one_sharing_bundle_for_same_session(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")

    first = bootstrap.runtime_for(session)
    second = bootstrap.runtime_for(session)

    assert first.sharing_services is first.services.sharing_services
    assert first.sharing_services is second.sharing_services
    assert first.sharing_services.auth_service is second.sharing_services.auth_service
    assert first.sharing_services.share_service is second.sharing_services.share_service


def test_runtime_sharing_bundles_are_isolated_between_libraries(tmp_path):
    bootstrap = ApplicationBootstrap()
    first_session = bootstrap.library_service.open_session(tmp_path / "first")
    second_session = bootstrap.library_service.open_session(tmp_path / "second")

    first = bootstrap.runtime_for(first_session).sharing_services
    second = bootstrap.runtime_for(second_session).sharing_services

    assert first is not second
    assert first.token_secret != second.token_secret
    assert first.auth_service._conn is not second.auth_service._conn
    assert first.share_service._conn is not second.share_service._conn


def test_runtime_rejects_foreign_and_stale_sessions(tmp_path):
    root = tmp_path / "library"
    foreign_service = LibraryService()
    foreign = foreign_service.open_session(root)
    bootstrap = ApplicationBootstrap()
    with pytest.raises(ValueError):
        bootstrap.runtime_for(foreign)
    with pytest.raises(RuntimeError, match="owned by another LibraryService"):
        bootstrap.library_service.open_session(root)

    foreign_service.close_session(foreign)
    stale = bootstrap.library_service.open_session(root)
    stale.close()
    current = bootstrap.library_service.open_session(root)
    with pytest.raises(ValueError):
        bootstrap.runtime_for(stale)
    assert bootstrap.runtime_for(current).session is current
    bootstrap.library_service.close_session(current)


def test_same_root_reopen_gets_new_runtime_epoch(tmp_path):
    root = tmp_path / "library"
    bootstrap = ApplicationBootstrap()
    old_session = bootstrap.library_service.open_session(root)
    old = bootstrap.runtime_for(old_session)
    old_session.close()
    new_session = bootstrap.library_service.open_session(root)
    new = bootstrap.runtime_for(new_session)

    assert new is not old
    assert new.epoch != old.epoch


def test_runtime_revision_is_monotonic(tmp_path):
    bootstrap = ApplicationBootstrap()
    runtime = bootstrap.runtime_for(bootstrap.library_service.open_session(tmp_path / "library"))
    assert runtime.revision == 0
    assert runtime.next_revision() == 1
    assert runtime.next_revision() == 2
    assert runtime.revision == 2


def test_runtime_close_is_idempotent_and_cleans_owned_undo_once(tmp_path, monkeypatch):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    calls = []
    monkeypatch.setattr(runtime.services.undo_service, "cleanup", lambda: calls.append("cleanup"))

    runtime.close()
    runtime.close()

    assert calls == ["cleanup"]
    assert session.is_closed is False


def test_runtime_close_stops_registered_lifecycle_adapters(tmp_path, monkeypatch):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    adapter = SimpleNamespace(stop=Mock())
    runtime.register_lifecycle_adapter(adapter)
    monkeypatch.setattr(runtime.services.undo_service, "cleanup", lambda: None)

    runtime.close()

    adapter.stop.assert_called_once_with()


def test_register_lifecycle_adapter_during_close_stops_adapter_synchronously(tmp_path, monkeypatch):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    entered = threading.Event()
    release = threading.Event()

    def first_stop():
        entered.set()
        assert release.wait(5)

    first_adapter = SimpleNamespace(stop=first_stop)
    late_adapter = SimpleNamespace(stop=Mock())
    runtime.register_lifecycle_adapter(first_adapter)
    monkeypatch.setattr(runtime.services.undo_service, "cleanup", lambda: None)

    closer = threading.Thread(target=runtime.close)
    closer.start()
    try:
        assert entered.wait(5)
        runtime.register_lifecycle_adapter(late_adapter)
        late_adapter.stop.assert_called_once_with()
    finally:
        release.set()
        closer.join(5)

    assert not closer.is_alive()
    assert runtime._state == "closed"
    assert late_adapter not in runtime._lifecycle_adapters


def test_runtime_retries_lifecycle_adapter_cleanup_after_failure(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    calls = []

    def flaky_stop():
        calls.append("stop")
        if len(calls) == 1:
            raise RuntimeError("adapter stop failed")

    adapter = SimpleNamespace(stop=flaky_stop)
    runtime.register_lifecycle_adapter(adapter)

    with pytest.raises(RuntimeError, match="adapter stop failed"):
        runtime.close()
    runtime.close()

    assert calls == ["stop", "stop"]


def test_runtime_restores_state_after_system_exit_from_adapter_stop(tmp_path, monkeypatch):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    stop_calls = []
    undo_calls = []

    def flaky_stop():
        stop_calls.append("stop")
        if len(stop_calls) == 1:
            raise SystemExit("adapter failed")

    adapter = SimpleNamespace(stop=flaky_stop)
    runtime.register_lifecycle_adapter(adapter)
    monkeypatch.setattr(
        runtime.services.undo_service,
        "cleanup",
        lambda: undo_calls.append("cleanup"),
    )

    with pytest.raises(SystemExit, match="adapter failed"):
        runtime.close()

    assert runtime._state == "failed"
    assert runtime._cleanup_in_progress is False
    runtime.close()

    assert stop_calls == ["stop", "stop"]
    assert undo_calls == ["cleanup"]


def test_runtime_restores_state_after_system_exit_from_undo_cleanup(tmp_path, monkeypatch):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    stop_calls = []
    undo_calls = []

    def stop():
        stop_calls.append("stop")

    def flaky_cleanup():
        undo_calls.append("cleanup")
        if len(undo_calls) == 1:
            raise SystemExit("undo failed")

    runtime.register_lifecycle_adapter(SimpleNamespace(stop=stop))
    monkeypatch.setattr(runtime.services.undo_service, "cleanup", flaky_cleanup)

    with pytest.raises(SystemExit, match="undo failed"):
        runtime.close()

    assert runtime._state == "failed"
    assert runtime._cleanup_in_progress is False
    runtime.close()

    assert stop_calls == ["stop", "stop"]
    assert undo_calls == ["cleanup", "cleanup"]


def test_runtime_cleanup_waits_until_active_lease_finishes(tmp_path, monkeypatch):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    entered = threading.Event()
    closing_started = threading.Event()
    release = threading.Event()
    cleanup_seen = []

    def leased_operation():
        with session.operation():
            entered.set()
            assert runtime.services.undo_service.can_undo() is False
            assert release.wait(5)
            # The runtime-owned service remains usable for an existing lease.
            assert runtime.services.undo_service.can_undo() is False

    monkeypatch.setattr(
        runtime.services.undo_service,
        "cleanup",
        lambda: cleanup_seen.append("cleanup"),
    )
    worker = threading.Thread(target=leased_operation)
    worker.start()
    assert entered.wait(5)

    bootstrap.library_service.add_session_closing_listener(
        lambda current_session: closing_started.set()
    )
    closer = threading.Thread(target=session.close)
    closer.start()
    assert closing_started.wait(5)
    assert session.is_closed
    assert cleanup_seen == []
    release.set()
    worker.join(5)
    closer.join(5)

    assert cleanup_seen == ["cleanup"]


def test_runtime_for_concurrent_calls_returns_exact_singleton(tmp_path, monkeypatch):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    original_build = bootstrap._build_services
    entered = threading.Event()
    release = threading.Event()
    runtimes = []

    def concurrent_build(current_session):
        entered.set()
        assert release.wait(5)
        return original_build(current_session)

    monkeypatch.setattr(bootstrap, "_build_services", concurrent_build)
    workers = [threading.Thread(target=lambda: runtimes.append(bootstrap.runtime_for(session))) for _ in range(2)]
    for worker in workers:
        worker.start()
    assert entered.wait(5)
    release.set()
    for worker in workers:
        worker.join(5)

    assert len(runtimes) == 2
    assert runtimes[0] is runtimes[1]


def test_runtime_for_rejects_session_closed_during_creation_and_cleans_temp_runtime(
    tmp_path, monkeypatch
):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    entered = threading.Event()
    release = threading.Event()
    cleanup_calls = []

    def blocked_build(_session):
        entered.set()
        assert release.wait(5)
        return SimpleNamespace(
            undo_service=SimpleNamespace(cleanup=lambda: cleanup_calls.append("cleanup"))
        )

    monkeypatch.setattr(bootstrap, "_build_services", blocked_build)
    result = []
    errors = []

    def create_runtime():
        try:
            result.append(bootstrap.runtime_for(session))
        except Exception as exc:  # noqa: BLE001 - capture worker failure
            errors.append(exc)

    creator = threading.Thread(target=create_runtime)
    creator.start()
    assert entered.wait(5)

    closer = threading.Thread(target=session.close)
    closer.start()
    closer.join(5)
    assert not closer.is_alive()
    assert session.is_closed

    release.set()
    creator.join(5)

    assert not result
    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)
    assert bootstrap._runtimes == {}
    assert cleanup_calls == ["cleanup"]


def test_runtime_cleanup_failure_can_retry_on_second_close(tmp_path, monkeypatch):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    calls = []

    def flaky_cleanup():
        calls.append("cleanup")
        if len(calls) == 1:
            raise RuntimeError("cleanup failed")

    monkeypatch.setattr(runtime.services.undo_service, "cleanup", flaky_cleanup)

    with pytest.raises(RuntimeError, match="cleanup failed"):
        runtime.close()
    assert calls == ["cleanup"]
    assert runtime._state == "failed"

    runtime.close()
    runtime.close()
    assert calls == ["cleanup", "cleanup"]


def test_lifecycle_notifies_closing_before_drain_and_closed_before_db_close(tmp_path, monkeypatch):
    bootstrap = ApplicationBootstrap()
    service = bootstrap.library_service
    session = service.open_session(tmp_path / "library")
    events = []
    entered = threading.Event()
    closing_started = threading.Event()
    release = threading.Event()

    def closing(closing_session):
        events.append("closing")
        closing_started.set()
        assert closing_session is session
        with pytest.raises(RuntimeError, match="closed"):
            with session.operation():
                pass

    def closed(closed_session):
        events.append("closed")
        assert closed_session is session
        assert not entered.is_set() or release.is_set()
        assert events == ["closing", "closed"]

    service.add_session_closing_listener(closing)
    service.add_session_close_listener(closed)
    original_close_library = service._db.close_library
    monkeypatch.setattr(service._db, "close_library", lambda root: (events.append("db"), original_close_library(root))[1])

    def leased():
        with session.operation():
            entered.set()
            release.wait(5)

    worker = threading.Thread(target=leased)
    worker.start()
    assert entered.wait(5)
    closer = threading.Thread(target=session.close)
    closer.start()
    assert closing_started.wait(5)
    assert session.is_closed
    assert events == ["closing"]
    release.set()
    worker.join(5)
    closer.join(5)
    assert events == ["closing", "closed", "db"]


def test_session_close_stops_runtime_adapter_before_drain_and_cache_release(
    tmp_path, monkeypatch
):
    bootstrap = ApplicationBootstrap()
    service = bootstrap.library_service
    session = service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    events = []
    adapter_observations = []
    lease_entered = threading.Event()
    release_lease = threading.Event()
    lease_exited = threading.Event()
    finish_started = threading.Event()
    original_finish = LibrarySession._finish_close
    original_close_library = service._db.close_library

    def tracked_finish(current):
        events.append("finish")
        finish_started.set()
        original_finish(current)

    def tracked_close_library(root):
        events.append("db")
        return original_close_library(root)

    def leased_operation():
        with session.operation():
            lease_entered.set()
            assert release_lease.wait(5)
        lease_exited.set()

    def stop_adapter():
        events.append("adapter")
        adapter_observations.append(
            (
                service.current_session is session,
                session.context.db_conn.execute("SELECT 1").fetchone(),
                not lease_exited.is_set(),
            )
        )

    monkeypatch.setattr(LibrarySession, "_finish_close", tracked_finish)
    monkeypatch.setattr(service._db, "close_library", tracked_close_library)
    runtime.register_lifecycle_adapter(SimpleNamespace(stop=stop_adapter))
    worker = threading.Thread(target=leased_operation)
    closer = threading.Thread(target=session.close)
    worker.start()
    assert lease_entered.wait(5)
    closer.start()
    try:
        assert finish_started.wait(5)
    finally:
        release_lease.set()
        worker.join(5)
        closer.join(5)

    assert not worker.is_alive()
    assert not closer.is_alive()
    assert events == ["adapter", "finish", "db"]
    assert adapter_observations == [(True, (1,), True)]


def test_close_session_retains_runtime_and_database_after_adapter_stop_failure(
    tmp_path, monkeypatch
):
    bootstrap = ApplicationBootstrap()
    service = bootstrap.library_service
    session = service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    stop_calls = []
    db_close_calls = []
    original_close_library = service._db.close_library

    def stop_adapter():
        stop_calls.append("stop")
        if len(stop_calls) == 1:
            raise RuntimeError("adapter stop failed")

    def tracked_close_library(root):
        db_close_calls.append(root)
        return original_close_library(root)

    monkeypatch.setattr(service._db, "close_library", tracked_close_library)
    runtime.register_lifecycle_adapter(SimpleNamespace(stop=stop_adapter))

    with pytest.raises(RuntimeError, match="adapter stop failed"):
        service.close_session(session)

    assert stop_calls == ["stop"]
    assert db_close_calls == []
    assert bootstrap._runtimes[id(session)] is runtime
    assert service.current_session is session
    assert session.context.db_conn.execute("SELECT 1").fetchone() == (1,)

    service.close_session(session)

    assert stop_calls == ["stop", "stop"]
    assert db_close_calls == [session.context.root_identity]
    assert id(session) not in bootstrap._runtimes
    assert service.current_session is None


def test_close_session_retains_runtime_and_database_after_postclose_failure(
    tmp_path, monkeypatch
):
    bootstrap = ApplicationBootstrap()
    service = bootstrap.library_service
    session = service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    cleanup_calls = []
    connection = session.connection_for(session.root)

    def flaky_cleanup():
        cleanup_calls.append("cleanup")
        if len(cleanup_calls) == 1:
            raise RuntimeError("undo cleanup failed")

    monkeypatch.setattr(runtime.services.undo_service, "cleanup", flaky_cleanup)

    with pytest.raises(RuntimeError, match="undo cleanup failed"):
        service.close_session(session)

    assert service.current_session is session
    assert bootstrap._runtimes[id(session)] is runtime
    assert connection.execute("SELECT 1").fetchone() == (1,)

    service.close_session(session)

    assert cleanup_calls == ["cleanup", "cleanup"]
    assert service.current_session is None
    assert id(session) not in bootstrap._runtimes
    with pytest.raises(Exception):
        connection.execute("SELECT 1")


def test_runtime_close_adapters_serializes_with_full_runtime_close(tmp_path, monkeypatch):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    stop_entered = threading.Event()
    release_stop = threading.Event()
    stop_calls = []

    def stop_adapter():
        stop_calls.append(threading.get_ident())
        if len(stop_calls) == 1:
            stop_entered.set()
        assert release_stop.wait(5)

    runtime.register_lifecycle_adapter(SimpleNamespace(stop=stop_adapter))
    monkeypatch.setattr(runtime.services.undo_service, "cleanup", lambda: None)
    closer = threading.Thread(target=runtime.close)
    precloser = threading.Thread(target=runtime.close_adapters)
    closer.start()
    assert stop_entered.wait(5)
    precloser.start()
    release_stop.set()
    closer.join(5)
    precloser.join(5)

    assert not closer.is_alive()
    assert not precloser.is_alive()
    assert stop_calls == [closer.ident]


def test_concurrent_session_close_runs_runtime_and_database_teardown_once(tmp_path):
    bootstrap = ApplicationBootstrap()
    service = bootstrap.library_service
    session = service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    adapter_entered = threading.Event()
    release_adapter = threading.Event()
    second_started = threading.Event()
    second_done = threading.Event()
    close_calls = []
    stop_calls = []
    original_close_library = service._db.close_library

    def stop_adapter():
        stop_calls.append("stop")
        adapter_entered.set()
        assert release_adapter.wait(5)

    def close_library(root):
        close_calls.append(root)
        return original_close_library(root)

    service._db.close_library = close_library
    runtime.register_lifecycle_adapter(SimpleNamespace(stop=stop_adapter))
    first = threading.Thread(target=session.close)
    second = threading.Thread(
        target=lambda: (second_started.set(), session.close(), second_done.set())
    )
    first.start()
    assert adapter_entered.wait(5)
    second.start()
    assert second_started.wait(5)
    assert not second_done.is_set()
    release_adapter.set()
    first.join(5)
    second.join(5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert stop_calls == ["stop"]
    assert close_calls == [session.context.root_identity]


def test_successful_session_close_does_not_replay_preclose_listeners(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    preclose_calls = []
    bootstrap.library_service.add_session_closing_listener(preclose_calls.append)

    session.close()
    session.close()

    assert preclose_calls == [session]


def test_runtime_snapshot_exposes_session_bound_maintenance_service_per_library(tmp_path):
    bootstrap = ApplicationBootstrap()
    first_session = bootstrap.library_service.open_session(tmp_path / "first")
    second_session = bootstrap.library_service.open_session(tmp_path / "second")

    first_runtime = bootstrap.runtime_for(first_session)
    second_runtime = bootstrap.runtime_for(second_session)
    first_service = first_runtime.services_snapshot.maintenance_service
    second_service = second_runtime.services_snapshot.maintenance_service

    assert first_service is first_runtime.services.maintenance_service
    assert first_service._session is first_session
    assert second_service._session is second_session
    assert first_service is not second_service

    bootstrap.library_service.close()


def test_runtime_close_stops_maintenance_service_and_keeps_vacuum_unsupported(
    tmp_path, monkeypatch
):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    integrity = runtime.services.integrity_service
    maintenance = runtime.services.maintenance_service
    close_order = []
    original_integrity_stop = integrity.stop
    original_maintenance_stop = maintenance.stop

    def tracked_integrity_stop():
        close_order.append("integrity")
        original_integrity_stop()

    def tracked_maintenance_stop():
        close_order.append("maintenance")
        original_maintenance_stop()

    monkeypatch.setattr(integrity, "stop", tracked_integrity_stop)
    monkeypatch.setattr(maintenance, "stop", tracked_maintenance_stop)
    monkeypatch.setattr(
        runtime.services.undo_service,
        "cleanup",
        lambda: close_order.append("undo"),
    )
    vacuum = maintenance.vacuum()

    runtime.close()
    runtime.close()

    assert close_order == ["integrity", "maintenance", "undo"]
    assert not maintenance.running
    with pytest.raises(RuntimeError, match="maintenance service is closed"):
        maintenance.schedule("checkpoint")
    assert not vacuum.supported
    assert not vacuum.success


def test_session_close_retries_failed_maintenance_stop_without_leaking_runtime(
    tmp_path, monkeypatch
):
    bootstrap = ApplicationBootstrap()
    service = bootstrap.library_service
    session = service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    maintenance = runtime.services.maintenance_service
    original_stop = maintenance.stop
    stop_calls = []

    def flaky_stop():
        stop_calls.append("stop")
        if len(stop_calls) == 1:
            raise RuntimeError("maintenance stop failed")
        original_stop()

    monkeypatch.setattr(maintenance, "stop", flaky_stop)

    with pytest.raises(RuntimeError, match="maintenance stop failed"):
        service.close_session(session)

    assert bootstrap._runtimes[id(session)] is runtime
    assert service.current_session is session
    assert session.context.db_conn.execute("SELECT 1").fetchone() == (1,)

    service.close_session(session)

    assert stop_calls == ["stop", "stop"]
    assert id(session) not in bootstrap._runtimes
    assert service.current_session is None
    with pytest.raises(RuntimeError, match="closed LibrarySession"):
        maintenance.schedule("checkpoint")


def test_runtime_cache_rejects_closing_runtime_and_next_revision(tmp_path):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)

    runtime.mark_closing()
    with pytest.raises(RuntimeError, match="closing or closed"):
        runtime.next_revision()
    with pytest.raises(RuntimeError, match="closing or closed"):
        bootstrap.runtime_for(session)

    runtime.close()
    with pytest.raises(RuntimeError, match="closing or closed"):
        runtime.next_revision()


def test_reconciliation_worker_is_stopped_with_library_runtime(tmp_path):
    from AssetsManager.application import ApplicationBootstrap

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    service = runtime.services.reconciliation_service

    assert service is not None
    assert service.is_running

    bootstrap.library_service.close()

    assert not service.is_running
