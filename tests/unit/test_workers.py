"""D1 unified worker framework tests."""
from __future__ import annotations

import time

import pytest

from AssetsManager.core.workers import (
    BoundedPool,
    CancellationToken,
    CancellableRunnable,
    TaskCancelled,
)


def test_timer_handle_is_cancellable():
    from PySide6.QtCore import QObject

    from AssetsManager.core.timers import TimerHandle

    owner = QObject()
    calls = []
    handle = TimerHandle.schedule(owner, 0, lambda: calls.append(1))
    handle.cancel()
    assert not handle.is_active()
    handle._timer.timeout.emit()  # cancel cleared the callback before queuing
    assert calls == []


class _SleepTask(CancellableRunnable):
    def __init__(self, seconds: float, token: CancellationToken):
        super().__init__(cancel_token=token)
        self._seconds = seconds
        self.finished = False

    def run(self):
        deadline = time.monotonic() + self._seconds
        while time.monotonic() < deadline:
            if self.is_cancelled():
                return
            time.sleep(0.01)
        self.finished = True


def test_cancellation_token_cooperative_cancel():
    token = CancellationToken()
    assert not token.is_cancelled()

    token.cancel()
    assert token.is_cancelled()
    with pytest.raises(TaskCancelled):
        token.raise_if_cancelled()


def test_bounded_pool_runs_and_drains_its_own_work():
    token = CancellationToken()
    pool = BoundedPool(1)
    task = _SleepTask(0.05, token)
    pool.start(task)
    assert pool.drain(5_000) is True
    assert task.finished is True


def test_bounded_pool_cancel_all_stops_loop_bodies():
    token = CancellationToken()
    pool = BoundedPool(1)
    task = _SleepTask(30, token)
    pool.start(task)
    time.sleep(0.02)
    pool.cancel_all()
    assert pool.drain(5_000) is True
    assert task.finished is False


def test_preload_task_stops_when_token_cancelled(tmp_path):
    from AssetsManager.panels._sidebar_parts import _PreloadTask

    for depth in range(6):
        (tmp_path / ("dir" * depth)).mkdir(parents=True, exist_ok=True)
        (tmp_path / ("dir" * depth) / "file.txt").write_text("x", encoding="utf-8")

    token = CancellationToken()
    token.cancel()
    task = _PreloadTask(
        [str(tmp_path)], "q", 1, str(tmp_path), max_depth=10, cancel_token=token
    )
    emitted = []
    task.signals.done.connect(lambda *args: emitted.append(args))

    task.run()

    assert emitted == []


def test_model_prepare_library_switch_drains_within_budget(tmp_path):
    """D1 acceptance: a switch during an active size walk stays bounded."""
    from PySide6.QtCore import QCoreApplication

    QCoreApplication.setOrganizationName("AssetsManager-tests")

    root = tmp_path / "large"
    root.mkdir()
    for i in range(200):
        sub = root / f"dir-{i}"
        sub.mkdir()
        for j in range(10):
            (sub / f"file-{j}.bin").write_bytes(b"x" * 64)

    from AssetsManager.panels.file_list._model import FileSystemModel

    model = FileSystemModel()
    model.set_library_root(str(tmp_path), None) if hasattr(model, "set_library_root") else None
    model._lib_root = str(tmp_path)
    model._start_async_dir_size(str(root))

    started = time.monotonic()
    model.prepare_library_switch()
    elapsed = time.monotonic() - started

    assert elapsed < 3.0
    model.shutdown()
