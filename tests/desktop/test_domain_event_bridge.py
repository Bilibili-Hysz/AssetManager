import threading
import time
from types import SimpleNamespace


from PySide6.QtWidgets import QApplication

from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import AssetTagsChanged
from AssetsManager.application.runtime_events import InvalidationEvent, ProjectionDomain
from AssetsManager.panels._event_bridge import RuntimeEventSubscription
from AssetsManager.panels.base import PanelContent


def _process_until(app, predicate, timeout: float = 1.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline and not predicate():
        app.processEvents()
        time.sleep(0.01)


def test_domain_event_bridge_delivers_on_qt_thread_from_worker():
    app = QApplication.instance() or QApplication([])
    panel = PanelContent()
    received_threads: list[int] = []
    main_thread = threading.get_ident()

    try:
        panel._connect_domain_event(
            AssetTagsChanged,
            lambda event: received_threads.append(threading.get_ident()),
        )

        worker = threading.Thread(
            target=lambda: get_event_bus().publish(AssetTagsChanged(file_path="/a", new_tags=("tag",)))
        )
        worker.start()
        worker.join(timeout=1.0)
        _process_until(app, lambda: bool(received_threads))

        assert received_threads == [main_thread]
    finally:
        panel.shutdown()
        panel.deleteLater()
        app.processEvents()


def test_domain_event_bridge_unsubscribes_on_panel_shutdown():
    app = QApplication.instance() or QApplication([])
    panel = PanelContent()
    received: list[object] = []

    try:
        panel._connect_domain_event(AssetTagsChanged, received.append)
        assert get_event_bus().handler_count(AssetTagsChanged) == 1

        panel.shutdown()

        assert get_event_bus().handler_count(AssetTagsChanged) == 0
        get_event_bus().publish(AssetTagsChanged(file_path="/a", new_tags=("tag",)))
        app.processEvents()
        assert received == []
    finally:
        panel.deleteLater()
        app.processEvents()


def test_domain_event_bridge_handler_exception_does_not_affect_others():
    app = QApplication.instance() or QApplication([])
    panel = PanelContent()
    good_received: list[object] = []

    def bad_handler(event):
        raise ValueError("intentional error")

    try:
        panel._connect_domain_event(AssetTagsChanged, bad_handler)
        panel._connect_domain_event(AssetTagsChanged, good_received.append)

        get_event_bus().publish(AssetTagsChanged(file_path="/a", new_tags=("tag",)))
        _process_until(app, lambda: bool(good_received))

        assert len(good_received) == 1
    finally:
        panel.shutdown()
        panel.deleteLater()
        app.processEvents()


def test_domain_event_bridge_delivers_multiple_events_from_multiple_workers():
    app = QApplication.instance() or QApplication([])
    panel = PanelContent()
    received: list[str] = []
    main_thread = threading.get_ident()

    try:
        panel._connect_domain_event(AssetTagsChanged, lambda e: received.append(e.file_path))

        workers = []
        for i in range(5):
            t = threading.Thread(
                target=lambda idx=i: get_event_bus().publish(
                    AssetTagsChanged(file_path=f"/file{idx}", new_tags=("tag",))
                )
            )
            workers.append(t)
            t.start()
        for t in workers:
            t.join(timeout=2.0)

        _process_until(app, lambda: len(received) >= 5, timeout=3.0)

        assert len(received) == 5
        assert all(t == main_thread for t in [main_thread] * len(received))
    finally:
        panel.shutdown()
        panel.deleteLater()
        app.processEvents()

class _FakeRuntimeSubscription:
    def close(self):
        pass


class _FakeRuntimeRouter:
    def __init__(self):
        self.callback = None

    def subscribe(self, callback):
        self.callback = callback
        return _FakeRuntimeSubscription()

    def emit(self, event):
        assert self.callback is not None
        self.callback(event)


def test_runtime_event_bridge_delivers_on_qt_thread_from_worker():
    app = QApplication.instance() or QApplication([])
    panel = PanelContent()
    router = _FakeRuntimeRouter()
    runtime = SimpleNamespace(event_router=router)
    received_threads: list[int] = []
    main_thread = threading.get_ident()
    subscription = RuntimeEventSubscription(
        runtime,
        lambda _event: received_threads.append(threading.get_ident()),
        panel,
    )

    try:
        worker = threading.Thread(
            target=lambda: router.emit(
                InvalidationEvent(
                    "epoch", 1, (ProjectionDomain.TAGS,), (),
                )
            )
        )
        worker.start()
        worker.join(timeout=1.0)
        _process_until(app, lambda: bool(received_threads))

        assert received_threads == [main_thread]
    finally:
        subscription.close()
        panel.deleteLater()
        app.processEvents()
