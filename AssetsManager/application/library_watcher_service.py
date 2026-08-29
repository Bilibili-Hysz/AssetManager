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
from collections import deque
from contextlib import AbstractContextManager, nullcontext
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import FileSystemChanged

if TYPE_CHECKING:
    from AssetsManager.application.context import LibrarySession
    from AssetsManager.application.reconciliation_queue import ReconciliationQueue


class LibraryWatcherStopTimeout(RuntimeError):
    """Raised when the watcher thread does not stop within its bound."""

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
        reconciliation_queue: "ReconciliationQueue | None" = None,
        stop_timeout: float = 2.0,
    ) -> None:
        self._session = session
        self._interval = interval_seconds
        self._max_directories = max_directories
        self._reconciliation_queue = reconciliation_queue
        self._stop_timeout = stop_timeout
        # Directory path (str) -> st_mtime_ns snapshot built by the last round.
        self._snapshot: dict[str, int] = {}
        # BFS cursor for a partially completed round: directories still to
        # visit when the last round hit the directory budget.  A deque keeps
        # popleft() O(1); a list.pop(0) here was O(n) per dequeue, i.e. O(n²)
        # across a 50k-directory budget.
        self._pending: deque[tuple[str, int]] = deque()
        self._wakeup = threading.Event()
        self._stop_event = threading.Event()
        self._started = False
        self._thread: threading.Thread | None = None
        self._run_stop_event: threading.Event | None = None
        self._run_wakeup: threading.Event | None = None
        self._lock = threading.Lock()

    # ── Lifecycle ────────────────────────────────────────────────

    def start(self) -> bool:
        """Start one polling thread, refusing overlap with a live prior run."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            stop_event = threading.Event()
            wakeup = threading.Event()
            self._stop_event = stop_event
            self._wakeup = wakeup
            self._run_stop_event = stop_event
            self._run_wakeup = wakeup
            self._started = True
            self._thread = threading.Thread(
                target=self._run,
                args=(stop_event, wakeup),
                name="library-watcher",
                daemon=True,
            )
            self._thread.start()
            return True

    def stop(self) -> bool:
        """Stop and bounded-join the polling thread."""
        with self._lock:
            thread = self._thread
            stop_event = self._stop_event
            wakeup = self._wakeup
            stop_event.set()
            wakeup.set()
        if thread is None or thread is threading.current_thread():
            with self._lock:
                self._started = False
                if thread is not threading.current_thread():
                    self._thread = None
            return True
        thread.join(timeout=self._stop_timeout)
        if thread.is_alive():
            raise LibraryWatcherStopTimeout(
                f"Library watcher did not stop within {self._stop_timeout:.3f}s"
            )
        with self._lock:
            if self._thread is thread:
                self._thread = None
                self._run_stop_event = None
                self._run_wakeup = None
                self._started = False
        return True

    # ── Polling loop ─────────────────────────────────────────────

    def _run(
        self, stop_event: threading.Event, wakeup: threading.Event
    ) -> None:
        while not stop_event.is_set():
            if wakeup.wait(self._interval):
                wakeup.clear()
                if stop_event.is_set():
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

    def _enqueue_rescan(self) -> None:
        if self._reconciliation_queue is None or self._session.is_closed:
            return
        try:
            operation = getattr(self._session, "operation", None)
            # Both branches yield a context manager at runtime; getattr on the
            # defensive duck-typed seam erases that statically.
            scope = cast(
                "AbstractContextManager[None]",
                operation() if callable(operation) else nullcontext(),
            )
            with scope:
                self._reconciliation_queue.enqueue_or_merge(
                    path=self._session.root,
                    reason="external_watch",
                    operation_id=f"watch-{uuid4().hex}",
                )
        except Exception:
            _log.exception(
                "Failed to enqueue external watcher rescan for %s",
                self._session.root_str,
            )

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
        queue = self._pending if self._pending else deque([(root, 0)])
        self._pending = deque()

        scanned = 0
        while queue:
            path, _depth = queue.popleft()
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
            self._enqueue_rescan()
            get_event_bus().publish(FileSystemChanged(
                library_root=self._session.root_str,
                session_token=self._session.event_token,
                kind=_KIND,
                paths=tuple(changed),
            ))
        return changed if not baseline else []
