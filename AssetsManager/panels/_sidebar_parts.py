"""Instance-independent sidebar helpers extracted from the sidebar panel.

Every symbol here was moved verbatim from ``sidebar.py``; ``SidebarPanel`` keeps
thin delegates that re-import these names, so call sites and behavior are
unchanged. ``VTYPE_FS`` lives here because the module-level helper ``_fs_level``
needs it; the panel imports it back so the existing name keeps resolving.
"""
import os

from PySide6.QtCore import Qt, Signal, QRunnable, QObject
from PySide6.QtWidgets import QTreeWidgetItem

VTYPE_FS = "fs"


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


class _PreloadTask(QRunnable):
    def __init__(self, root_paths, text, gen, root, max_depth=2):
        super().__init__()
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
        self.signals = _PreloadSignals()

    def run(self):
        results = []
        for root_path in self._root_paths:
            self._scan_recursive(root_path, 0, results)
        self.signals.done.emit(self._text, results, self._gen, self._root)

    def _scan_recursive(self, path, depth, results):
        if depth >= self._max_depth:
            return
        try:
            entries = sorted(os.scandir(path),
                             key=lambda e: (not e.is_dir(), e.name.lower()))
            results.append((path, [(e.name, e.path, e.is_dir()) for e in entries
                                   if not e.name.startswith(".")]))
            for entry in entries:
                if entry.is_dir() and not entry.name.startswith("."):
                    self._scan_recursive(entry.path, depth + 1, results)
        except OSError:
            pass
