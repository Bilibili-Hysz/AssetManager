"""Regression tests for runtime lifecycle and event-routing defects.

Covers the low-batch fixes:
- Bug 1: a failed close must keep the runtime closed (no half-open state).
- Bug 3: next_revision() failures must not bubble out of event dispatch.
- Bug 4: a single unnormalizable path must not drop the whole event.
- Bug 5: _RouterSubscription.close() must time out instead of blocking forever.
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from AssetsManager.application import ApplicationBootstrap
from AssetsManager.application.runtime_events import RuntimeEventRouter
from AssetsManager.domain.event_bus import EventBus
from AssetsManager.domain.events import FileSystemChanged, TagCatalogChanged


def _runtime(tmp_path, bus):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    runtime.event_router.close()
    runtime.event_router = RuntimeEventRouter(runtime, event_bus=bus)
    return bootstrap, session, runtime


def _identity(session, **kwargs):
    return {"library_root": session.root_str, "session_token": session.event_token, **kwargs}


def test_close_failure_keeps_closed_semantics_and_disables_event_routing(tmp_path):
    """Bug 1: a failed close must not leave the runtime half-open."""
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    stop_calls = []

    def flaky_stop():
        stop_calls.append("stop")
        if len(stop_calls) == 1:
            raise RuntimeError("adapter stop failed")

    runtime.register_lifecycle_adapter(SimpleNamespace(stop=flaky_stop))
    router = runtime.event_router

    with pytest.raises(RuntimeError, match="adapter stop failed"):
        runtime.close()

    # The runtime must not roll back to "open": no new work, no revisions,
    # and the event router must stay closed so event routing is unavailable.
    assert runtime._state == "failed"
    assert runtime.is_open is False
    assert router.closed
    with pytest.raises(RuntimeError, match="closing or closed"):
        runtime.next_revision()

    # A retry can still complete the close.
    runtime.close()
    assert runtime._state == "closed"


def test_dispatch_event_swallows_revision_failure_after_close(tmp_path):
    """Bug 3: next_revision() raising (closed runtime) must not bubble up."""
    bus = EventBus()
    bootstrap, session, runtime = _runtime(tmp_path, bus)
    received = []
    runtime.event_router.subscribe(received.append)
    try:
        runtime.close()

        # Direct dispatch: next_revision() raises because the runtime is
        # closed; the router must swallow it instead of letting the
        # exception escape to the event bus.
        runtime.event_router._dispatch_event(FileSystemChanged(
            **_identity(session, paths=("a.txt",), old_paths=()),
        ))

        assert received == []
        assert runtime.revision == 0
    finally:
        runtime.close()
        bootstrap.library_service.close()


def test_paths_for_keeps_valid_paths_when_one_path_fails(tmp_path):
    """Bug 4: one unnormalizable path must not drop the whole event."""
    bus = EventBus()
    bootstrap, session, runtime = _runtime(tmp_path, bus)
    received = []
    runtime.event_router.subscribe(received.append)
    try:
        bus.publish(FileSystemChanged(**_identity(
            session,
            paths=(str(tmp_path / "library" / "good.txt"), 12345, "../escape"),
            old_paths=(),
        )))
        assert len(received) == 1
        assert received[0].paths == ("good.txt",)
        assert received[0].revision == 1

        # An event whose paths all fail to normalize is still dropped.
        bus.publish(FileSystemChanged(**_identity(
            session, paths=("../escape",), old_paths=(),
        )))
        assert len(received) == 1
        assert runtime.revision == 1
    finally:
        runtime.close()
        bootstrap.library_service.close()


def test_subscription_close_times_out_when_callback_hangs(tmp_path):
    """Bug 5: close() must time out instead of blocking forever."""
    bus = EventBus()
    bootstrap, session, runtime = _runtime(tmp_path, bus)
    handler_entered = threading.Event()
    release_handler = threading.Event()
    calls = []

    def handler(_event):
        calls.append("handler")
        handler_entered.set()
        assert release_handler.wait(timeout=5)

    subscription = runtime.event_router.subscribe(handler)
    publish_thread = threading.Thread(
        target=bus.publish,
        args=(TagCatalogChanged(**_identity(session)),),
    )
    try:
        publish_thread.start()
        assert handler_entered.wait(timeout=5)

        start = time.monotonic()
        subscription.close()
        elapsed = time.monotonic() - start

        # close() gave up on the in-flight callback and returned.
        assert not release_handler.is_set()
        assert calls == ["handler"]
        assert elapsed >= 1.5
        assert elapsed < 5
    finally:
        release_handler.set()
        publish_thread.join(timeout=5)
        runtime.close()
        bootstrap.library_service.close()
