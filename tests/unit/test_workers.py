"""D1 unified worker framework tests."""
from __future__ import annotations

import logging
import threading
import time

import pytest

from AssetsManager.core.workers import (
    BoundedPool,
    CancellationToken,
    CancellableRunnable,
    TaskCancelled,
    retained_pool_count,
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


class _BlockingTask(CancellableRunnable):
    def __init__(self, entered: threading.Event, release: threading.Event):
        super().__init__()
        self._entered = entered
        self._release = release

    def run(self):
        self._entered.set()
        self._release.wait(10)


def test_bounded_pool_close_reaps_a_timed_out_pool_without_blocking():
    entered = threading.Event()
    release = threading.Event()
    pool = BoundedPool(1)
    pool.start(_BlockingTask(entered, release))
    assert entered.wait(5), "blocking task should start"

    initial_retained = retained_pool_count()
    started = time.monotonic()
    assert pool.close(100, owner_label="worker-test") is False
    assert time.monotonic() - started < 1.0
    assert retained_pool_count() == initial_retained + 1

    release.set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and retained_pool_count() != initial_retained:
        time.sleep(0.01)
    assert retained_pool_count() == initial_retained
    with pytest.raises(RuntimeError, match="closed"):
        pool.drain(1)


def test_reap_pool_gives_up_after_bounded_polls_and_keeps_entry(monkeypatch, caplog):
    """A wedged pool must not pin the reaper forever: after the poll budget
    the reaper logs an error and leaves the registry entry for observation."""
    from AssetsManager.core import workers as workers_module

    class _WedgedPool:
        def __init__(self):
            self.polls = 0

        def waitForDone(self, timeout_ms=None):
            self.polls += 1
            return False

        def activeThreadCount(self):
            return 1

    wedged = _WedgedPool()
    monkeypatch.setattr(workers_module, "_REAP_POLL_INTERVAL_MS", 1)
    initial = retained_pool_count()
    workers_module._retained_pools[id(wedged)] = wedged
    try:
        with caplog.at_level(logging.ERROR, logger="AssetsManager.core.workers"):
            workers_module._reap_pool(wedged, "reaper-wedged-test")

        # The reaper exited after exactly the poll budget instead of waiting
        # unboundedly on the wedged pool.
        assert wedged.polls == workers_module._REAP_MAX_POLLS
        assert retained_pool_count() == initial + 1
        errors = [
            record
            for record in caplog.records
            if record.levelno == logging.ERROR
            and "reaper-wedged-test" in record.getMessage()
        ]
        assert errors, "expected an ERROR log for the wedged pool"
        assert "still busy" in errors[0].getMessage()
    finally:
        with workers_module._retained_pools_lock:
            workers_module._retained_pools.pop(id(wedged), None)


def test_reap_pool_releases_entry_once_pool_finishes(monkeypatch):
    """A pool that finishes within the poll budget is released normally."""
    from AssetsManager.core import workers as workers_module

    class _FinishingPool:
        def __init__(self):
            self.polls = 0

        def waitForDone(self, timeout_ms=None):
            self.polls += 1
            return self.polls >= 2

        def activeThreadCount(self):
            return 0

    pool = _FinishingPool()
    monkeypatch.setattr(workers_module, "_REAP_POLL_INTERVAL_MS", 1)
    initial = retained_pool_count()
    workers_module._retained_pools[id(pool)] = pool
    try:
        workers_module._reap_pool(pool, "reaper-finish-test")

        assert pool.polls == 2
        assert retained_pool_count() == initial
    finally:
        with workers_module._retained_pools_lock:
            workers_module._retained_pools.pop(id(pool), None)


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
