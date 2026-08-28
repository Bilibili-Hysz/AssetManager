"""Sidebar preload single-flight and cancellation tests (H-D2).

Covers the two worker-level guarantees the fix depends on:
1. a superseded ``_PreloadTask`` cooperatively cancels mid-walk and never
   delivers its results;
2. rapid successive searches keep only the latest result (single-flight);
   every stale in-flight preload is cancelled synchronously at submission.
"""
import threading
import time


from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from AssetsManager.core.workers import BoundedPool
from AssetsManager.panels._sidebar_parts import _PreloadTask
from AssetsManager.panels.sidebar import SidebarPanel

_app = QApplication.instance() or QApplication([])


def _process_until(condition, timeout=5.0, step=0.01):
    """Pump the GUI event loop until *condition* holds or *timeout* expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _app.processEvents()
        if condition():
            return True
        time.sleep(step)
    return False


class _DoneRecorder(QObject):
    """Record preload completions with queued (cross-thread) delivery.

    ``_PreloadTask.signals.done`` is emitted from a worker thread; routing it
    through this recorder's queued connection means a result is observable
    only after the GUI event loop actually delivers it — so an *unexpected*
    emission cannot hide behind a direct (emitter-thread) call.
    """

    received = Signal(str, object, int, object)

    def __init__(self):
        super().__init__()
        self.items = []
        self.received.connect(self._record)

    def _record(self, text, results, gen, root):
        self.items.append(text)


def _fill_tree(root, dirs, files_per_dir):
    """Create a nested tree large enough for a cancellable mid-walk scan."""
    for i in range(dirs):
        d = root / f"dir-{i:03d}"
        d.mkdir(parents=True)
        for j in range(files_per_dir):
            (d / f"f-{j:03d}.txt").write_text("x")


def test_preload_task_cancel_stops_inflight_walk_and_drops_results(tmp_path, monkeypatch):
    root = tmp_path / "library"
    _fill_tree(root, dirs=48, files_per_dir=64)

    entered = threading.Event()
    real_scan = _PreloadTask._scan_recursive

    def _mark_entered(self, path, depth, results):
        entered.set()
        return real_scan(self, path, depth, results)

    monkeypatch.setattr(_PreloadTask, "_scan_recursive", _mark_entered)

    task = _PreloadTask([str(root)], "findme", gen=7, root=str(root), max_depth=2)
    recorder = _DoneRecorder()
    task.signals.done.connect(recorder.received)
    pool = BoundedPool(1)
    pool.start(task)
    assert entered.wait(5), "walk should have started before cancellation"

    task.cancel()
    started = time.monotonic()
    drained = pool.drain(1000)
    elapsed = time.monotonic() - started
    _app.processEvents()

    # The cancelled walk must exit in well under the 1s budget…
    assert drained is True
    assert elapsed < 1.0
    # …and must never deliver results, even after the event loop runs.
    assert recorder.items == []


def test_sidebar_rapid_searches_keep_only_latest_result(tmp_path, monkeypatch):
    panel = SidebarPanel()
    try:
        root = tmp_path / "library"
        root.mkdir()
        for i in range(10):
            (root / f"term{i}_asset.txt").write_text("x")
        panel._library_root = str(root)

        submitted = []
        applied = []
        calls = []
        real_start = panel._preload_pool.start
        real_done = panel._on_preload_done

        def spy_start(runnable):
            submitted.append(runnable)
            return real_start(runnable)

        def spy_done(text, results, gen, root_arg=None):
            calls.append((text, gen, root_arg))
            if (
                root_arg == panel._library_root
                and panel._controller.is_current_search(gen)
            ):
                applied.append(text)
            return real_done(text, results, gen, root_arg)

        monkeypatch.setattr(panel._preload_pool, "start", spy_start)
        monkeypatch.setattr(panel, "_on_preload_done", spy_done)

        for i in range(10):
            panel._search_pending = f"term{i}"
            panel._do_search()

        assert submitted, "each search must submit one preload task"
        # Every superseded preload is cancelled synchronously at submission;
        # only the newest task stays live (single-flight).
        for task in submitted[:-1]:
            assert task.is_cancelled()
        assert not submitted[-1].is_cancelled()

        assert _process_until(lambda: applied), "latest search result never delivered"
        assert applied == ["term9"]
        assert len(calls) >= 1
    finally:
        panel.shutdown()
        panel.deleteLater()
        _app.processEvents()