"""Library-level resident filesystem watcher (audit task B3).

The existing ``QFileSystemWatcher`` in ``panels/file_list/_navigation.py`` only
watches the currently browsed directory, so changes made outside that directory
(e.g. by another process or a sibling directory) are invisible to the UI.

Recursive ``QFileSystemWatcher`` over a whole library is not viable on Windows
(it would consume an OS change-notification handle per watched directory), so
this service instead polls the library tree by comparing a per-directory mtime
snapshot between rounds.  Directories whose mtime changed, were added, or were
removed since the previous round are reported through a ``FileSystemChanged``
domain event with ``kind="external_watch"``, using the same publishing shape as
``FileOperationService._publish_file_change``.

Design notes:
- The scan runs on a daemon thread so it never blocks the UI thread.
- A single failed round is logged and skipped; the loop keeps running.
- ``session.is_closed`` is checked before each scan so a closed session stops
  the service without waiting for the runtime adapter to call ``stop()``.
- The scan is budgeted by ``max_directories``: when the budget is exhausted
  mid-scan the service logs a warning and leaves the pending queue intact so
  the next round resumes where the previous one stopped (BFS with a cursor).
"""
from __future__ import annotations

import logging
import os
import threading
from typing import TYPE_CHECKING

from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import FileSystemChanged

if TYPE_CHECKING:
    from AssetsManager.application.context import LibrarySession

_log = logging.getLogger(__name__)

# Budget for a single scan round.  When a round hits this many directories it
# stops early and resumes next round (see ``_pending``), so a huge library can
# never pin the daemon thread for an unbounded time in one pass.
MAX_DIRECTORIES = 50_000

_KIND = "external_watch"


class LibraryWatcherService:
    """Poll a library root for directory-level changes and publish events.

    Lifecycle:
    - ``start()`` launches a single daemon thread that loops until ``stop()``
      is called (or the bound ``session`` is closed).
    - ``stop()`` is idempotent and safe to call before or after ``start()``.
    - ``scan_once()`` performs a single comparison round and is callable
      directly for deterministic testing.
    """

    def __init__(
        self,
        session: "LibrarySession",
        *,
        interval_seconds: float = 120.0,
        max_directories: int = MAX_DIRECTORIES,
    ) -> None:
        self._session = session
        self._interval = interval_seconds
        self._max_directories = max_directories
        # Directory path (str) -> st_mtime_ns snapshot built by the last round.
        self._snapshot: dict[str, int] = {}
        # BFS cursor for a partially completed round: directories still to
        # visit when the last round hit the directory budget.
        self._pending: list[tuple[str, int]] = []
        self._wakeup = threading.Event()
        self._stop_event = threading.Event()
        self._started = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # ── Lifecycle ────────────────────────────────────────────────

    def start(self) -> None:
        """Start the polling thread.  Idempotent."""
        with self._lock:
            if self._started:
                return
            self._started = True
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run, name="library-watcher", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        """Stop the polling thread.  Idempotent and repeatable."""
        with self._lock:
            self._stop_event.set()
            self._wakeup.set()
            self._started = False

    # ── Polling loop ─────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if self._wakeup.wait(self._interval):
                # ``stop()`` set the wakeup event; break out on the next check.
                if self._stop_event.is_set():
                    break
            if self._session.is_closed:
                _log.info("Library watcher stopping: session closed for %s", self._session.root_str)
                break
            try:
                self.scan_once()
            except Exception:
                # A single failed round must not kill the loop; log and resume
                # on the next interval.
                _log.exception("Library watcher scan failed for %s", self._session.root_str)
                continue

    # ── Scanning ─────────────────────────────────────────────────

    def scan_once(self) -> list[str]:
        """Run one comparison round and return changed directory paths.

        The returned paths are the string paths of directories that were added,
        removed, or whose mtime changed relative to the previous snapshot.  The
        first round (empty snapshot) only establishes a baseline and returns an
        empty list — it publishes nothing.
        """
        if self._session.is_closed:
            return []

        root = str(self._session.root)
        baseline = not self._snapshot
        seen: dict[str, int] = {}
        changed: list[str] = []
        budget_exhausted = False

        # Resume an interrupted previous round before scanning the root anew.
        queue = self._pending if self._pending else [(root, 0)]
        self._pending = []

        scanned = 0
        while queue:
            path, _depth = queue.pop(0)
            try:
                entry = os.scandir(path)
            except OSError:
                # The directory vanished or is unreadable.  If it was known to
                # us, report its removal (the parent will also be flagged).
                if path in self._snapshot:
                    changed.append(path)
                continue
            with entry:
                try:
                    st = os.stat(path)
                    mtime_ns = st.st_mtime_ns
                except OSError:
                    mtime_ns = self._snapshot.get(path, 0)
                seen[path] = mtime_ns
                scanned += 1
                if scanned >= self._max_directories:
                    budget_exhausted = True
                    self._pending = queue
                    break
                for child in entry:
                    if child.name.startswith("."):
                        continue
                    try:
                        if child.is_dir(follow_symlinks=False):
                            queue.append((child.path, _depth + 1))
                    except OSError:
                        continue

        if not baseline:
            for path in seen:
                if self._snapshot.get(path) != seen[path]:
                    changed.append(path)
            # Removal detection is deferred while a round is still partial:
            # directories beyond the budget were not observed this round, so
            # their absence from ``seen`` proves nothing yet.
            if not budget_exhausted:
                for path in self._snapshot:
                    if path not in seen:
                        changed.append(path)

        # Merge instead of replace: entries beyond an exhausted budget keep
        # their previous mtime so the next round resumes comparing them
        # instead of reporting the whole unscanned region as new every time.
        self._snapshot.update(seen)

        if budget_exhausted:
            _log.warning(
                "Library watcher directory budget (%d) exhausted for %s; "
                "deferring the remainder to the next round",
                self._max_directories,
                self._session.root_str,
            )

        if changed and not baseline:
            get_event_bus().publish(FileSystemChanged(
                library_root=self._session.root_str,
                session_token=self._session.event_token,
                kind=_KIND,
                paths=tuple(changed),
            ))
        return changed if not baseline else []
