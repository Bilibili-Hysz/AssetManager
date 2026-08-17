"""Tests for EventBus and domain events."""
import gc

from AssetsManager.domain.events import (
    AssetTagsChanged,
    DomainEvent,
    FileSystemChanged,
)
from AssetsManager.domain.event_bus import EventBus


def test_subscribe_and_publish():
    bus = EventBus()
    received = []
    bus.subscribe(AssetTagsChanged, lambda e: received.append(e))
    bus.publish(AssetTagsChanged(file_path="/a", new_tags=("hero",)))

    assert len(received) == 1
    assert received[0].file_path == "/a"
    assert received[0].new_tags == ("hero",)


def test_multiple_handlers():
    bus = EventBus()
    results = []
    bus.subscribe(FileSystemChanged, lambda e: results.append("a"))
    bus.subscribe(FileSystemChanged, lambda e: results.append("b"))
    bus.publish(FileSystemChanged(kind="moved", paths=("/new",), old_paths=("/old",)))

    assert results == ["a", "b"]


def test_unsubscribe():
    bus = EventBus()
    results = []

    def handler(e):
        results.append(1)

    bus.subscribe(FileSystemChanged, handler)
    bus.unsubscribe(FileSystemChanged, handler)
    bus.publish(FileSystemChanged(kind="moved", paths=("/new",), old_paths=("/old",)))

    assert results == []


def test_subscription_token_close_unsubscribes():
    bus = EventBus()
    results = []

    token = bus.subscribe(AssetTagsChanged, results.append)
    token.close()
    bus.publish(AssetTagsChanged(file_path="/a", new_tags=("hero",)))

    assert results == []
    assert bus.handler_count(AssetTagsChanged) == 0


def test_subscription_token_close_is_idempotent():
    bus = EventBus()
    token = bus.subscribe(AssetTagsChanged, lambda e: None)

    token.close()
    token.close()

    assert bus.handler_count(AssetTagsChanged) == 0


def test_weak_subscription_does_not_keep_owner_alive():
    bus = EventBus()
    results = []

    class Owner:
        def handle(self, event):
            results.append(event)

    owner = Owner()
    bus.subscribe_weak(AssetTagsChanged, owner.handle)
    assert bus.handler_count(AssetTagsChanged) == 1

    del owner
    gc.collect()
    bus.publish(AssetTagsChanged(file_path="/a", new_tags=("hero",)))

    assert results == []
    assert bus.handler_count(AssetTagsChanged) == 0


def test_weak_subscription_token_close_is_idempotent():
    bus = EventBus()

    class Owner:
        def handle(self, event):
            pass

    owner = Owner()
    token = bus.subscribe_weak(AssetTagsChanged, owner.handle)
    token.close()
    token.close()

    assert bus.handler_count(AssetTagsChanged) == 0


def test_handler_exception_does_not_block_others():
    bus = EventBus()
    results = []

    def bad_handler(e):
        raise ValueError("boom")

    bus.subscribe(AssetTagsChanged, bad_handler)
    bus.subscribe(AssetTagsChanged, lambda e: results.append("ok"))
    bus.publish(AssetTagsChanged(file_path="/a", new_tags=()))

    assert results == ["ok"]


def test_no_handlers_does_not_raise():
    bus = EventBus()
    bus.publish(DomainEvent())


def test_clear():
    bus = EventBus()
    bus.subscribe(AssetTagsChanged, lambda e: None)
    bus.subscribe(FileSystemChanged, lambda e: None)
    assert bus.handler_count(AssetTagsChanged) == 1
    assert bus.handler_count(FileSystemChanged) == 1

    bus.clear()
    assert bus.handler_count(AssetTagsChanged) == 0
    assert bus.handler_count(FileSystemChanged) == 0


def test_handler_count():
    bus = EventBus()
    assert bus.handler_count(FileSystemChanged) == 0
    bus.subscribe(FileSystemChanged, lambda e: None)
    bus.subscribe(FileSystemChanged, lambda e: None)
    assert bus.handler_count(FileSystemChanged) == 2


def test_event_timestamp_auto_set():
    event = AssetTagsChanged(file_path="/a", new_tags=("hero",))
    assert event.timestamp > 0


def test_event_is_frozen():
    event = FileSystemChanged(kind="moved", paths=("/new",), old_paths=("/old",))
    try:
        event.kind = "changed"
        raise AssertionError("Should have raised")
    except AttributeError:
        pass
