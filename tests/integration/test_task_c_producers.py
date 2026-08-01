"""Task C contracts for session-scoped mutation event producers."""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from AssetsManager.application.auth_service import AuthService
from AssetsManager.application.share_service import ShareService
from AssetsManager.domain.event_bus import EventBus
from AssetsManager.domain.events import ActivityChanged, InviteChanged, PresenceChanged, ShareChanged, UserChanged
from AssetsManager.lan.routes._helpers import ActivityLog, OnlineUsers


ROOT = "/library"
TOKEN = "session-token"


@pytest.mark.parametrize(
    "event_type",
    [ShareChanged, UserChanged, InviteChanged, ActivityChanged, PresenceChanged],
)
def test_mutation_events_are_immutable_and_session_scoped(event_type):
    event = event_type(library_root=ROOT, session_token=TOKEN)
    with pytest.raises(FrozenInstanceError):
        event.session_token = "changed"  # type: ignore[misc]
    assert event.library_root == ROOT
    assert event.session_token == TOKEN


def test_share_mutations_publish_after_repository_success_and_not_on_failure(
    schema_db, monkeypatch,
):
    bus = EventBus()
    service = ShareService(schema_db, "secret")
    service.init_table()
    service._library_root = ROOT
    service._session_token = TOKEN
    service._event_bus = bus
    order: list[str] = []

    def publish(event):
        order.append("publish")
        assert isinstance(event, ShareChanged)
        assert event.library_root == ROOT
        assert event.session_token == TOKEN

    monkeypatch.setattr(bus, "publish", publish)
    original_insert = service._repo.insert
    monkeypatch.setattr(service._repo, "insert", lambda *args, **kwargs: (order.append("repo"), original_insert(*args, **kwargs))[1])
    assert service.create_share(["asset.txt"]) is not None
    assert order == ["repo", "publish"]

    order.clear()
    monkeypatch.setattr(service._repo, "insert", lambda *args, **kwargs: (order.append("repo"), False)[1])
    assert service.create_share(["asset.txt"]) is None
    assert order == ["repo"]


def test_share_notification_failure_does_not_change_successful_mutation(schema_db, monkeypatch):
    bus = EventBus()
    service = ShareService(schema_db, "secret")
    service.init_table()
    service._library_root = ROOT
    service._session_token = TOKEN
    service._event_bus = bus
    monkeypatch.setattr(bus, "publish", lambda _event: (_ for _ in ()).throw(RuntimeError("notify failed")))

    assert service.create_share(["asset.txt"]) is not None


def test_share_download_publishes_after_counter_commit(schema_db, monkeypatch):
    bus = EventBus()
    service = ShareService(schema_db, "secret")
    service._library_root = ROOT
    service._session_token = TOKEN
    service._event_bus = bus
    published = []
    monkeypatch.setattr(bus, "publish", published.append)
    monkeypatch.setattr(service._repo, "increment_download", lambda _share_id: True)

    assert service.increment_download("share-1") is True
    assert len(published) == 1
    assert isinstance(published[0], ShareChanged)

    published.clear()
    monkeypatch.setattr(service._repo, "increment_download", lambda _share_id: False)
    assert service.increment_download("share-1") is False
    assert published == []


def test_activity_and_presence_producers_publish_after_visible_state_changes():
    bus = EventBus()
    published = []
    activity = ActivityLog(event_bus=bus, library_root=ROOT, session_token=TOKEN)
    online = OnlineUsers(event_bus=bus, library_root=ROOT, session_token=TOKEN)

    bus.subscribe(ActivityChanged, published.append)
    bus.subscribe(PresenceChanged, published.append)

    activity.add("admin", "login", "signed in")
    online.connect("user-1", "member", "127.0.0.1")
    online.connect("user-1", "member", "127.0.0.1")
    online.disconnect("user-1")
    online.disconnect("user-1")

    assert [type(event) for event in published] == [ActivityChanged, PresenceChanged, PresenceChanged]
    assert all(event.library_root == ROOT and event.session_token == TOKEN for event in published)


def test_user_notification_failure_does_not_change_successful_mutation(schema_db, monkeypatch):
    bus = EventBus()
    service = AuthService(schema_db, "secret")
    service._library_root = ROOT
    service._session_token = TOKEN
    service._event_bus = bus
    monkeypatch.setattr(service._repo, "set_user_active", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(bus, "publish", lambda _event: (_ for _ in ()).throw(RuntimeError("notify failed")))

    assert service.activate_user(7) is True


@pytest.mark.parametrize(
    ("method_name", "args", "event_type", "repo_method"),
    [
        ("activate_user", (7,), UserChanged, "set_user_active"),
        ("deactivate_user", (7,), UserChanged, "set_user_active"),
        ("generate_invite_code", (), InviteChanged, "insert_invite_code"),
        ("revoke_invite_code", ("INVITE",), InviteChanged, "deactivate_invite_code"),
    ],
)
def test_auth_mutations_publish_only_after_repository_success(
    schema_db, monkeypatch, method_name, args, event_type, repo_method,
):
    bus = EventBus()
    service = AuthService(schema_db, "secret")
    service._library_root = ROOT
    service._session_token = TOKEN
    service._event_bus = bus
    order: list[str] = []

    def publish(event):
        order.append("publish")
        assert isinstance(event, event_type)
        assert event.library_root == ROOT
        assert event.session_token == TOKEN

    monkeypatch.setattr(bus, "publish", publish)
    if method_name == "generate_invite_code":
        monkeypatch.setattr(service._repo, repo_method, lambda *a, **k: (order.append("repo"), True)[1])
    else:
        monkeypatch.setattr(service._repo, repo_method, lambda *a, **k: (order.append("repo"), True)[1])
    result = getattr(service, method_name)(*args)
    assert result is True or (isinstance(result, str) and result)
    assert order == ["repo", "publish"]

    order.clear()
    if method_name == "generate_invite_code":
        monkeypatch.setattr(service._repo, repo_method, lambda *a, **k: (order.append("repo"), False)[1])
    else:
        monkeypatch.setattr(service._repo, repo_method, lambda *a, **k: (order.append("repo"), False)[1])
    result = getattr(service, method_name)(*args)
    assert result is False or result == ""
    assert order == ["repo"]
