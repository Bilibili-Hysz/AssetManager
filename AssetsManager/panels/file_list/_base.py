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
    QTreeWidgetItem,
)

from AssetsManager.panels.base import PanelContent
from AssetsManager.core.signal_bus import get as bus
from AssetsManager.core import icons
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
from AssetsManager.application.tag_service import TagServiceAdapter

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
        self._thumbnail_service = None
        self._operation_feedback_generation = 0

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
        self._nav_tooltip_keys = ("filelist.back", "filelist.forward", "filelist.up")
        self._nav_buttons.append(self._make_nav_button("arrow_left", tr("filelist.back"), self._go_back, font_size=10))
        self._nav_buttons.append(self._make_nav_button("arrow_right", tr("filelist.forward"), self._go_forward, font_size=10))
        self._nav_buttons.append(self._make_nav_button("arrow_up", tr("filelist.up"), self._go_up, font_size=10))
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

        self._sort_btn = self._make_nav_button("arrow_up_down", tr("filelist.sort_dir"), self._toggle_sort_dir, font_size=14)
        tb.addWidget(self._sort_btn)

        self._filter_combo = QComboBox()
        for key, _label in FILTER_CATEGORY_LABELS:
            self._filter_combo.addItem(tr(f"filelist.filter.{key}"), key)
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
        self._hidden_btn = self._make_nav_button("eye", tr("filelist.hidden"), self._toggle_hidden, font_size=12)
        tb.addWidget(self._hidden_btn)
        self._refresh_btn = self._make_nav_button("refresh", tr("filelist.refresh"), self._do_refresh, font_size=15)
        tb.addWidget(self._refresh_btn)

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
        self._refresh_state_icons()

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
        self._scroll_animating = False
        self._scroll_animation_generation = 0
        self._scroll_animation_setting_value = False
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
        self._operation_feedback = QLabel("")
        self._operation_feedback.hide()
        sl.addWidget(self._operation_feedback)
        self._operation_feedback_timer = QTimer(self)
        self._operation_feedback_timer.setSingleShot(True)
        self._operation_feedback_timer.setInterval(4000)
        self._operation_feedback_timer.timeout.connect(self._clear_operation_feedback)
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
        self._operation_feedback.setStyleSheet(
            f"color: {t['muted']}; font-size: {scaled_pt(11)}px; background: transparent;")

    def set_scoped_services(self, services):
        """Bind library-scoped services resolved by MainWindow."""
        self._operation_feedback_generation = getattr(self, "_operation_feedback_generation", 0) + 1
        clear_feedback = getattr(self, "_clear_operation_feedback", None)
        if callable(clear_feedback):
            clear_feedback()
        self._scoped_services = services
        # Capture the service object together with the session bundle.  This
        # is intentionally a snapshot, not a later lookup through a mutable
        # application container; async thumbnail work must retain the service
        # belonging to the generation that created it.
        self._thumbnail_service = services.thumbnail_service
        self._root = services.session.root
        self._model.set_library_root(services.session.root_str, services.session)
        self._model.set_metadata_service(services.metadata_service)
        performance_recorder = getattr(services, "performance_recorder", None)
        session_token = services.session.event_token
        set_model_context = getattr(self._model, "set_performance_context", None)
        if callable(set_model_context):
            set_model_context(performance_recorder, session_token)
        set_grid_context = getattr(self, "_set_grid_performance_context", None)
        if set_grid_context is not None:
            set_grid_context(
                getattr(services, "performance_recorder", None),
                services.session.event_token,
                self._model.scan_generation,
            )
        self._loader.bind_runtime(
            services.thumbnail_service,
            services.session.thumb_dir_str,
            services.session.root_str,
            performance_recorder,
            session_token,
        )
        self._loader.orphan_cleanup()
        if hasattr(services, "undo_service"):
            self._undo_svc = services.undo_service
        self._controller.set_file_operations(
            services.file_operation_service, self._undo_svc)

    def set_runtime(self, runtime):
        """Bind the immutable service snapshot owned by ``LibraryRuntime``."""
        self.set_scoped_services(runtime.services_snapshot)

    def _get_scoped_services(self):
        return self._scoped_services

    def _is_current_operation_session(self, session) -> bool:
        scoped = self._scoped_services
        return bool(
            not getattr(self._model, "_is_shutdown", False)
            and scoped is not None
            and getattr(scoped, "session", None) is session
            and not getattr(session, "is_closed", False)
        )

    def _show_operation_feedback(
        self,
        session,
        operation: str,
        *,
        changed_count: int = 0,
        errors: tuple[str, ...] = (),
        running: bool = False,
    ) -> None:
        """Display session-bound operation feedback without affecting command state."""
        if (
            not self._is_current_operation_session(session)
        ):
            return
        label = tr(f"filelist.feedback.operation.{operation}")
        if running:
            text = tr("filelist.feedback.running", operation=label)
        elif errors and changed_count:
            text = tr("filelist.feedback.partial", operation=label, count=changed_count, failed=len(errors))
        elif errors:
            text = tr("filelist.feedback.failed", operation=label, failed=len(errors))
        else:
            text = tr("filelist.feedback.succeeded", operation=label, count=changed_count)
        self._operation_feedback.setText(text)
        self._operation_feedback.show()
        if running:
            self._operation_feedback_timer.stop()
        else:
            self._operation_feedback_timer.start()

    def _clear_operation_feedback(self) -> None:
        feedback = getattr(self, "_operation_feedback", None)
        if feedback is not None:
            feedback.clear()
            feedback.hide()

    def _set_grid_performance_context(self, _recorder, _session_token: str, _generation: int) -> None:
        """Optional QWidget-grid hook; legacy list views have no frame recorder."""
        pass

    def _get_file_operation_service(self):
        scoped = self._scoped_services
        if scoped is not None:
            return scoped.file_operation_service
        raise RuntimeError("FileListPanel scoped services not injected")

    def _get_tag_service(self):
        if not self._lib_root:
            raise RuntimeError("FileListPanel requires a library root for TagService")
        scoped = self._scoped_services
        if scoped is None:
            raise RuntimeError("FileListPanel scoped services not injected")
        return scoped.tag_service

    def _configure_library_runtime(self, root: str):
        """Bind file-list runtime helpers to a library root."""
        scoped = self._scoped_services
        if scoped is None:
            raise RuntimeError("FileListPanel scoped services not injected before navigate_to")
        if Path(scoped.session.root).resolve() != Path(root).resolve():
            raise RuntimeError("FileListPanel scoped services do not match navigation root")
        self._model.set_library_root(scoped.session.root_str, scoped.session)

    def refresh_header(self):
        """Re-apply header bar styling (called on bg opacity changes)."""
        t = themes.get()
        self._header.setStyleSheet(
            f"background: {themes.header_for_dock()}; "
            f"border: 1px solid {t['border']}; "
            f"border-top-left-radius: {scaled_px(7)}px; border-top-right-radius: {scaled_px(7)}px; ")

    def refresh_contents(self):
        """Refresh the active directory after an application-wide update."""
        self._model.refresh()

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
            semantic_icon = btn.property("semanticIcon")
            if semantic_icon:
                btn.setIcon(icons.icon(semantic_icon, color=t["body"], size=scaled_px(16)))
            btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {t['body']}; "
                f"border: none; padding: 0; font-size: {scaled_pt(10)}px; }} "
                f"QPushButton:hover {{ background: {alpha(t['panel'], 0.50)}; border-radius: {scaled_px(3)}px; color: {t['heading']}; }}")

    def _retranslate_controls(self):
        self._header_title.setText(tr("filelist.header"))
        for button, key in zip(self._nav_buttons, self._nav_tooltip_keys):
            button.setToolTip(tr(key))
        self._sort_btn.setToolTip(tr("filelist.sort_dir"))
        self._hidden_btn.setToolTip(tr("filelist.hidden"))
        self._refresh_btn.setToolTip(tr("filelist.refresh"))
        self._search.setPlaceholderText(tr("filelist.filter_placeholder"))

        sort_key = self._sort_combo.currentData()
        self._sort_combo.blockSignals(True)
        self._sort_combo.clear()
        for key, label in (("name", tr("filelist.sort.name")), ("date", tr("filelist.sort.date")),
                           ("size", tr("filelist.sort.size")), ("type", tr("filelist.sort.type"))):
            self._sort_combo.addItem(label, key)
        self._sort_combo.setCurrentIndex(max(0, self._sort_combo.findData(sort_key)))
        self._sort_combo.blockSignals(False)

        filter_key = self._filter_combo.currentData()
        self._filter_combo.blockSignals(True)
        self._filter_combo.clear()
        for key, _label in FILTER_CATEGORY_LABELS:
            self._filter_combo.addItem(tr(f"filelist.filter.{key}"), key)
        self._filter_combo.setCurrentIndex(max(0, self._filter_combo.findData(filter_key)))
        self._filter_combo.blockSignals(False)

        view_mode = self._view_combo.currentData()
        self._view_combo.blockSignals(True)
        self._view_combo.setItemText(0, tr("filelist.view.grid"))
        self._view_combo.setItemText(1, tr("filelist.view.details"))
        self._view_combo.setCurrentIndex(max(0, self._view_combo.findData(view_mode)))
        self._view_combo.blockSignals(False)

    def _update_thumb_cache_dir(self):
        if self._root:
            self._configure_library_runtime(str(self._root))
        else:
            self._loader.bind_runtime(None, "", "", None, None)

    def _toggle_sort_dir(self):
        self._model._sort_asc = not self._model._sort_asc
        self._refresh_state_icons()
        self._model.set_sort(self._sort_key(), self._model._sort_asc)
        if self._view_mode == "Details":
            self._populate_details()
        self._load_visible()

    def _toggle_hidden(self):
        self._model._show_hidden = not self._model._show_hidden
        self._refresh_state_icons()
        self._post_refresh()

    def _post_refresh(self):
        """Refresh model and update display — call after any data change."""
        self._model.refresh()
        if self._view_mode == "Details":
            self._populate_details()
        else:
            self._load_visible()
        self._refresh_state_icons()
        self._update_status()

    def _clear_selection_for_navigation(self) -> None:
        """Compatibility hook for clearing view-owned selection on directory changes."""

    def _request_operation_selection(self, _session, _paths) -> None:
        """Compatibility hook for result-path selection after a refresh."""

    def _deletion_selection_candidates(self, _paths) -> tuple[str, ...]:
        """Compatibility hook for selecting a surviving neighbor after deletion."""
        return ()

    def _on_view_changed(self, _index):
        mode = self._view_mode
        self._view_memory[str(self._current)] = mode
        self._loader.set_size(self._thumb_size)
        is_detail = mode == "Details"
        if self._list_view:
            self._list_view.setVisible(not is_detail)
        if self._detail_view:
            self._detail_view.setVisible(is_detail)
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
        self._zoom_anim = QVariantAnimation(self)
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
        if self._view_mode == "Grid":
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
        self._refresh_state_icons()
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
        self._refresh_state_icons()
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
        if self._model._is_shutdown:
            return
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
        if self._model._is_shutdown:
            return
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
        self._detail_store = TagServiceAdapter(root, self._get_tag_service())
        self._detail_index = 0
        self._detail_total = self._model.rowCount()
        self._detail_snapshot_id = id(self._model._entries)  # detect stale chunks
        self._populate_details_chunk()

    def _populate_details_chunk(self):
        import datetime
        if self._model._is_shutdown:
            return
        detail_view = self._detail_view
        if detail_view is None:
            return
        # Abort if model changed since _populate_details was called
        if id(self._model._entries) != self._detail_snapshot_id:
            return
        CHUNK = 100
        store = self._detail_store
        end = min(self._detail_index + CHUNK, self._detail_total)
        prioritize_sizes = getattr(self._model, "prioritize_dir_sizes", None)
        if callable(prioritize_sizes):
            prioritize_sizes(
                self._model._entries[i].path
                for i in range(self._detail_index, end)
                if self._model._entries[i].is_dir()
            )
        for i in range(self._detail_index, end):
            entry = self._model._entries[i]
            name = entry.name
            is_dir = entry.is_dir()
            path = entry.path
            if is_dir:
                # Read from subtitle cache (async result) first, then fallback to DIR_SIZE_ROLE
                sz = self._model._subtitle_cache.get(path)
                if not sz or sz == "...":
                    sz = self._model.data(
                        self._model.index(i, 0),
                        Qt.ItemDataRole(FileSystemModel.DIR_SIZE_ROLE),
                    )
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
            item = QTreeWidgetItem()
            item.setIcon(
                0,
                icons.icon(
                    "folder" if is_dir else "file",
                    color=themes.get()["heading"],
                    size=scaled_px(16),
                ),
            )
            for column, text in enumerate((name, ext, size, date, tags_text)):
                item.setText(column, str(text))
            item.setData(0, Qt.ItemDataRole.UserRole, path)
            detail_view.addTopLevelItem(item)
        self._detail_index = end
        if self._detail_index < self._detail_total:
            QTimer.singleShot(0, self._populate_details_chunk)
        else:
            detail_view.setSortingEnabled(True)
            detail_view.setUpdatesEnabled(True)
            self._update_status()

    def _on_detail_dir_size_ready(self, dir_path: str, size_str: str, gen: int = 0):
        """Update Detail view when async directory size computation completes."""
        if self._model._is_shutdown:
            return
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
        detail_view = self._detail_view
        if detail_view is not None:
            detail_view.resizeColumnToContents(col)

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
        self._status.setText(self._controller.compute_status_text(
            total, sel, self._cached_total_sz, self._view_mode,
        ))

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
                    if lv is None:
                        return super().eventFilter(obj, event)
                    idx = lv.indexAt(event.pos())
                    if idx.isValid() and idx in lv.selectionModel().selectedRows():
                        self._drag_origin_pos = event.pos()
                        self._drag_started = False
                        return True
                    else:
                        self._reset_drag_state()
                else:
                    if dv is None:
                        return super().eventFilter(obj, event)
                    idx = dv.indexAt(event.pos())
                    if idx.isValid() and dv.selectionModel().isSelected(idx):
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
                view = lv if is_list else dv
                if view is None:
                    return super().eventFilter(obj, event)
                vp = view.viewport()
                if not vp.rect().contains(event.pos()):
                    self._reset_drag_state()
            if t == QEvent.Type.MouseButtonRelease:
                if self._drag_origin_pos is not None and not self._drag_started:
                    # Was a click on selected item that didn't become a drag — simulate click
                    if is_list:
                        if lv is None:
                            return super().eventFilter(obj, event)
                        idx = lv.indexAt(event.pos())
                        if idx.isValid():
                            self._on_click(idx)
                    else:
                        if dv is None:
                            return super().eventFilter(obj, event)
                        item = dv.itemAt(event.pos())
                        if item:
                            self._on_tree_click(item, 0)
                self._reset_drag_state()
        return super().eventFilter(obj, event)

    def _on_scroll_value_changed(self) -> None:
        if self._scroll_animation_setting_value:
            return
        if self._scroll_animating:
            self._scroll_animation_generation += 1
            self._scroll_animating = False
            animation = getattr(self, "_scroll_anim", None)
            if animation is not None:
                animation.stop()
        self._scroll_debounce.start()

    def _begin_smooth_scroll(self) -> int:
        self._scroll_animation_generation += 1
        self._scroll_animating = True
        self._scroll_debounce.stop()
        return self._scroll_animation_generation

    def _finish_smooth_scroll(self, generation: int) -> None:
        if generation != self._scroll_animation_generation:
            return
        self._scroll_animating = False
        self._scroll_debounce.start()

    def _set_scroll_animation_value(self, scrollbar, value) -> None:
        self._scroll_animation_setting_value = True
        try:
            scrollbar.setValue(int(value))
        finally:
            self._scroll_animation_setting_value = False

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

        self._scroll_anim = QVariantAnimation(self)
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
        scoped = self._get_scoped_services()
        root_path = self._lib_root
        if scoped is None or root_path is None:
            return False
        destination = str(self._current)
        root = Path(root_path).resolve()
        sources = [path for path in paths if os.path.dirname(path) != destination]
        in_library = [path for path in sources if Path(path).resolve().is_relative_to(root)]
        external = [path for path in sources if path not in in_library]
        if not sources:
            return False

        service = scoped.file_operation_service
        changed_paths = []
        for source in in_library:
            result = service.move_to_directory(
                [source], destination, library_root=root_path,
            )
            for changed_path in result.changed_paths:
                changed_paths.append(changed_path)
                if self._undo_svc is not None:
                    self._undo_svc.record_rename(source, str(changed_path))
            for error in result.errors:
                _log.error("Drag-drop move failed: %s", error)
        if external:
            result = service.copy_to_directory(
                external, destination, library_root=root_path,
            )
            changed_paths.extend(getattr(result, "changed_paths", ()))
            for error in result.errors:
                _log.error("Drag-drop copy failed: %s", error)
        self._request_operation_selection(scoped.session, changed_paths)
        self._post_refresh()
        if self._view_mode == "Details":
            self._populate_details()
        self._load_visible()
        return True

    # ── External drag (drag files to other apps) ────────────────

    def _reset_drag_state(self):
        """Clear all drag tracking state."""
        self._drag_origin_pos = None
        self._drag_started = False

    def _start_external_drag(self):
        """Start a QDrag with file URLs so files can be dropped to other apps."""
        from PySide6.QtGui import QDrag
        list_view = self._list_view
        if list_view is None:
            self._reset_drag_state()
            return
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
        drag = QDrag(list_view.viewport())
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

    def _refresh_state_icons(self) -> None:
        """Keep stateful toolbar controls icon-only across every refresh path."""
        t = themes.get()
        sort_icon = "arrow_up" if self._model._sort_asc else "arrow_down"
        hidden_icon = "eye" if self._model._show_hidden else "eye_off"
        for button, icon_name in (
            (self._sort_btn, sort_icon),
            (self._hidden_btn, hidden_icon),
        ):
            button.setIcon(icons.icon(icon_name, color=t["body"], size=scaled_px(16)))
            button.setIconSize(QSize(scaled_px(16), scaled_px(16)))
            button.setProperty("semanticIcon", icon_name)
            button.setText("")

    @staticmethod
    def _make_nav_button(icon_name, tooltip, callback, font_size=13):
        from AssetsManager.core import themes
        t = themes.get()
        btn = QPushButton()
        btn.setIcon(icons.icon(icon_name, color=t["body"], size=scaled_px(16)))
        btn.setIconSize(QSize(scaled_px(16), scaled_px(16)))
        btn.setProperty("semanticIcon", icon_name)
        btn.setFixedSize(scaled_px(26), scaled_px(26))
        btn.setToolTip(tooltip)
        btn.setAccessibleName(tooltip)
        themes.set_button_variant(btn, "ghost")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {t['body']}; "
            f"border: none; padding: 0; min-width: {scaled_px(26)}px; }} "
            f"QPushButton:hover {{ background: {t['panel']}80; border-radius: {scaled_px(3)}px; color: {t['heading']}; }}")
        btn.clicked.connect(callback)
        return btn

    # ── Cleanup ─────────────────────────────────────────────────

    def prepare_library_switch(self):
        """Drain all session-bound background work before its session closes."""
        fs_refresh_timer = getattr(self, "_fs_refresh_timer", None)
        if fs_refresh_timer is not None:
            fs_refresh_timer.stop()
        if hasattr(self, "_pending_fs_changed_path"):
            self._pending_fs_changed_path = None
        generation = self._loader.invalidate_tasks()
        self._loader.wait_for_runtime(generation)
        self._model.prepare_library_switch()

    def clone(self):
        new = FileListPanel()
        new.navigate_to(str(self._current))
        return new

    @staticmethod
    def _schedule_library_stats_update(_lib_root: str):
        pass  # implemented in concrete subclass

    def shutdown(self):
        """Clean up bus connections and worker threads."""
        self._operation_feedback_generation += 1
        for timer_name in ("_search_timer", "_scroll_debounce", "_file_op_timer", "_operation_feedback_timer", "_fs_refresh_timer"):
            timer = getattr(self, timer_name, None)
            if timer is not None:
                timer.stop()
        if hasattr(self, "_pending_fs_changed_path"):
            self._pending_fs_changed_path = None
        watcher = getattr(self, "_fs_watcher", None)
        if watcher is not None:
            watched = watcher.directories()
            if watched:
                watcher.removePaths(watched)
        delivery = getattr(self, "_thumbnail_delivery", None)
        if delivery is not None:
            delivery.clear()
        grid = getattr(self, "_grid_widget", None)
        if grid is not None:
            grid.stop_animations()
        for animation_name in ("_zoom_anim", "_scroll_anim"):
            animation = getattr(self, animation_name, None)
            if animation is not None:
                for signal_name in ("valueChanged", "finished"):
                    signal = getattr(animation, signal_name, None)
                    if signal is not None:
                        try:
                            signal.disconnect()
                        except (RuntimeError, TypeError):
                            pass
                animation.stop()
        self._scroll_animating = False
        self._scroll_animation_setting_value = False
        self._loader.stop()
        self._model.shutdown()
        self._model.clear_scoped_services()
        self._controller.set_file_operations(None, None)
        self._scoped_services = None
        self._thumbnail_service = None
        self._undo_svc = None
        self._clear_operation_feedback()
        super().shutdown()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
