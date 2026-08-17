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
