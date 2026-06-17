"""Tests for EventBus and domain events."""
import gc

from AssetsManager.domain.events import (
    DomainEvent,
    FileRenamed,
    TagsChanged,
)
from AssetsManager.domain.event_bus import EventBus


def test_subscribe_and_publish():
    bus = EventBus()
    received = []
    bus.subscribe(TagsChanged, lambda e: received.append(e))
    bus.publish(TagsChanged(file_path="/a", new_tags=("hero",)))

    assert len(received) == 1
    assert received[0].file_path == "/a"
    assert received[0].new_tags == ("hero",)


def test_multiple_handlers():
    bus = EventBus()
    results = []
    bus.subscribe(FileRenamed, lambda e: results.append("a"))
    bus.subscribe(FileRenamed, lambda e: results.append("b"))
    bus.publish(FileRenamed(old_path="/old", new_path="/new"))

    assert results == ["a", "b"]


def test_unsubscribe():
    bus = EventBus()
    results = []

    def handler(e):
        results.append(1)

    bus.subscribe(FileRenamed, handler)
    bus.unsubscribe(FileRenamed, handler)
    bus.publish(FileRenamed(old_path="/old", new_path="/new"))

    assert results == []


def test_subscription_token_close_unsubscribes():
    bus = EventBus()
    results = []

    token = bus.subscribe(TagsChanged, results.append)
    token.close()
    bus.publish(TagsChanged(file_path="/a", new_tags=("hero",)))

    assert results == []
    assert bus.handler_count(TagsChanged) == 0


def test_subscription_token_close_is_idempotent():
    bus = EventBus()
    token = bus.subscribe(TagsChanged, lambda e: None)

    token.close()
    token.close()

    assert bus.handler_count(TagsChanged) == 0


def test_weak_subscription_does_not_keep_owner_alive():
    bus = EventBus()
    results = []

    class Owner:
        def handle(self, event):
            results.append(event)

    owner = Owner()
    bus.subscribe_weak(TagsChanged, owner.handle)
    assert bus.handler_count(TagsChanged) == 1

    del owner
    gc.collect()
    bus.publish(TagsChanged(file_path="/a", new_tags=("hero",)))

    assert results == []
    assert bus.handler_count(TagsChanged) == 0


def test_weak_subscription_token_close_is_idempotent():
    bus = EventBus()

    class Owner:
        def handle(self, event):
            pass

    owner = Owner()
    token = bus.subscribe_weak(TagsChanged, owner.handle)
    token.close()
    token.close()

    assert bus.handler_count(TagsChanged) == 0


def test_handler_exception_does_not_block_others():
    bus = EventBus()
    results = []

    def bad_handler(e):
        raise ValueError("boom")

    bus.subscribe(TagsChanged, bad_handler)
    bus.subscribe(TagsChanged, lambda e: results.append("ok"))
    bus.publish(TagsChanged(file_path="/a", new_tags=()))

    assert results == ["ok"]


def test_no_handlers_does_not_raise():
    bus = EventBus()
    bus.publish(DomainEvent())


def test_clear():
    bus = EventBus()
    bus.subscribe(TagsChanged, lambda e: None)
    bus.subscribe(FileRenamed, lambda e: None)
    assert bus.handler_count(TagsChanged) == 1
    assert bus.handler_count(FileRenamed) == 1

    bus.clear()
    assert bus.handler_count(TagsChanged) == 0
    assert bus.handler_count(FileRenamed) == 0


def test_handler_count():
    bus = EventBus()
    assert bus.handler_count(FileRenamed) == 0
    bus.subscribe(FileRenamed, lambda e: None)
    bus.subscribe(FileRenamed, lambda e: None)
    assert bus.handler_count(FileRenamed) == 2


def test_event_timestamp_auto_set():
    event = TagsChanged(file_path="/a", new_tags=("hero",))
    assert event.timestamp > 0


def test_event_is_frozen():
    event = FileRenamed(old_path="/old", new_path="/new")
    try:
        event.old_path = "/changed"
        assert False, "Should have raised"
    except AttributeError:
        pass
