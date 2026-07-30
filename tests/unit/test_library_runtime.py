import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from AssetsManager.application import ApplicationBootstrap
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
    assert bootstrap.for_library(session) is first.services


def test_runtime_rejects_foreign_and_stale_sessions(tmp_path):
    root = tmp_path / "library"
    foreign = LibraryService().open_session(root)
    bootstrap = ApplicationBootstrap()
    with pytest.raises(ValueError):
        bootstrap.runtime_for(foreign)

    stale = bootstrap.library_service.open_session(root)
    stale.close()
    current = bootstrap.library_service.open_session(root)
    with pytest.raises(ValueError):
        bootstrap.runtime_for(stale)
    assert bootstrap.runtime_for(current).session is current


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

    assert runtime._state == "open"
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

    assert runtime._state == "open"
    assert runtime._cleanup_in_progress is False
    runtime.close()

    assert stop_calls == ["stop", "stop"]
    assert undo_calls == ["cleanup", "cleanup"]


def test_runtime_cleanup_waits_until_active_lease_finishes(tmp_path, monkeypatch):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    entered = threading.Event()
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

    closer = threading.Thread(target=session.close)
    closer.start()
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
    assert runtime.next_revision() == 1

    runtime.close()
    runtime.close()
    assert calls == ["cleanup", "cleanup"]


def test_lifecycle_notifies_closing_before_drain_and_closed_before_db_close(tmp_path, monkeypatch):
    bootstrap = ApplicationBootstrap()
    service = bootstrap.library_service
    session = service.open_session(tmp_path / "library")
    events = []
    entered = threading.Event()
    release = threading.Event()

    def closing(closing_session):
        events.append("closing")
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
    assert session.is_closed
    assert events == ["closing"]
    release.set()
    worker.join(5)
    closer.join(5)
    assert events == ["closing", "closed", "db"]
