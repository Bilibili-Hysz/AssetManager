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
        self._db = db_conn
        self._index: list[dict] = []
        self._lock = threading.Lock()
        self._scanning = False

    def start_background_scan(self):
        """Start a background thread to scan the library."""
        if self._scanning:
            return
        self._scanning = True
        t = threading.Thread(target=self._scan_all, daemon=True)
        t.start()

    def _scan_all(self):
        """Walk the entire library and build the index."""
        _log.info("Scanning library: %s", self._root)
        index = []
        try:
            for dirpath, dirnames, filenames in os.walk(self._root):
                # Skip hidden directories
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for fname in filenames:
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
            self._index = index
            self._scanning = False
        _log.info("Scan complete: %d files indexed", len(index))

    def search(self, query: str, limit: int = 200) -> list[dict]:
        """Search the index by filename substring."""
        q = query.lower()
        with self._lock:
            results = [f for f in self._index if q in f["name"].lower()]
        return results[:limit]

    def is_scanning(self) -> bool:
        return self._scanning

    def file_count(self) -> int:
        with self._lock:
            return len(self._index)
