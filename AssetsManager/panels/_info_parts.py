"""Instance-independent helper classes extracted from the info panel.

Every symbol here was moved verbatim from ``info.py``; ``InfoPanel`` keeps
thin delegates with the same names, so call sites and behavior are unchanged.
``_FileInfoTask`` refers to ``InfoPanel`` by name only inside methods, which
resolves lazily at call time, so the panel class remains the sole owner.
"""
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QRect, QSize, QPoint, QMimeData, QUrl, QRunnable, QObject
from PySide6.QtWidgets import QLabel, QLayout, QLayoutItem
from PySide6.QtGui import QDrag

from AssetsManager.application.context import LibrarySession
from AssetsManager.core.constants import IMAGE_EXTS

from AssetsManager import i18n

_log = logging.getLogger(__name__)
tr = i18n.tr


class _DragLabel(QLabel):
    """Label that supports click-to-open and drag-to-browser."""
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._drag_url = ""
        self._drag_start = None

    def set_drag_url(self, url: str):
        self._drag_url = url

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._drag_url:
            self._drag_start = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start and self._drag_url:
            if (event.globalPosition().toPoint() - self._drag_start).manhattanLength() > 10:
                self._drag_start = None
                drag = QDrag(self)
                mime = QMimeData()
                mime.setUrls([QUrl(self._drag_url)])
                mime.setText(self._drag_url)
                drag.setMimeData(mime)
                drag.exec(Qt.DropAction.CopyAction)
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_start = None
        super().mouseReleaseEvent(event)


class _PreviewLabel(QLabel):
    view_fullscreen = Signal(str)

    def mouseDoubleClickEvent(self, event):
        self.view_fullscreen.emit(self.toolTip())  # fallback, panel overrides handler
        # Accept the event so it does not propagate to the parent host,
        # whose eventFilter would emit view_fullscreen a second time and
        # open two overlapping viewers.
        event.accept()


class _FlowLayout(QLayout):
    """Wrapping flow layout for tag chips."""
    def __init__(self, parent=None, margin=0, spacing=4):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _do_layout(self, rect, test_only):
        x = rect.x()
        y = rect.y()
        line_height = 0
        spacing = self.spacing()
        for item in self._items:
            widget = item.widget()
            if widget and widget.isHidden():
                continue
            item_size = item.sizeHint()
            next_x = x + item_size.width() + spacing
            if next_x > rect.right() and line_height > 0:
                x = rect.x()
                y += line_height + spacing
                line_height = 0
                next_x = x + item_size.width() + spacing
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item_size))
            x = next_x
            line_height = max(line_height, item_size.height())
        return y + line_height - rect.y() + spacing


def format_info_size(size):
    try:
        size = float(size)
    except Exception:
        return "—"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"


@dataclass(frozen=True)
class _AsyncRequest:
    generation: int
    session: LibrarySession
    path: str


class _FileInfoSignals(QObject):
    result_ready = Signal(object, object)
    preview_ready = Signal(object, object)
    urls_discovered = Signal(object, object)  # scanned path, list of urls


class _FileInfoTask(QRunnable):
    """Background task for heavy file-info operations."""

    def __init__(self, request, controller, library_root,
                 sidebar_depth, branch_depths, classify_cache):
        super().__init__()
        self._request = request
        self._path = request.path
        self._controller = controller
        self._session = request.session
        self._library_root = library_root
        self._sidebar_depth = sidebar_depth
        self._branch_depths = branch_depths
        self._classify_cache = classify_cache
        self.signals = _FileInfoSignals()
        # Both signals are emitted inside run(), so the pool may reclaim the
        # runnable as soon as run() returns; the panel keeps a Python
        # reference (self._pending_task) until the next update.
        self.setAutoDelete(True)

    def _load_preview(self, path, is_dir):
        from AssetsManager.panels.info import InfoPanel
        if is_dir:
            img_path = InfoPanel._first_image_in_dir(path)
            if img_path:
                return InfoPanel._load_preview_pixmap(img_path)
            return None
        suffix = Path(path).suffix.lower()
        if suffix in IMAGE_EXTS:
            return InfoPanel._load_preview_pixmap(path)
        return None

    def run(self):
        try:
            with self._session.operation():
                self._run_scoped()
        except Exception:
            _log.exception("FileInfoTask failed for %s", self._path)

    def _run_scoped(self):
        from AssetsManager.controllers.info_controller import InfoController
        path = self._path
        is_dir = os.path.isdir(path)
        is_project = is_dir and InfoController.is_deepest_folder(
            path, self._library_root, self._sidebar_depth, self._branch_depths)

        if is_project and self._controller:
            # Discovery is read-only and safe in the worker; persisting the
            # urls would publish AssetUrlsChanged from this thread, so the
            # writes are deferred to the UI thread via urls_discovered.
            existing = self._controller.get_urls(path)
            if not existing:
                discovered = self._controller.discover_urls_in_dir(path)
                if discovered:
                    self.signals.urls_discovered.emit(path, discovered)

        dir_summary = self._controller.classify_dir(path, classify_cache=self._classify_cache) if is_dir else None

        if is_dir:
            display_type = tr("info.project") if is_project else tr("info.folder")
            display_size = tr("info.calculating") if os.path.exists(path) else "—"
        else:
            display_type = tr("info.file", ext=Path(path).suffix.lstrip('.').upper())
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            display_size = format_info_size(size) if size else "—"

        try:
            from datetime import datetime
            mtime = os.path.getmtime(path)
            modified_display = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        except OSError:
            modified_display = "—"

        parent_path = str(Path(path).parent)

        file_info = self._controller.get_file_info(
            path,
            is_dir=is_dir,
            file_type=display_type,
            size_display=display_size,
            modified_display=modified_display,
            parent_path=parent_path,
            dir_summary=dir_summary,
            is_project=is_project,
        )

        self.signals.result_ready.emit(self._request, file_info)

        preview = self._load_preview(path, is_dir)
        self.signals.preview_ready.emit(self._request, preview)


class _LinkScanSignals(QObject):
    done = Signal(object, object)  # discovered urls, scanned path


class _LinkScanTask(QRunnable):
    """Background URL discovery for the manual scan action."""

    def __init__(self, controller, path):
        super().__init__()
        # Auto-delete: the pool reclaims the C++ object after run(); the
        # panel's Python reference (self._link_scan_task) keeps the signals
        # object alive until the queued delivery is consumed on the UI
        # thread, so no task leak accumulates across scans.
        self.setAutoDelete(True)
        self._controller = controller
        self._path = path
        self.signals = _LinkScanSignals()

    def run(self):
        try:
            discovered = self._controller.discover_urls_in_dir(self._path)
        except Exception:
            _log.exception("Manual URL scan failed for %s", self._path)
            discovered = []
        self.signals.done.emit(discovered, self._path)
