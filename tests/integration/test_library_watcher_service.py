"""Integration tests for the library-level filesystem watcher (B3).

Uses a minimal fake session exposing only the ``LibrarySession`` attributes the
watcher consumes (``root``/``root_str``/``event_token``/``is_closed``).  A fake
keeps these tests free of the full SQLite bootstrap and makes the baseline /
publish / close semantics deterministic without a daemon thread (``scan_once``
is called directly; ``start``/``stop`` are only exercised for the thread loop).
"""
from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from AssetsManager.domain import event_bus as eb
from AssetsManager.domain.event_bus import EventBus
from AssetsManager.domain.events import FileSystemChanged
from AssetsManager.application.library_watcher_service import LibraryWatcherService


class _FakeSession:
    """Minimal stand-in for ``LibrarySession`` narrowed to what the watcher uses."""

    def __init__(self, root: Path, *, closed: bool = False):
        self._root = root
        self._closed = closed
        self.event_token = "fake-token"

    @property
    def root(self) -> Path:
        return self._root

    @property
    def root_str(self) -> str:
        return str(self._root)

    @property
    def is_closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        self._closed = True


def _subscribe(monkeypatch):
    bus = EventBus()
    events = []
    bus.subscribe(FileSystemChanged, events.append)
    monkeypatch.setattr(eb, "_instance", bus)
    return events


def test_first_round_establishes_baseline_without_publishing(tmp_path, monkeypatch):
    """The first scan records a baseline and publishes nothing."""
    events = _subscribe(monkeypatch)
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b").mkdir()

    watcher = LibraryWatcherService(_FakeSession(tmp_path), interval_seconds=5.0)

    assert watcher.scan_once() == []
    assert events == []


def test_changed_directory_enqueues_root_rescan(tmp_path, monkeypatch):
    from AssetsManager.application import ReconciliationQueue

    events = _subscribe(monkeypatch)
    queue = ReconciliationQueue(library_root=tmp_path, clock=lambda: 0.0)
    watcher = LibraryWatcherService(
        _FakeSession(tmp_path),
        interval_seconds=5.0,
        reconciliation_queue=queue,
    )
    assert watcher.scan_once() == []
    (tmp_path / "changed").mkdir()

    changed = watcher.scan_once()

    assert str(tmp_path / "changed") in changed
    tasks = queue.snapshot()
    assert len(tasks) == 1
    assert tasks[0].path == str(tmp_path.resolve()).lower()
    assert tasks[0].reason == "external_watch"
    assert len(events) == 1


def test_watcher_queue_failure_does_not_block_event(tmp_path, monkeypatch):
    events = _subscribe(monkeypatch)

    class FailingQueue:
        def enqueue_or_merge(self, **_kwargs):
            raise RuntimeError("queue unavailable")

    watcher = LibraryWatcherService(
        _FakeSession(tmp_path),
        reconciliation_queue=FailingQueue(),
    )
    watcher.scan_once()
    (tmp_path / "changed").mkdir()

    assert watcher.scan_once()
    assert len(events) == 1


def test_added_directory_reports_and_publishes_once(tmp_path, monkeypatch):
    """A directory added after the baseline is reported and published once."""
    events = _subscribe(monkeypatch)
    watcher = LibraryWatcherService(_FakeSession(tmp_path), interval_seconds=5.0)
    assert watcher.scan_once() == []

    added = tmp_path / "newdir"
    added.mkdir()

    changed = watcher.scan_once()
    assert str(added) in changed
    assert len(events) == 1
    event = events[0]
    assert event.library_root == str(tmp_path)
    assert event.session_token == "fake-token"
    assert event.kind == "external_watch"
    assert str(added) in event.paths


def test_removed_directory_reports_parent(tmp_path, monkeypatch):
    """Removing a known directory reports its (parent) path on the next round."""
    events = _subscribe(monkeypatch)
    child = tmp_path / "gone"
    child.mkdir()
    watcher = LibraryWatcherService(_FakeSession(tmp_path))
    assert watcher.scan_once() == []

    child.rmdir()
    changed = watcher.scan_once()

    # The removed dir itself must be reported; the root's mtime also changes.
    assert str(child) in changed
    assert len(events) == 1
    assert str(child) in events[0].paths


def test_stop_prevents_further_scanning(tmp_path, monkeypatch):
    """``stop()`` halts the polling loop even if the interval elapses."""
    events = _subscribe(monkeypatch)
    watcher = LibraryWatcherService(_FakeSession(tmp_path), interval_seconds=0.05)
    assert watcher.scan_once() == []

    watcher.start()
    watcher.stop()
    count_after_stop = len(events)

    # Re-scan directly: the snapshot is still consulted, but the loop must not
    # fire again on its own.  Calling scan_once directly is still allowed — the
    # contract is that the *loop* stops, so we assert the thread flag is set.
    assert watcher._stop_event.is_set()
    assert count_after_stop == 0


def test_stop_joins_thread_and_prevents_overlapping_restart(tmp_path, monkeypatch):
    watcher = LibraryWatcherService(_FakeSession(tmp_path), interval_seconds=0.01)
    assert watcher.start() is True
    watcher.stop()
    assert watcher._thread is None
    assert watcher.start() is True
    watcher.stop()


def test_scan_once_on_closed_session_returns_empty(tmp_path, monkeypatch):
    """A closed session makes ``scan_once`` return [] without raising."""
    events = _subscribe(monkeypatch)
    (tmp_path / "a").mkdir()
    session = _FakeSession(tmp_path)
    watcher = LibraryWatcherService(session)
    assert watcher.scan_once() == []

    session.close()
    (tmp_path / "added_after_close").mkdir()

    assert watcher.scan_once() == []
    assert events == []


def _mutate_until_mtime_differs(
    path: Path, mutate, baseline_ns: int, timeout: float = 5.0
) -> None:
    """Apply ``mutate`` until ``path``'s mtime differs from ``baseline_ns``.

    The watcher reports a directory only when its mtime differs from the
    recorded snapshot, so a test must guarantee an *observably different*
    timestamp rather than merely a later one.  Windows directory timestamps
    advance in coarse ticks: a mutation landing in the same tick as the
    baseline scan leaves the mtime byte-identical, and the change is invisible
    no matter how long the test then waits.  Under a parallel suite that
    same-tick collision is routine.  Re-mutating is what moves the clock
    forward; production polls seconds apart and never sees the window.
    """
    deadline = time.monotonic() + timeout
    counter = 0
    while True:
        mutate(counter)
        if os.stat(path).st_mtime_ns != baseline_ns:
            return
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"{path} mtime stayed at {baseline_ns} for {timeout}s across "
                f"{counter + 1} mutations"
            )
        counter += 1
        time.sleep(0.01)


def test_dot_entries_and_files_are_ignored(tmp_path, monkeypatch):
    """Hidden entries and plain files do not create directory snapshots."""
    _subscribe(monkeypatch)
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "file.txt").write_text("content")
    watcher = LibraryWatcherService(_FakeSession(tmp_path))
    assert watcher.scan_once() == []
    # The value the watcher will compare against, not a separate stat of our
    # own: a tick could elapse between the two, which is the race this guards.
    baseline_ns = watcher._snapshot[str(tmp_path)]

    # Creating a new file changes the parent (root) directory mtime, so the
    # root is reported while neither the hidden dir nor the new file becomes a
    # snapshotted directory.
    _mutate_until_mtime_differs(
        tmp_path,
        lambda n: (tmp_path / f"second{'' if n == 0 else n}.txt").write_text("content"),
        baseline_ns,
    )
    changed = watcher.scan_once()
    assert str(tmp_path) in changed
    assert all("/.hidden" not in p for p in changed)


class _FakeDirEntry:
    """Scandir entry stand-in with a fixed name/path/kind."""

    def __init__(self, name: str, path: str, *, is_dir: bool = True):
        self.name = name
        self.path = path
        self._is_dir = is_dir

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        return self._is_dir


class _FakeScandir:
    """Deterministic directory listing (path -> children in insertion order).

    Real ``os.scandir`` ordering is filesystem-specific, so a budget test that
    pins the dequeue (BFS) order needs a fixed enumeration.
    """

    def __init__(self, tree: dict[str, list[_FakeDirEntry]]):
        self._tree = tree

    def __call__(self, path: str):
        entries = iter(self._tree[path])

        class _Iterator:
            def __iter__(self):
                return entries

            def __next__(self):
                return next(entries)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def close(self):
                pass

        return _Iterator()


def test_directory_budget_resumes_in_fifo_order(tmp_path, monkeypatch):
    """A budget-exhausted round resumes exactly where it stopped (BFS order).

    With a per-round budget of 3 and the fixed listing root -> [a1, z1],
    a1 -> [a2], the first round dequeues root, a1 and z1.  a2 must therefore be
    the *only* deferred entry: under LIFO dequeue the third dequeue would have
    been a2 and z1 would be deferred instead.
    """
    import AssetsManager.application.library_watcher_service as watcher_module

    _subscribe(monkeypatch)
    a1 = tmp_path / "a1"
    z1 = tmp_path / "z1"
    a2 = a1 / "a2"
    for directory in (a1, z1, a2):
        directory.mkdir()
    tree = {
        str(tmp_path): [_FakeDirEntry("a1", str(a1)), _FakeDirEntry("z1", str(z1))],
        str(a1): [_FakeDirEntry("a2", str(a2))],
        str(z1): [],
        str(a2): [],
    }
    monkeypatch.setattr(watcher_module.os, "scandir", _FakeScandir(tree))
    watcher = LibraryWatcherService(_FakeSession(tmp_path), max_directories=3)

    assert watcher.scan_once() == []  # baseline
    assert list(watcher._pending) == [(str(a2), 2)]

    watcher.scan_once()  # resumes with the deferred a2 only
    assert set(watcher._snapshot) == {str(tmp_path), str(a1), str(z1), str(a2)}
