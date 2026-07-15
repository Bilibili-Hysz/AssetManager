"""File list panel — core infrastructure for file browser panels.

Provides: toolbar, breadcrumb, search, status bar, navigation, actions, thumbnails.
View creation is delegated to subclasses (QWidgetFileListPanel or legacy FileListPanel).

Architecture:
  _common.py       — shared constants (FILTER_CATEGORIES, ZOOM_PRESETS, natural_key)
  _model.py        — FileSystemModel (QAbstractListModel)
  _loader.py       — ThumbnailLoader + async disk-write thread
  _navigation.py   — NavigationMixin (breadcrumb, history, FS watcher)
  _actions.py      — ActionsMixin (context menu, file ops, undo, tags)
  _grid_widget.py  — FileListGridWidget (QWidget canvas)
  __init__.py      — QWidgetFileListPanel (default) + legacy FileListPanel
"""
import os
import logging
from pathlib import Path

from PySide6.QtCore import (
    Qt, Signal, QEvent, QRect,
    QSize, QUrl, QMimeData, QTimer, QPoint,
)
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QPen, QPainterPath
from PySide6.QtWidgets import (
    QPushButton, QHBoxLayout, QComboBox, QLabel, QWidget, QApplication,
    QListView, QTreeWidgetItem,
)

from AssetsManager.panels.base import PanelContent
from AssetsManager.core.signal_bus import get as bus
from AssetsManager.core import themes
from AssetsManager.core.color_utils import alpha
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager import i18n

from AssetsManager.panels.file_list._model import FileSystemModel
from AssetsManager.panels.file_list._loader import ThumbnailLoader
from AssetsManager.panels.file_list._common import IMAGE_EXTS, FILTER_CATEGORY_LABELS, ZOOM_PRESETS, natural_key
from AssetsManager.panels.file_list._navigation import NavigationMixin
from AssetsManager.panels.file_list._actions import ActionsMixin
from AssetsManager.panels.file_list._toast import Toast

_log = logging.getLogger(__name__)
tr = i18n.tr
_natural_key = natural_key


class FileListPanel(NavigationMixin, ActionsMixin, PanelContent):
    file_selected = Signal(object)
    file_double_clicked = Signal(str)
    folder_entered = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.content_layout.setContentsMargins(1, 0, 1, 1)

        self._current = Path.home() / "Documents"
        self._root = None
        self._history: list[str] = []
        self._cached_total_sz: int = -1
        self._forward_list: list[str] = []
        self._thumb_size = scaled_px(96)
        self._view_memory: dict[str, str] = {}
        self._first_image_cache: dict[str, str | None] = {}
        self._first_image_cache_max = 5000
        self._last_click_row: int = -1
        self._last_tree_item: QTreeWidgetItem | None = None
        self._drag_origin_pos = None
        self._drag_started = False
        self._scoped_services = None

        # Controller for non-UI business logic
        from AssetsManager.controllers.file_list_controller import FileListController
        self._controller = FileListController()

        # Actions mixin state (clipboard, undo)
        self._init_actions()

        self._model = FileSystemModel()
        self._model.modelReset.connect(self._invalidate_size_cache)
        self._model.dir_size_ready.connect(self._on_dir_size_ready)
        self._model.dir_size_ready.connect(self._on_detail_dir_size_ready)
        self._loader = ThumbnailLoader(size=self._thumb_size)
        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(self._cleanup_undo_dir)

        # ── Panel header ─────────────────────────────────────────

        t = themes.get()
        self._header = QWidget()
        self._header.setStyleSheet(
            f"background: {themes.header_for_dock()}; "
            f"border: 1px solid {t['border']}; "
            f"border-top-left-radius: {scaled_px(7)}px; border-top-right-radius: {scaled_px(7)}px; ")
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(scaled_px(10), scaled_px(3), scaled_px(6), scaled_px(3))
        header_layout.setSpacing(scaled_px(4))

        self._header_title = QLabel(tr("filelist.header"))
        self._header_title.setStyleSheet(
            f"color: {t['heading']}; font-size: {scaled_pt(12)}px; font-weight: bold; "
            f"background: transparent; border: none; padding: 2px 4px;")
        header_layout.addWidget(self._header_title)
        header_layout.addStretch()
        self.content_layout.addWidget(self._header)

        # ── Toolbar ─────────────────────────────────────────────

        tb = QHBoxLayout()
        tb.setContentsMargins(scaled_px(4), scaled_px(4), scaled_px(4), scaled_px(2))
        tb.setSpacing(scaled_px(3))

        self._nav_buttons = []
        self._nav_buttons.append(self._make_nav_button("◀", tr("filelist.back"), self._go_back, font_size=10))
        self._nav_buttons.append(self._make_nav_button("▶", tr("filelist.forward"), self._go_forward, font_size=10))
        self._nav_buttons.append(self._make_nav_button("▲", tr("filelist.up"), self._go_up, font_size=10))
        for b in self._nav_buttons:
            tb.addWidget(b)

        self._sort_combo = QComboBox()
        for key, label in (
            ("name", tr("filelist.sort.name")),
            ("date", tr("filelist.sort.date")),
            ("size", tr("filelist.sort.size")),
            ("type", tr("filelist.sort.type")),
        ):
            self._sort_combo.addItem(label, key)
        self._sort_combo.currentTextChanged.connect(self._on_sort_changed)
        tb.addWidget(self._sort_combo)

        self._sort_btn = self._make_nav_button("↑", tr("filelist.sort_dir"), self._toggle_sort_dir, font_size=14)
        tb.addWidget(self._sort_btn)

        self._filter_combo = QComboBox()
        for key, label in FILTER_CATEGORY_LABELS:
            self._filter_combo.addItem(label, key)
        self._filter_combo.currentTextChanged.connect(self._on_filter_changed)
        tb.addWidget(self._filter_combo)

        self._view_combo = QComboBox()
        self._view_combo.addItem(tr("filelist.view.grid"), userData="Grid")
        self._view_combo.addItem(tr("filelist.view.details"), userData="Details")
        self._view_combo.currentIndexChanged.connect(self._on_view_changed)
        tb.addWidget(self._view_combo)

        self._zoom_combo = QComboBox()
        for sz in ZOOM_PRESETS:
            self._zoom_combo.addItem(f"{sz}px")
        self._zoom_combo.setCurrentIndex(2)
        self._zoom_combo.currentTextChanged.connect(self._on_zoom_changed)
        tb.addWidget(self._zoom_combo)

        tb.addStretch()
        self._hidden_btn = self._make_nav_button("◉", tr("filelist.hidden"), self._toggle_hidden, font_size=12)
        tb.addWidget(self._hidden_btn)
        refresh = self._make_nav_button("⟳", tr("filelist.refresh"), self._do_refresh, font_size=15)
        tb.addWidget(refresh)

        # Search — inline at end of toolbar
        from PySide6.QtWidgets import QLineEdit
        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("filelist.filter_placeholder"))
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search_changed)
        self._search.installEventFilter(self)
        self._setup_search_history(self._search)
        tb.addWidget(self._search, stretch=1)
        self._search_timer: QTimer | None = None
        self.content_layout.addLayout(tb)

        # ── Breadcrumb ──────────────────────────────────────────

        self._breadcrumb = QWidget()
        self._breadcrumb.setStyleSheet("background: transparent;")
        self._bc_layout = QHBoxLayout(self._breadcrumb)
        self._bc_layout.setContentsMargins(scaled_px(4), 0, scaled_px(4), 0)
        self._bc_layout.setSpacing(0)
        self.content_layout.addWidget(self._breadcrumb)

        # ── Views (set by subclass) ────────────────────────────
        self._list_view = None
        self._detail_view = None
        self._loader.thumbnail_ready.connect(self._on_thumbnail_ready)
        self._connect_bus(bus().theme_changed, self._on_theme_changed)

        # Scroll debounce — 100ms after scroll stops before loading thumbnails
        self._scroll_debounce = QTimer(self)
        self._scroll_debounce.setSingleShot(True)
        self._scroll_debounce.setInterval(100)
        self._scroll_debounce.timeout.connect(self._load_visible)
        self.setFocusProxy(self._search)

        # ── Status bar ──────────────────────────────────────────

        self._status_bar = QWidget()
        self._status_bar.setFixedHeight(scaled_px(28))
        sl = QHBoxLayout(self._status_bar)
        sl.setContentsMargins(scaled_px(10), scaled_px(4), scaled_px(10), scaled_px(4))
        sl.setSpacing(scaled_px(8))
        self._status = QLabel("")
        sl.addWidget(self._status)
        sl.addStretch()
        self._fst_status_style()
        self.content_layout.addWidget(self._status_bar)

    def initialize_navigation(self):
        """Start filesystem watching after views exist."""
        self._start_fs_watcher()

    def _fst_status_style(self):
        t = themes.get()
        self._status_bar.setStyleSheet(
            f"background: transparent; "
            f"border-top: 1px solid {t['border']};")
        self._status.setStyleSheet(
            f"color: {t['muted']}; font-size: {scaled_pt(11)}px; background: transparent;")

    def set_scoped_services(self, services):
        """Bind library-scoped services resolved by MainWindow."""
        self._scoped_services = services
        self._root = services.session.root
        self._model.set_library_root(services.session.root_str)
        self._model.set_metadata_service(services.metadata_service)
        self._loader.set_cache_db(services.session.db_conn)
        self._loader.set_cache_dir(services.session.thumb_dir_str)
        self._loader.orphan_cleanup()
        if hasattr(services, "undo_service"):
            self._undo_svc = services.undo_service
        self._controller.set_file_operations(
            services.file_operation_service, self._undo_svc)

    def _get_scoped_services(self):
        return self._scoped_services

    def _get_file_operation_service(self):
        scoped = self._scoped_services
        if scoped is not None:
            return scoped.file_operation_service
        from AssetsManager.application import FileOperationService
        return FileOperationService()

    def _get_tag_service(self):
        if not self._lib_root:
            raise RuntimeError("FileListPanel requires a library root for TagService")
        scoped = self._scoped_services
        if scoped is None:
            raise RuntimeError("FileListPanel scoped services not injected")
        return scoped.tag_service

    def _get_tag_store(self, root: str | None = None):
        scoped = self._scoped_services
        if scoped is not None:
            return scoped.session.tag_store
        # Lightweight fallback for tests / bootstrap-free contexts
        target = root or self._lib_root or str(self._current)
        if not target:
            return None
        from AssetsManager.core.database import DatabaseManager
        from AssetsManager.core.singleton import ThreadSafeSingleton
        from AssetsManager.core.tag_store import TagStore
        mgr = ThreadSafeSingleton.get(DatabaseManager)
        try:
            conn = mgr.connection_for(target)
            return TagStore(str(Path(target).resolve()), db_conn=conn)
        except Exception:
            return None

    def _configure_library_runtime(self, root: str):
        """Bind file-list runtime helpers to a library root."""
        scoped = self._scoped_services
        if scoped is None:
            from AssetsManager.panels._service_access import require_scoped_services
            try:
                scoped = require_scoped_services(root, consumer="FileListPanel")
            except Exception:
                raise RuntimeError("FileListPanel scoped services not injected before navigate_to")
        self.set_scoped_services(scoped)
        self._loader.orphan_cleanup()

    def refresh_header(self):
        """Re-apply header bar styling (called on bg opacity changes)."""
        t = themes.get()
        self._header.setStyleSheet(
            f"background: {themes.header_for_dock()}; "
            f"border: 1px solid {t['border']}; "
            f"border-top-left-radius: {scaled_px(7)}px; border-top-right-radius: {scaled_px(7)}px; ")

    # ── View switching ──────────────────────────────────────────

    @property
    def _view_mode(self):
        return self._view_combo.currentData() or self._view_combo.currentText()

    def _apply_list_theme(self):
        if self._list_view:
            self._list_view.setStyleSheet(
                "QListView { background: transparent; border: none; }")

    def _sync_selection_anim(self):
        """Forward selection state to delegate for animation. Override in subclass."""
        pass

    def _on_theme_changed(self, _name):
        t = themes.get()
        self._header.setStyleSheet(
            f"background: {themes.header_for_dock()}; "
            f"border: 1px solid {t['border']}; "
            f"border-top-left-radius: {scaled_px(7)}px; border-top-right-radius: {scaled_px(7)}px; ")
        self._header_title.setStyleSheet(
            f"color: {t['heading']}; font-size: {scaled_pt(12)}px; font-weight: bold; "
            f"background: transparent; border: none; padding: 2px 4px;")
        self._fst_status_style()
        for btn in self._nav_buttons:
            btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {t['body']}; "
                f"border: none; padding: 0; font-size: {scaled_pt(10)}px; }} "
                f"QPushButton:hover {{ background: {alpha(t['panel'], 0.50)}; border-radius: {scaled_px(3)}px; color: {t['heading']}; }}")

    def _update_thumb_cache_dir(self):
        if self._root:
            self._configure_library_runtime(str(self._root))
        else:
            self._loader.set_cache_db(None)
            self._loader.set_cache_dir("")

    def _toggle_sort_dir(self):
        self._model._sort_asc = not self._model._sort_asc
        self._sort_btn.setText("↑" if self._model._sort_asc else "↓")
        self._model.set_sort(self._sort_key(), self._model._sort_asc)
        if self._view_mode == "Details":
            self._populate_details()
        self._load_visible()

    def _toggle_hidden(self):
        self._model._show_hidden = not self._model._show_hidden
        self._post_refresh()
        self._hidden_btn.setText("◉" if self._model._show_hidden else "•")

    def _post_refresh(self):
        """Refresh model and update display — call after any data change."""
        self._model.refresh()
        if self._view_mode == "Details":
            self._populate_details()
        else:
            self._load_visible()
        self._hidden_btn.setText("◉" if self._model._show_hidden else "•")
        self._update_status()

    def _on_view_changed(self, _index):
        mode = self._view_mode
        self._view_memory[str(self._current)] = mode
        self._loader.set_size(self._thumb_size)
        is_detail = mode == "Details"
        if self._list_view:
            self._list_view.setVisible(not is_detail)
        if self._detail_view:
            self._detail_view.setVisible(is_detail)
        if hasattr(self, '_grid_delegate') and self._grid_delegate:
            if mode == "Grid" and self._list_view:
                self._grid_delegate.set_view_mode("Grid")
                if hasattr(self._list_view, 'setViewMode'):
                    self._list_view.setViewMode(QListView.ViewMode.IconMode)
                    self._list_view.setIconSize(QSize(self._thumb_size, self._thumb_size))
                    self._list_view.scheduleDelayedItemsLayout()
        if is_detail:
            self._populate_details()
        else:
            self._load_visible()

    def _on_zoom_changed(self, val):
        """Animate thumb size transition over 200ms for smooth zoom."""
        from PySide6.QtCore import QVariantAnimation, QEasingCurve
        target = int(val.replace("px", ""))
        if not hasattr(self, '_zoom_anim'):
            self._zoom_anim = None

        if self._zoom_anim and self._zoom_anim.state() == QVariantAnimation.State.Running:
            self._zoom_anim.stop()

        start = self._thumb_size
        if start == target:
            return

        if self._list_view and hasattr(self._list_view, 'set_zoom_in_progress'):
            self._list_view.set_zoom_in_progress(True)
        self._zoom_anim = QVariantAnimation()
        self._zoom_anim.setDuration(180)
        self._zoom_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._zoom_anim.setStartValue(start)
        self._zoom_anim.setEndValue(target)
        self._zoom_anim.valueChanged.connect(self._on_zoom_frame)
        self._zoom_anim.finished.connect(self._on_zoom_done)
        self._zoom_anim.start()

    def _on_zoom_frame(self, size: int):
        self._thumb_size = size
        if self._view_mode == "Grid":
            if self._list_view:
                self._list_view.setIconSize(QSize(size, size))

    def _on_zoom_done(self):
        if self._list_view and hasattr(self._list_view, 'set_zoom_in_progress'):
            self._list_view.set_zoom_in_progress(False)
        self._loader.set_size(self._thumb_size)
        if hasattr(self, '_grid_delegate') and self._grid_delegate:
            self._grid_delegate.invalidate_scaled_cache()
        if self._view_mode == "Grid":
            if hasattr(self, '_grid_delegate') and self._grid_delegate:
                self._grid_delegate.set_thumb_size(self._thumb_size)
            if self._list_view:
                self._list_view.scheduleDelayedItemsLayout()
        self._load_visible()

    def _wheel_zoom_evt(self, event):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            idx = self._zoom_combo.currentIndex()
            from AssetsManager.panels.file_list._common import ZOOM_PRESETS
            if delta > 0 and idx < len(ZOOM_PRESETS) - 1:
                self._zoom_combo.setCurrentIndex(idx + 1)
            elif delta < 0 and idx > 0:
                self._zoom_combo.setCurrentIndex(idx - 1)
            return
        if self._list_view:
            from PySide6.QtWidgets import QListView
            QListView.wheelEvent(self._list_view, event)

    def _on_sort_changed(self):
        self._model.set_sort(self._sort_key(), self._model._sort_asc)
        if self._view_mode == "Details":
            self._populate_details()
        self._load_visible()

    def _on_filter_changed(self):
        cat = self._filter_key()
        text = self._search.text().lower()
        self._model.set_filter(text=text, category=cat)
        self._hidden_btn.setText("◉" if self._model._show_hidden else "•")
        self._update_status()
        if self._view_mode == "Details":
            self._populate_details()
        self._load_visible()

    def _on_search_changed(self, text):
        """Debounce search to avoid O(n) scandir on every keystroke."""
        self._model._filter_text = text.lower()
        if self._search_timer is None:
            self._search_timer = QTimer(self)
            self._search_timer.setSingleShot(True)
            self._search_timer.timeout.connect(self._apply_search)
        self._search_timer.start(200)

    def _apply_search(self):
        self._model.set_filter(
            text=self._search.text().lower(),
            category=self._filter_key())
        self._hidden_btn.setText("◉" if self._model._show_hidden else "•")
        self._update_status()
        if self._view_mode == "Details":
            self._populate_details()
        self._load_visible()
        self._save_search_term(self._search.text())
        # Show search result count
        text = self._search.text().strip()
        if text:
            count = self._model.rowCount()
            self._toast(f"{count} results for \"{text}\"")

    def _toast(self, text: str):
        """Show a brief notification overlay."""
        Toast(text, parent=self._list_view, duration_ms=2000)

    def _sort_key(self):
        return self._sort_combo.currentData() or self._sort_combo.currentText()

    def _filter_key(self):
        return self._filter_combo.currentData() or self._filter_combo.currentText()

    def _do_refresh(self):
        self._loader.clear_queue()
        self._loader.clear_cache()
        self._post_refresh()

    # ── Search history ────────────────────────────────────────

    def _setup_search_history(self, line_edit):
        from PySide6.QtWidgets import QCompleter
        from AssetsManager.controllers.file_list_controller import FileListController
        history = FileListController.get_search_history()
        if history:
            completer = QCompleter(history, line_edit)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            line_edit.setCompleter(completer)

    @staticmethod
    def _save_search_term(term: str):
        from AssetsManager.controllers.file_list_controller import FileListController
        FileListController.save_search_term(term)

    # ── Thumbnail loading ───────────────────────────────────────

    def _load_visible(self):
        """Load thumbnails for visible items. Override in subclass."""
        pass

    def _on_thumbnail_ready(self, row: int, path: str, img):
        """Main-thread handler: convert QImage to QPixmap."""
        if img is None or img.isNull():
            return
        pixmap = QPixmap.fromImage(img)
        idx = self._model.index(row, 0)
        if not idx.isValid():
            return
        if self._model.path_at(row) != path:
            return
        self._model._raw_pixmaps[path] = pixmap
        self._model.setData(idx, QIcon(pixmap), Qt.ItemDataRole.DecorationRole)

    def _flush_thumb_batch(self):
        """Emit a single dataChanged covering all rows that received thumbnails. Override in subclass."""
        pass

    def _start_fade_timer(self):
        """Start fade-in animation timer. Override in subclass."""
        pass

    @staticmethod
    def _first_image_in(dir_path: str) -> str | None:
        try:
            for i, entry in enumerate(os.scandir(dir_path)):
                if i > 500:
                    break
                if entry.is_file() and Path(entry.name).suffix.lower() in IMAGE_EXTS:
                    return entry.path
        except OSError:
            pass
        return None

    def _first_image_cached(self, dir_path: str) -> str | None:
        if dir_path in self._first_image_cache:
            return self._first_image_cache[dir_path]
        result = self._first_image_in(dir_path)
        if len(self._first_image_cache) >= self._first_image_cache_max:
            self._first_image_cache.clear()
        self._first_image_cache[dir_path] = result
        return result

    def _on_dir_size_ready(self, dir_path: str, size_str: str, gen: int = 0):
        """Handle async directory size result — update subtitle and refresh affected row."""
        self._model._pending_dir_sizes.discard(dir_path)
        if gen and gen != self._model._dir_size_gen:
            return
        if dir_path not in self._model._subtitle_cache:
            return
        self._model._subtitle_cache[dir_path] = size_str
        row = self._model._path_index.get(dir_path, -1)
        if row >= 0:
            idx = self._model.index(row, 0)
            if idx.isValid():
                self._model.dataChanged.emit(idx, idx, [FileSystemModel.SUBTITLE_ROLE])

    # ── Details view ────────────────────────────────────────────

    def _populate_details(self):
        """Populate detail tree in chunks to avoid blocking the UI thread."""
        if not self._detail_view:
            return
        self._detail_view.setUpdatesEnabled(False)
        self._detail_view.setSortingEnabled(False)
        self._detail_view.clear()
        # Use _lib_root if available, otherwise current directory for tag access
        root = self._lib_root or str(self._current)
        self._detail_store = self._get_tag_store(root)
        self._detail_index = 0
        self._detail_total = self._model.rowCount()
        self._detail_snapshot_id = id(self._model._entries)  # detect stale chunks
        self._populate_details_chunk()

    def _populate_details_chunk(self):
        import datetime
        # Abort if model changed since _populate_details was called
        if id(self._model._entries) != self._detail_snapshot_id:
            return
        CHUNK = 100
        store = self._detail_store
        end = min(self._detail_index + CHUNK, self._detail_total)
        for i in range(self._detail_index, end):
            entry = self._model._entries[i]
            name = entry.name
            is_dir = entry.is_dir()
            path = entry.path
            icon = "📁 " if is_dir else "  "
            if is_dir:
                # Read from subtitle cache (async result) first, then fallback to DIR_SIZE_ROLE
                sz = self._model._subtitle_cache.get(path)
                if not sz or sz == "...":
                    sz = self._model.data(self._model.index(i, 0), FileSystemModel.DIR_SIZE_ROLE)
                size = sz if sz else "..."
            else:
                try:
                    size = f"{self._model._cached_stat(entry).st_size:,}"
                except (OSError, AttributeError):
                    size = "—"
            try:
                st = self._model._cached_stat(entry)
                if st.st_mtime > 0:
                    date = datetime.datetime.fromtimestamp(st.st_mtime).strftime('%Y-%m-%d')
                else:
                    date = "—"
            except (OSError, AttributeError, ValueError, OverflowError):
                date = "—"
            tags_text = ", ".join(store.get_tags(path)[:3]) if store and not is_dir else ""
            ext = Path(name).suffix.upper() if not is_dir else tr("filelist.prop_folder")
            item = QTreeWidgetItem([f"{icon}{name}", ext, size, date, tags_text])
            item.setData(0, Qt.ItemDataRole.UserRole, path)
            self._detail_view.addTopLevelItem(item)
        self._detail_index = end
        if self._detail_index < self._detail_total:
            QTimer.singleShot(0, self._populate_details_chunk)
        else:
            self._detail_view.setSortingEnabled(True)
            self._detail_view.setUpdatesEnabled(True)
            self._update_status()

    def _on_detail_dir_size_ready(self, dir_path: str, size_str: str, gen: int = 0):
        """Update Detail view when async directory size computation completes."""
        if not self._detail_view:
            return
        if gen and gen != self._model._dir_size_gen:
            return
        for i in range(self._detail_view.topLevelItemCount()):
            item = self._detail_view.topLevelItem(i)
            if item and item.data(0, Qt.ItemDataRole.UserRole) == dir_path:
                item.setText(2, size_str)
                break

    def _on_detail_header_clicked(self, col: int):
        """Tweak column widths after sort for better readability."""
        self._detail_view.resizeColumnToContents(col)

    # ── Status ──────────────────────────────────────────────────

    def _invalidate_size_cache(self):
        if self._model.rowCount():
            self._compute_total_sz()
        self._update_status()

    def _compute_total_sz(self):
        total_sz = 0
        for i in range(self._model.rowCount()):
            e = self._model.entry_at(i)
            if e and not e.is_dir():
                try:
                    total_sz += self._model._cached_stat(e).st_size
                except (OSError, AttributeError):
                    pass
        self._cached_total_sz = total_sz

    def _update_status(self):
        total = self._model.rowCount()
        if self._view_mode == "Details" and self._detail_view:
            sel = len(self._detail_view.selectedItems())
        elif self._list_view:
            sel = len(self._list_view.selectionModel().selectedRows())
        else:
            sel = 0
        total_sz = self._cached_total_sz
        sz_str = ""
        if total_sz > 0:
            sz_str = f"  |  {FileSystemModel._fmt_size(total_sz)}"
        if sel:
            self._status.setText(f"{sel} selected / {total} items{sz_str}  |  {self._view_mode}")
        else:
            self._status.setText(f"{total} items{sz_str}  |  {self._view_mode}")

    # ── Keyboard ────────────────────────────────────────────────

    def eventFilter(self, obj, event):
        t = event.type()
        if t == QEvent.Type.DragEnter:
            return self._on_drag_enter(event)
        if t == QEvent.Type.DragMove:
            return self._accept_drag(event)
        if t == QEvent.Type.Drop:
            return self._on_drop(event)
        if t == QEvent.Type.KeyPress:
            return self._handle_key(event)
        if t == QEvent.Type.Wheel and self._list_view and obj is self._list_view.viewport():
            if event.modifiers() != Qt.KeyboardModifier.ControlModifier:
                self._smooth_scroll(event)
                return True
        # External drag initiation — must intercept BEFORE the view's rubber band
        if not hasattr(self, '_list_view') or not hasattr(self, '_detail_view'):
            return super().eventFilter(obj, event)
        lv = self._list_view
        dv = self._detail_view
        is_list = lv is not None and (obj is lv or (hasattr(lv, 'viewport') and obj is lv.viewport()))
        is_detail = dv is not None and (obj is dv or (hasattr(dv, 'viewport') and obj is dv.viewport()))
        if is_list or is_detail:
            if t == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                if is_list:
                    idx = self._list_view.indexAt(event.pos())
                    if idx.isValid() and idx in self._list_view.selectionModel().selectedRows():
                        self._drag_origin_pos = event.pos()
                        self._drag_started = False
                        return True
                    else:
                        self._reset_drag_state()
                else:
                    idx = self._detail_view.indexAt(event.pos())
                    if idx.isValid() and self._detail_view.selectionModel().isSelected(idx):
                        self._drag_origin_pos = event.pos()
                        self._drag_started = False
                        return True
                    else:
                        self._reset_drag_state()
            if t == QEvent.Type.MouseMove and self._drag_origin_pos is not None:
                if not self._drag_started and event.buttons() & Qt.MouseButton.LeftButton:
                    dist = (event.pos() - self._drag_origin_pos).manhattanLength()
                    if dist >= QApplication.startDragDistance():
                        self._drag_started = True
                        self._start_external_drag()
                        return True
                # Mouse left the viewport during potential drag — cancel
                vp = self._list_view.viewport() if is_list else self._detail_view.viewport()
                if not vp.rect().contains(event.pos()):
                    self._reset_drag_state()
            if t == QEvent.Type.MouseButtonRelease:
                if self._drag_origin_pos is not None and not self._drag_started:
                    # Was a click on selected item that didn't become a drag — simulate click
                    if is_list:
                        idx = self._list_view.indexAt(event.pos())
                        if idx.isValid():
                            self._on_click(idx)
                    else:
                        item = self._detail_view.itemAt(event.pos())
                        if item:
                            self._on_tree_click(item, 0)
                self._reset_drag_state()
        return super().eventFilter(obj, event)

    def _smooth_scroll(self, event):
        from PySide6.QtCore import QVariantAnimation, QEasingCurve
        sb = self._list_view.verticalScrollBar() if self._list_view else None
        if not sb:
            return
        target = sb.value() - event.angleDelta().y()

        if not hasattr(self, '_scroll_anim'):
            self._scroll_anim = None
        if self._scroll_anim and self._scroll_anim.state() == QVariantAnimation.State.Running:
            target = self._scroll_anim.endValue() - event.angleDelta().y()
            self._scroll_anim.stop()

        self._scroll_anim = QVariantAnimation()
        self._scroll_anim.setDuration(120)
        self._scroll_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._scroll_anim.setStartValue(sb.value())
        self._scroll_anim.setEndValue(target)
        self._scroll_anim.valueChanged.connect(lambda v: sb.setValue(int(v)))
        self._scroll_anim.start()

    def _handle_key(self, event):
        key = event.key()
        mod = event.modifiers()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._open_selected()
            return True
        if key == Qt.Key.Key_Delete:
            self._delete(self._selected_paths())
            return True
        if key == Qt.Key.Key_Backspace:
            self._go_up()
            return True
        if key == Qt.Key.Key_F and mod == Qt.KeyboardModifier.ControlModifier:
            self._search.setFocus()
            self._search.selectAll()
            return True
        if key == Qt.Key.Key_A and mod == Qt.KeyboardModifier.ControlModifier:
            if self._list_view:
                self._list_view.selectAll()
            return True
        if key == Qt.Key.Key_Escape:
            if self._list_view:
                self._list_view.clearSelection()
            self._search.clear()
            return True
        if key == Qt.Key.Key_F2:
            self._inline_rename()
            return True
        if key == Qt.Key.Key_C and mod == Qt.KeyboardModifier.ControlModifier:
            self._copy_to_clipboard()
            return True
        if key == Qt.Key.Key_X and mod == Qt.KeyboardModifier.ControlModifier:
            self._cut_to_clipboard()
            return True
        if key == Qt.Key.Key_V and mod == Qt.KeyboardModifier.ControlModifier:
            self._paste()
            return True
        return False

    def _on_drag_enter(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return True
        return False

    def _accept_drag(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return True
        return False

    def _on_drop(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile()]
        if not paths:
            return False
        result = self._get_file_operation_service().copy_to_directory(paths, str(self._current))
        for error in result.errors:
            _log.error("Drag-drop copy failed: %s", error)
        self._post_refresh()
        if self._view_mode == "Details":
            self._populate_details()
        self._load_visible()

    # ── External drag (drag files to other apps) ────────────────

    def _reset_drag_state(self):
        """Clear all drag tracking state."""
        self._drag_origin_pos = None
        self._drag_started = False

    def _start_external_drag(self):
        """Start a QDrag with file URLs so files can be dropped to other apps."""
        from PySide6.QtGui import QDrag
        paths = self._selected_paths()
        if not paths:
            self._reset_drag_state()
            return
        # Build MIME data with file URLs
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
        # Build drag preview pixmap
        t = themes.get()
        count = len(paths)
        name = Path(paths[0]).name
        is_dir = os.path.isdir(paths[0])
        w, h = 200, 72
        dpr = max(1.0, float(self.devicePixelRatioF() or 1.0))
        pixmap = QPixmap(int(w * dpr), int(h * dpr))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Shadow
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 50))
        p.drawRoundedRect(QRect(4, 5, w - 8, h - 8), 12, 12)
        # Card
        card = QRect(2, 2, w - 8, h - 8)
        p.setBrush(QColor(t["header"]))
        p.setPen(QPen(QColor(t["border"]), 1))
        p.drawRoundedRect(card, 12, 12)
        # Accent top bar
        accent_bar = QRect(card.x() + 1, card.y() + 1, card.width() - 2, 6)
        accent_path = QPainterPath()
        accent_path.addRoundedRect(accent_bar, 11, 11)
        p.fillPath(accent_path, QColor(t["accent"]))
        # Icon area
        icon_rect = QRect(card.x() + 10, card.y() + 12, 40, 40)
        p.setBrush(QColor(t["panel"]))
        p.setPen(QPen(QColor(t["border"]), 1))
        p.drawRoundedRect(icon_rect, 6, 6)
        if is_dir:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(t["accent"]))
            p.drawRoundedRect(icon_rect.adjusted(8, 10, -8, -8), 3, 3)
        else:
            p.setPen(QColor(t["muted"]))
            p.setFont(QFont(p.font()))
            p.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, Path(paths[0]).suffix.upper() or "?")
        # Text
        text_x = icon_rect.right() + 10
        title_font = QFont(p.font())
        title_font.setBold(True)
        title_font.setPointSize(scaled_pt(9))
        p.setFont(title_font)
        p.setPen(QColor(t["heading"]))
        fm = p.fontMetrics()
        title_rect = QRect(text_x, card.y() + 12, card.right() - text_x - 10, fm.height())
        p.drawText(title_rect, Qt.AlignmentFlag.AlignLeft, fm.elidedText(name, Qt.TextElideMode.ElideRight, title_rect.width()))
        # Subtitle
        sub_font = QFont(p.font())
        sub_font.setBold(False)
        sub_font.setPointSize(scaled_pt(8))
        p.setFont(sub_font)
        p.setPen(QColor(t["muted"]))
        fm2 = p.fontMetrics()
        sub_text = f"{count} items" if count > 1 else ("Folder" if is_dir else Path(paths[0]).suffix.upper() or "File")
        sub_rect = QRect(text_x, title_rect.bottom() + 2, title_rect.width(), fm2.height())
        p.drawText(sub_rect, Qt.AlignmentFlag.AlignLeft, fm2.elidedText(sub_text, Qt.TextElideMode.ElideRight, sub_rect.width()))
        # Path
        path_font = QFont(p.font())
        path_font.setPointSize(scaled_pt(7))
        p.setFont(path_font)
        p.setPen(QColor(t["muted"]))
        fm3 = p.fontMetrics()
        path_rect = QRect(text_x, sub_rect.bottom() + 2, title_rect.width(), fm3.height())
        p.drawText(path_rect, Qt.AlignmentFlag.AlignLeft, fm3.elidedText(str(Path(paths[0]).parent), Qt.TextElideMode.ElideMiddle, path_rect.width()))
        # Multi-select badge
        if count > 1:
            badge_sz = 22
            badge_rect = QRect(card.right() - badge_sz - 8, card.y() + 8, badge_sz, badge_sz)
            p.setPen(QPen(QColor(t["accent"]), 1))
            p.setBrush(QColor(t["accent"]))
            p.drawEllipse(badge_rect)
            badge_font = QFont(p.font())
            badge_font.setBold(True)
            badge_font.setPointSize(scaled_pt(8))
            p.setFont(badge_font)
            p.setPen(QColor("white"))
            p.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, str(count))
        p.end()
        # Execute drag — blocks until drop/cancel
        drag = QDrag(self._list_view.viewport())
        drag.setMimeData(mime)
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(min(20, w // 3), min(16, h // 3)))
        drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction)
        # Always reset state after drag ends (drop, cancel, or ignore)
        self._reset_drag_state()

    def _show_empty_if_needed(self):
        if self._model.rowCount() == 0:
            self._status.setText(tr("filelist.empty"))
            if self._list_view:
                self._list_view.setStyleSheet(
                    "QListView { background: transparent; border: none; }")
        else:
            self._apply_list_theme()

    # ── Helpers ─────────────────────────────────────────────────

    @staticmethod
    def _make_nav_button(text, tooltip, callback, font_size=13):
        from AssetsManager.core import themes
        t = themes.get()
        btn = QPushButton(text)
        btn.setFixedSize(scaled_px(26), scaled_px(26))
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {t['body']}; "
            f"border: none; padding: 0; font-size: {scaled_pt(font_size)}px; }} "
            f"QPushButton:hover {{ background: {t['panel']}80; border-radius: {scaled_px(3)}px; color: {t['heading']}; }}")
        btn.clicked.connect(callback)
        return btn

    # ── Cleanup ─────────────────────────────────────────────────

    def clone(self):
        new = FileListPanel()
        new.navigate_to(str(self._current))
        return new

    def _cleanup_undo_dir(self):
        if hasattr(self, '_undo_svc'):
            self._undo_svc.cleanup()

    @staticmethod
    def _schedule_library_stats_update(_lib_root: str):
        pass  # implemented in concrete subclass

    def shutdown(self):
        """Clean up bus connections and worker threads."""
        try:
            bus().theme_changed.disconnect(self._on_theme_changed)
        except (RuntimeError, TypeError):
            pass
        self._loader.stop()
        self._model.shutdown()

    def closeEvent(self, event):
        self._cleanup_undo_dir()
        self._loader.stop()
        self._model.shutdown()
        super().closeEvent(event)
