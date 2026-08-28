"""Task 9 tests for session-scoped runtime invalidation events."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
import threading
import pytest

from AssetsManager.application.bootstrap import ApplicationBootstrap
from AssetsManager.application.runtime_events import (
    InvalidationEvent,
    ProjectionDomain,
    RuntimeEventRouter,
)
from AssetsManager.domain.event_bus import EventBus
from AssetsManager.domain.events import (
    ActivityChanged,
    AssetNotesChanged,
    AssetTagsChanged,
    AssetUrlsChanged,
    DomainEvent,
    FavoritesChanged,
    FileSystemChanged,
    InviteChanged,
    PresenceChanged,
    SellerProfileChanged,
    ShareChanged,
    TagCatalogChanged,
    UserChanged,
)


def _runtime(tmp_path, bus):
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    runtime = bootstrap.runtime_for(session)
    runtime.event_router.close()
    runtime.event_router = RuntimeEventRouter(runtime, event_bus=bus)
    return bootstrap, session, runtime


def _identity(session, **kwargs):
    return {"library_root": session.root_str, "session_token": session.event_token, **kwargs}


def _projection_domain(name: str):
    member = getattr(ProjectionDomain, name.upper(), None)
    return member if member is not None else name


def test_model_is_frozen_and_mapping_is_exact(tmp_path):
    event = InvalidationEvent("epoch", 1, (ProjectionDomain.FILES,), ("a.txt",))
    with pytest.raises(FrozenInstanceError):
        event.revision = 2  # type: ignore[misc]

    assert ProjectionDomain("project_detail").value == "project_detail"
    assert RuntimeEventRouter.domains_for(FileSystemChanged) == (
        ProjectionDomain.FILES, ProjectionDomain.TREE, ProjectionDomain.HOME,
        ProjectionDomain.PROJECT_DETAIL, ProjectionDomain.FAVORITES,
    )
    assert RuntimeEventRouter.domains_for(FavoritesChanged) == (
        ProjectionDomain.FAVORITES,
    )
    assert RuntimeEventRouter.domains_for(AssetTagsChanged) == (
        ProjectionDomain.METADATA, ProjectionDomain.TAGS,
        ProjectionDomain.PROJECT_DETAIL, ProjectionDomain.HOME,
    )
    assert RuntimeEventRouter.domains_for(TagCatalogChanged) == (
        ProjectionDomain.TAGS, ProjectionDomain.HOME,
    )
    assert RuntimeEventRouter.domains_for(AssetNotesChanged) == (
        ProjectionDomain.METADATA, ProjectionDomain.PROJECT_DETAIL,
    )
    assert RuntimeEventRouter.domains_for(AssetUrlsChanged) == (
        ProjectionDomain.METADATA, ProjectionDomain.PROJECT_DETAIL,
    )
    assert _projection_domain("shares") == "shares"
    assert _projection_domain("users") == "users"
    assert _projection_domain("activity") == "activity"
    assert _projection_domain("online_users") == "online_users"
    assert RuntimeEventRouter.domains_for(ShareChanged) == (_projection_domain("shares"),)
    assert RuntimeEventRouter.domains_for(UserChanged) == (_projection_domain("users"),)
    assert RuntimeEventRouter.domains_for(InviteChanged) == (_projection_domain("users"),)
    assert RuntimeEventRouter.domains_for(ActivityChanged) == (_projection_domain("activity"),)
    assert RuntimeEventRouter.domains_for(PresenceChanged) == (_projection_domain("online_users"),)
    assert RuntimeEventRouter.domains_for(SellerProfileChanged) == (_projection_domain("shop"),)


@pytest.mark.parametrize(
    ("event_type", "expected_domain"),
    [
        (FavoritesChanged, _projection_domain("favorites")),
        (ShareChanged, _projection_domain("shares")),
        (UserChanged, _projection_domain("users")),
        (InviteChanged, _projection_domain("users")),
        (ActivityChanged, _projection_domain("activity")),
        (PresenceChanged, _projection_domain("online_users")),
        (SellerProfileChanged, _projection_domain("shop")),
    ],
)
def test_router_maps_share_and_identity_events_only_for_current_session(
    tmp_path, event_type, expected_domain,
):
    bus = EventBus()
    bootstrap, session, runtime = _runtime(tmp_path, bus)
    received = []
    runtime.event_router.subscribe(received.append)
    try:
        event = event_type(**_identity(session))
        bus.publish(event)
        assert len(received) == 1
        assert received[0].domains == (expected_domain,)
        assert received[0].paths == ()

        bus.publish(event_type(**_identity(session, session_token="wrong-token")))
        bus.publish(event_type(**_identity(session, library_root=str(tmp_path / "other"))))
        assert len(received) == 1
        assert runtime.revision == 1
    finally:
        runtime.close()
        bootstrap.library_service.close()


def test_router_maps_paths_deterministically_and_filters_invalid_events(tmp_path):
    bus = EventBus()
    bootstrap, session, runtime = _runtime(tmp_path, bus)
    received = []
    runtime.event_router.subscribe(received.append)
    try:
        bus.publish(FileSystemChanged(**_identity(
            session, paths=(str(tmp_path / "library" / "a.txt"), "b.txt", "a.txt", "."),
            old_paths=("old.txt", str(tmp_path / "library" / "b.txt")),
        )))
        assert received[-1].paths == ("a.txt", "b.txt", "old.txt")
        assert received[-1].revision == 1
        assert received[-1].domains == (
            ProjectionDomain.FILES, ProjectionDomain.TREE, ProjectionDomain.HOME,
            ProjectionDomain.PROJECT_DETAIL, ProjectionDomain.FAVORITES,
        )

        bus.publish(AssetTagsChanged(**_identity(session, file_path="nested\\asset.png")))
        assert received[-1].paths == ("nested/asset.png",)
        assert received[-1].revision == 2
        bus.publish(AssetTagsChanged(**_identity(
            session, file_path="", paths=("a.txt", "b.txt"),
        )))
        assert received[-1].paths == ("a.txt", "b.txt")
        assert received[-1].revision == 3
        bus.publish(TagCatalogChanged(**_identity(session)))
        assert received[-1].paths == ()
        assert received[-1].revision == 4

        for event in (
            FileSystemChanged(**_identity(session, session_token="wrong", paths=("x",))),
            AssetNotesChanged(**_identity(session, library_root=str(tmp_path / "other"), file_path="x")),
            AssetTagsChanged(file_path="x"),
            DomainEvent(),
            FileSystemChanged(**_identity(session, paths=("../escape",), old_paths=())),
        ):
            bus.publish(event)
        assert runtime.revision == 4
        assert len(received) == 4
    finally:
        runtime.close()
        bootstrap.library_service.close()


def test_router_subscriber_order_error_isolation_and_close(tmp_path):
    bus = EventBus()
    bootstrap, session, runtime = _runtime(tmp_path, bus)
    calls = []

    def bad(_event):
        calls.append("bad")
        raise RuntimeError("subscriber failure")

    first = runtime.event_router.subscribe(bad)
    runtime.event_router.subscribe(lambda _event: calls.append("good"))
    bus.publish(TagCatalogChanged(**_identity(session)))
    assert calls == ["bad", "good"]
    first.close()
    first.close()
    runtime.event_router.close()
    runtime.event_router.close()
    bus.publish(TagCatalogChanged(**_identity(session)))
    assert calls == ["bad", "good"]
    with pytest.raises(RuntimeError, match="closed"):
        runtime.event_router.subscribe(lambda _event: None)
    runtime.close()
    bootstrap.library_service.close()


def test_router_close_subscription_skips_snapshot_handler(tmp_path):
    """Closing a subscriber after dispatch snapshots must prevent its callback."""
    bus = EventBus()
    bootstrap, session, runtime = _runtime(tmp_path, bus)
    first_entered = threading.Event()
    release_first = threading.Event()
    calls = []

    def first(_event):
        calls.append("first")
        first_entered.set()
        assert release_first.wait(timeout=5)

    runtime.event_router.subscribe(first)
    second = runtime.event_router.subscribe(lambda _event: calls.append("second"))
    publish_thread = threading.Thread(
        target=bus.publish,
        args=(TagCatalogChanged(**_identity(session)),),
    )
    try:
        publish_thread.start()
        assert first_entered.wait(timeout=5)
        second.close()
        release_first.set()
        publish_thread.join(timeout=5)

        assert not publish_thread.is_alive()
        assert calls == ["first"]
    finally:
        release_first.set()
        publish_thread.join(timeout=5)
        runtime.close()
        bootstrap.library_service.close()


def test_subscription_close_drains_claimed_callback_before_return(tmp_path, monkeypatch):
    """A close racing a claimed callback waits for that callback to finish."""
    bus = EventBus()
    bootstrap, session, runtime = _runtime(tmp_path, bus)
    claimed = threading.Event()
    release_claim = threading.Event()
    handler_started = threading.Event()
    release_handler = threading.Event()
    close_done = threading.Event()
    calls = []

    def handler(_event):
        handler_started.set()
        assert release_handler.wait(timeout=5)
        calls.append("handler")

    subscription = runtime.event_router.subscribe(handler)
    original_claim = runtime.event_router._claim_subscription

    def gated_claim(subscription):
        claimed_result = original_claim(subscription)
        if claimed_result:
            claimed.set()
            assert release_claim.wait(timeout=5)
        return claimed_result

    monkeypatch.setattr(runtime.event_router, "_claim_subscription", gated_claim)
    publish_thread = threading.Thread(
        target=bus.publish,
        args=(TagCatalogChanged(**_identity(session)),),
    )
    close_thread = threading.Thread(
        target=lambda: (subscription.close(), close_done.set()),
    )
    try:
        publish_thread.start()
        assert claimed.wait(timeout=5)
        close_thread.start()
        assert not close_done.wait(timeout=0.1)

        release_claim.set()
        assert handler_started.wait(timeout=5)
        assert not close_done.wait(timeout=0.1)
        release_handler.set()
        publish_thread.join(timeout=5)
        close_thread.join(timeout=5)

        assert not publish_thread.is_alive()
        assert not close_thread.is_alive()
        assert close_done.is_set()
        assert calls == ["handler"]
        bus.publish(TagCatalogChanged(**_identity(session)))
        assert calls == ["handler"]
    finally:
        release_claim.set()
        release_handler.set()
        publish_thread.join(timeout=5)
        close_thread.join(timeout=5)
        runtime.close()
        bootstrap.library_service.close()


def test_router_close_from_callback_stops_remaining_callbacks(tmp_path):
    bus = EventBus()
    bootstrap, session, runtime = _runtime(tmp_path, bus)
    calls = []

    def close_router(_event):
        calls.append("close")
        runtime.event_router.close()

    runtime.event_router.subscribe(close_router)
    runtime.event_router.subscribe(lambda _event: calls.append("late"))
    bus.publish(TagCatalogChanged(**_identity(session)))
    assert calls == ["close"]
    runtime.close()
    bootstrap.library_service.close()


def test_runtime_close_from_callback_defers_adapter_cleanup(tmp_path, monkeypatch):
    """Runtime cleanup must wait until the closing callback has returned."""
    bus = EventBus()
    bootstrap, session, runtime = _runtime(tmp_path, bus)
    callback_entered = threading.Event()
    cleanup_started = threading.Event()
    release_callback = threading.Event()

    def cleanup():
        cleanup_started.set()

    monkeypatch.setattr(runtime.services.undo_service, "cleanup", cleanup)

    def closing_callback(_event):
        callback_entered.set()
        runtime.close()
        assert not cleanup_started.is_set()
        release_callback.set()

    runtime.event_router.subscribe(closing_callback)
    publish_thread = threading.Thread(
        target=bus.publish,
        args=(TagCatalogChanged(**_identity(session)),),
    )
    try:
        publish_thread.start()
        assert callback_entered.wait(timeout=5)
        assert release_callback.wait(timeout=5)
        publish_thread.join(timeout=5)
        assert not publish_thread.is_alive()
        assert cleanup_started.is_set()
    finally:
        release_callback.set()
        publish_thread.join(timeout=5)
        runtime.close()
        bootstrap.library_service.close()


def test_concurrent_router_close_waits_for_inflight_callback(tmp_path):
    """Every external close waits until the router has drained callbacks."""
    bus = EventBus()
    bootstrap, session, runtime = _runtime(tmp_path, bus)
    callback_entered = threading.Event()
    release_callback = threading.Event()
    first_close_returned = threading.Event()
    second_close_returned = threading.Event()

    def blocked_callback(_event):
        callback_entered.set()
        assert release_callback.wait(timeout=5)

    runtime.event_router.subscribe(blocked_callback)
    publish_thread = threading.Thread(
        target=bus.publish,
        args=(TagCatalogChanged(**_identity(session)),),
    )
    first_close_thread = threading.Thread(
        target=lambda: (runtime.event_router.close(), first_close_returned.set()),
    )
    second_close_thread = threading.Thread(
        target=lambda: (runtime.event_router.close(), second_close_returned.set()),
    )
    try:
        publish_thread.start()
        assert callback_entered.wait(timeout=5)
        first_close_thread.start()
        second_close_thread.start()
        assert not first_close_returned.wait(timeout=0.1)
        assert not second_close_returned.wait(timeout=0.1)

        release_callback.set()
        publish_thread.join(timeout=5)
        first_close_thread.join(timeout=5)
        second_close_thread.join(timeout=5)

        assert not publish_thread.is_alive()
        assert not first_close_thread.is_alive()
        assert not second_close_thread.is_alive()
        assert first_close_returned.is_set()
        assert second_close_returned.is_set()
    finally:
        release_callback.set()
        publish_thread.join(timeout=5)
        first_close_thread.join(timeout=5)
        second_close_thread.join(timeout=5)
        runtime.close()
        bootstrap.library_service.close()


def test_runtime_close_drains_router_callback_before_rejecting_revisions(
    tmp_path, monkeypatch,
):
    """A callback already in the router must finish during runtime close."""
    bus = EventBus()
    bootstrap, session, runtime = _runtime(tmp_path, bus)
    entered_revision = threading.Event()
    release_revision = threading.Event()
    received = []
    original_next_revision = runtime.next_revision

    def blocked_next_revision():
        entered_revision.set()
        assert release_revision.wait(timeout=5)
        return original_next_revision()

    monkeypatch.setattr(runtime, "next_revision", blocked_next_revision)
    runtime.event_router.subscribe(received.append)
    event = TagCatalogChanged(**_identity(session))
    publish_thread = threading.Thread(target=bus.publish, args=(event,))
    close_thread = threading.Thread(target=runtime.close)
    try:
        publish_thread.start()
        assert entered_revision.wait(timeout=5)
        close_thread.start()
        release_revision.set()
        publish_thread.join(timeout=5)
        close_thread.join(timeout=5)

        assert not publish_thread.is_alive()
        assert not close_thread.is_alive()
        assert received and received[0].revision == 1
        assert runtime.revision == 1
    finally:
        release_revision.set()
        publish_thread.join(timeout=5)
        close_thread.join(timeout=5)
        runtime.close()
        bootstrap.library_service.close()


def test_runtime_owns_independent_router_and_cleanup_does_not_reopen(tmp_path):
    bootstrap = ApplicationBootstrap()
    first_session = bootstrap.library_service.open_session(tmp_path / "library")
    first = bootstrap.runtime_for(first_session)
    router = first.event_router
    first_session.close()
    second_session = bootstrap.library_service.open_session(tmp_path / "library")
    second = bootstrap.runtime_for(second_session)
    assert first is not second
    assert first.epoch != second.epoch
    assert router is not second.event_router
    assert router.closed
    second.close()
    second.close()
    bootstrap.library_service.close()
