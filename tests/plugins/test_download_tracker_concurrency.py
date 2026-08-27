import importlib.util
import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from AssetsManager.domain.events import FileSystemChanged


class _PreferenceBag:
    def __init__(self):
        self.values = {"keep_days": 30, "history": {}}
        self.lock = threading.Lock()

    def get(self, key, default=None):
        with self.lock:
            return self.values.get(key, default)

    def set(self, key, value):
        with self.lock:
            self.values[key] = value


class _Context:
    def __init__(self, bag):
        self.bag = bag

    def preferences(self, _plugin_id=None):
        return self.bag


def _load_tracker() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[2]
        / "Plugins"
        / "Addons"
        / "download_tracker"
        / "tracker.py"
    )
    name = f"download_tracker_test_{id(path)}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tracker_history_reads_and_updates_are_thread_safe():
    tracker = _load_tracker()
    bag = _PreferenceBag()
    ctx = _Context(bag)
    hook = tracker.ImportHook()
    errors = []
    barrier = threading.Barrier(8)

    def writer(index):
        try:
            barrier.wait()
            path = f"asset-{index % 3}.png"
            hook.handle(ctx, FileSystemChanged(kind="import", paths=(path,)))
        except BaseException as exc:
            errors.append(exc)

    def reader(index):
        try:
            barrier.wait()
            for _ in range(20):
                tracker.DownloadParser.match(ctx, f"asset-{index % 3}.png")
                tracker.DownloadParser().parse(ctx, f"asset-{index % 3}.png")
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
    threads += [threading.Thread(target=reader, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert sum(record["count"] for record in tracker._history.values()) == 4
    assert bag.values["history"] == tracker._history


def test_history_panel_build_uses_snapshot_while_history_changes(monkeypatch):
    tracker = _load_tracker()
    bag = _PreferenceBag()
    ctx = _Context(bag)
    tracker._history.update(
        {f"asset-{index}.png": {"count": index + 1, "last": "2026-01-01T00:00:00+00:00"} for index in range(30)}
    )

    class Widget:
        pass

    class Layout:
        def __init__(self, _widget):
            self.widgets = []

        def addWidget(self, widget):
            self.widgets.append(widget)

        def addStretch(self):
            return None

    class Label:
        def __init__(self, text):
            self.text = text

    qtwidgets = SimpleNamespace(QLabel=Label, QVBoxLayout=Layout, QWidget=Widget)
    qt_module = ModuleType("PySide6")
    qt_module.QtWidgets = qtwidgets
    monkeypatch.setitem(sys.modules, "PySide6", qt_module)
    monkeypatch.setitem(sys.modules, "PySide6.QtWidgets", qtwidgets)

    stop = threading.Event()
    errors = []

    def mutate():
        try:
            while not stop.is_set():
                with tracker._history_lock:
                    tracker._history["live.png"] = {"count": 1, "last": "2026-01-02T00:00:00+00:00"}
                    tracker._history.pop("live.png", None)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=mutate)
    thread.start()
    try:
        for _ in range(50):
            widget = tracker.HistoryPanel().build(ctx)
            assert isinstance(widget, Widget)
    finally:
        stop.set()
        thread.join()

    assert errors == []


def test_import_hook_emits_refresh_after_history_update(monkeypatch):
    """handle() pings the refresh channel exactly once per applied change."""
    tracker = _load_tracker()
    bag = _PreferenceBag()
    ctx = _Context(bag)
    hook = tracker.ImportHook()

    calls: list[int] = []
    monkeypatch.setattr(tracker, "_emit_refresh", lambda: calls.append(1))

    hook.handle(ctx, FileSystemChanged(kind="import", paths=("asset.png",)))
    assert calls == [1]

    # Untracked kinds and empty change sets must not ping.
    hook.handle(ctx, FileSystemChanged(kind="deleted", paths=("asset.png",)))
    assert calls == [1]
    hook.handle(ctx, FileSystemChanged(kind="import", paths=()))
    assert calls == [1]


def test_refresh_signal_is_class_attribute_with_direct_emit():
    """_RefreshSignal.sig is a class attribute and emits into plain slots."""
    tracker = _load_tracker()
    try:
        from PySide6.QtCore import Signal
    except ImportError:  # pragma: no cover - env without Qt bindings
        assert tracker._QT_READY is False
        assert tracker._RefreshSignal.sig is None
        return

    sig = tracker._RefreshSignal.sig
    assert isinstance(sig, Signal)
    assert "sig" in vars(tracker._RefreshSignal)  # class attribute, not instance

    notifier = tracker._ensure_refresh_notifier()
    assert notifier is not None
    assert tracker._ensure_refresh_notifier() is notifier  # lazy singleton

    received: list[int] = []
    # The signal carries no payload, so the slot must be zero-arg.
    notifier.sig.connect(lambda: received.append(1))
    notifier.sig.emit()
    assert received == [1]


def test_refresh_notifies_under_core_application_instance():
    """End-to-end: worker emit -> QueuedConnection -> GUI loop delivers."""
    pytest.importorskip("PySide6.QtCore")
    from PySide6.QtCore import QCoreApplication, Qt

    tracker = _load_tracker()
    bag = _PreferenceBag()
    ctx = _Context(bag)

    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    try:
        notifier = tracker._ensure_refresh_notifier()
        assert notifier is not None

        received: list = []
        # Same wiring as HistoryPanel: explicit QueuedConnection.
        notifier.sig.connect(
            lambda: received.append(dict(tracker._history)),
            Qt.ConnectionType.QueuedConnection,
        )

        hook = tracker.ImportHook()
        hook.handle(ctx, FileSystemChanged(kind="copied", paths=("asset.png",)))
        assert received == []  # queued, nothing delivered yet

        app.processEvents()  # stand-in for the GUI event loop
        assert len(received) == 1
        assert list(received[0]) == ["asset.png"]
        received.clear()

        # Emits from a worker thread queue safely and deliver on the pump
        # (Qt may coalesce back-to-back no-payload emissions into one
        # delivery, so drain the queue instead of asserting exact counts).
        worker = threading.Thread(
            target=hook.handle,
            args=(ctx, FileSystemChanged(kind="import", paths=("asset2.png",))),
        )
        worker.start()
        worker.join()
        assert received == []
        for _ in range(5):
            app.processEvents()  # Qt6 has no hasPendingEvents; pump to converge
            if received:
                break
        assert len(received) >= 1
        snapshots = [path for snapshot in received for path in snapshot]
        assert set(snapshots) == {"asset.png", "asset2.png"}
    finally:
        del app
