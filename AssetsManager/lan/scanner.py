"""Directory scanner — builds an in-memory file index for fast API responses."""
import logging
import os
import threading
from pathlib import Path

_log = logging.getLogger(__name__)


class DirectoryScanner:
    """Scans the library root and builds an in-memory index.

    The index is used by the search API endpoint for fast full-text
    filename search without repeated os.walk calls.
    """

    def __init__(self, library_root: str, db_conn):
        self._root = Path(library_root)
        # db_conn is kept for backward compatibility with existing callers
        # (e.g. server.py and test_lan_api.py pass a db connection). The
        # scanner is purely filesystem-based and does not use it.
        self._db = db_conn  # noqa: F841 - retained for API compatibility
        self._index: list[dict] = []
        self._lock = threading.Lock()
        self._scanning = False
        self._stop_event = threading.Event()
        self._scan_thread: threading.Thread | None = None
        # Scan generation: stop() only joins for 2s, so a superseded worker
        # may still be alive when the next scan starts. A stale worker must
        # neither publish its partial index nor clear the new scan's
        # _scanning flag (which would let a second start spawn a third
        # concurrent scan, and would release the gallery prewarm early).
        self._generation = 0

    def start_background_scan(self):
        """Start a background thread to scan the library."""
        with self._lock:
            if self._scanning:
                return
            self._scanning = True
            self._generation += 1
            generation = self._generation
        self._stop_event.clear()
        t = threading.Thread(target=self._scan_all, args=(generation,), daemon=True)
        self._scan_thread = t
        t.start()

    def stop(self):
        """Cancel a running scan and wait for the worker to finish (max 2s).

        Safe to call repeatedly; a finished scan has nothing to cancel.
        """
        self._stop_event.set()
        t = self._scan_thread
        if t is not None and t.is_alive():
            t.join(timeout=2)

    def _on_walk_error(self, exc: OSError) -> None:
        """os.walk error callback: log permission errors instead of silently skipping."""
        _log.warning("scan permission error: %s", exc)

    def _scan_all(self, generation: int):
        """Walk the entire library and build the index."""
        _log.info("Scanning library: %s", self._root)
        index = []
        try:
            for dirpath, dirnames, filenames in os.walk(
                self._root, onerror=self._on_walk_error
            ):
                if self._stop_event.is_set():
                    break
                # Skip hidden directories
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for fname in filenames:
                    if self._stop_event.is_set():
                        break
                    if fname.startswith("."):
                        continue
                    fp = os.path.join(dirpath, fname)
                    rel = os.path.relpath(fp, self._root).replace("\\", "/")
                    ext = os.path.splitext(fname)[1].lower()
                    try:
                        stat = os.stat(fp)
                        index.append({
                            "name": fname,
                            "path": rel,
                            "size": stat.st_size,
                            "modified": stat.st_mtime,
                            "extension": ext,
                        })
                    except OSError:
                        pass
        except OSError as e:
            _log.warning("Library scan failed: %s", e)

        with self._lock:
            if generation != self._generation:
                # A newer scan started while this one was still walking:
                # neither publish the stale index nor clear the new scan's
                # _scanning flag.
                return
            # If the scan was cancelled, do NOT publish the partial index —
            # keep the previous (complete) index so callers never see a
            # half-built one after stop().
            if not self._stop_event.is_set():
                self._index = index
            self._scanning = False
        _log.info(
            "Scan finished: %d files indexed (cancelled=%s)",
            len(index),
            self._stop_event.is_set(),
        )

    def search(self, query: str, limit: int = 200) -> list[dict]:
        """Search the index by filename substring.

        Returns a new list; the internal index is never handed out.
        """
        # Fail-safe: non-string queries (None, numbers, ...) return an
        # empty list instead of raising, preserving index-only semantics.
        if not isinstance(query, str):
            return []
        q = query.lower()
        with self._lock:
            # Build and slice inside the lock, and return a fresh list so
            # callers can never share/mutate the internal index. Order
            # matches scan order (no sorting — existing semantics).
            return [f for f in self._index if q in f["name"].lower()][:limit]

    def is_scanning(self) -> bool:
        with self._lock:
            return self._scanning

    def file_count(self) -> int:
        with self._lock:
            return len(self._index)

    def invalidate(self):
        """Drop the in-memory index.

        Call after the underlying library changes (files added, removed or
        renamed) so stale search results are not served. The next
        start_background_scan() rebuilds the index from disk.
        """
        with self._lock:
            self._index = []
