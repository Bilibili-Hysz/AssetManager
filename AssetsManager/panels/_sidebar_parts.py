"""Instance-independent sidebar helpers extracted from the sidebar panel.

Every symbol here was moved verbatim from ``sidebar.py``; ``SidebarPanel`` keeps
thin delegates that re-import these names, so call sites and behavior are
unchanged. ``VTYPE_FS`` lives here because the module-level helper ``_fs_level``
needs it; the panel imports it back so the existing name keeps resolving.
"""
import os

from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtWidgets import QTreeWidgetItem

from AssetsManager.core.workers import CancellationToken, CancellableRunnable

VTYPE_FS = "fs"

# Cancellation is polled once per this many visited entries instead of once
# per entry.  The token check takes a lock; a whole-library walk otherwise
# pays one lock acquire per file/directory, which measurably slows the hot
# path on large trees.  A cancelled task notices within roughly one scandir
# worth of work (≤ _WALK_POLL_EVERY extra entries), which keeps superseded
# preloads from hogging their worker slot.
_WALK_POLL_EVERY = 64


def _fs_level(item: QTreeWidgetItem) -> int:
    """Return how many FS levels deep this item is (1 = top-level FS item)."""
    level = 0
    it = item
    while it:
        vt = it.data(0, Qt.ItemDataRole.UserRole + 1)
        if vt == VTYPE_FS:
            level += 1
        it = it.parent()
    return level


class _PreloadSignals(QObject):
    # text, results, search generation, library root at schedule time
    done = Signal(str, object, int, object)


class _PreloadTask(CancellableRunnable):
    def __init__(self, root_paths, text, gen, root, max_depth=2,
                 cancel_token: CancellationToken | None = None):
        super().__init__(generation=gen, cancel_token=cancel_token)
        # Auto-delete: the pool reclaims the C++ runnable once run() returns,
        # so a task replaced by a newer search (self._preload_task = None)
        # cannot leak. done is emitted inside run() and the panel keeps the
        # Python reference (self._preload_task) until the next search, so the
        # queued delivery still reaches _on_preload_done.
        self.setAutoDelete(True)
        self._root_paths = root_paths
        self._text = text
        self._gen = gen
        self._root = root
        self._max_depth = max_depth
        self._walk_checks = 0
        self.signals = _PreloadSignals()

    def cancel(self) -> None:
        """Cooperatively cancel this preload before a newer search replaces it."""
        self.cancel_token.cancel()

    def _poll_cancelled(self) -> bool:
        """Sample the cancellation token every ``_WALK_POLL_EVERY`` entries."""
        self._walk_checks += 1
        if self._walk_checks % _WALK_POLL_EVERY:
            return False
        return self.is_cancelled()

    def run(self):
        results = []
        for root_path in self._root_paths:
            if self.is_cancelled():
                break
            self._scan_recursive(root_path, 0, results)
        if not self.is_cancelled():
            self.signals.done.emit(self._text, results, self._gen, self._root)

    def _scan_recursive(self, path, depth, results):
        if self.is_cancelled() or depth >= self._max_depth:
            return
        try:
            entries = sorted(os.scandir(path),
                             key=lambda e: (not e.is_dir(), e.name.lower()))
            row = []
            for entry in entries:
                if not entry.name.startswith("."):
                    row.append((entry.name, entry.path, entry.is_dir()))
                if self._poll_cancelled():
                    return
            results.append((path, row))
            for entry in entries:
                if self._poll_cancelled():
                    return
                if entry.is_dir() and not entry.name.startswith("."):
                    self._scan_recursive(entry.path, depth + 1, results)
        except OSError:
            pass
