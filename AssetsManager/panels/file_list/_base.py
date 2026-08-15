"""File list panel — core infrastructure for file browser panels.

Provides: toolbar, breadcrumb, search, status bar, navigation, actions, thumbnails.
View creation is delegated to subclasses (FileListPanel or legacy FileListPanel).

Architecture:
  _common.py       — shared constants (FILTER_CATEGORIES, ZOOM_PRESETS, natural_key)
  _model.py        — FileSystemModel (QAbstractListModel)
  _loader.py       — ThumbnailLoader + async disk-write thread
  _navigation.py   — NavigationMixin (breadcrumb, history, FS watcher)
  _actions.py      — ActionsMixin (context menu, file ops, undo, tags)
  _grid_widget.py  — FileListGridWidget (QWidget canvas)
  __init__.py      — FileListPanel (default) + legacy FileListPanel
"""
import os
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    Qt, Signal, QEvent, QSize, QTimer, QPoint, QModelIndex,
    QEasingCurve, QVariantAnimation, QFileInfo, QItemSelectionModel,
)
from PySide6.QtWidgets import (
    QHBoxLayout, QComboBox, QLabel, QWidget, QApplication,
    QMenu, QSizePolicy, QTreeView, QAbstractItemView,
    QHeaderView,
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
from AssetsManager.panels.file_list._common import (
    FILTER_CATEGORY_LABELS,
    IMAGE_EXTS,
    VIDEO_EXTS,
    ZOOM_PRESETS,
    natural_key,
)
from AssetsManager.panels.file_list._navigation import NavigationMixin
from AssetsManager.panels.file_list._actions import ActionsMixin
from AssetsManager.widgets.toast import Toast
from AssetsManager.panels.file_list._grid_layout import GridLayout
from AssetsManager.panels.file_list._grid_widget import FileListGridWidget
from AssetsManager.panels.file_list._thumbnail_delivery import ThumbnailDeliveryCoordinator
from AssetsManager.panels.file_list._detail_model import DetailModel
from AssetsManager.panels.file_list._commands import FileListCommand, FileListCommandContext
from AssetsManager.panels.file_list._ui_helpers import (
    _add_command_group,
    _always,
    _DetailsItemDelegate,
    _first_image_in,
    _is_external_drop,
    _make_nav_button,
    _save_search_term,
)
from AssetsManager.panels.file_list._status_helpers import (
    compute_total_size,
    status_text,
    operation_feedback_text,
)

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
        self._last_tree_item: QModelIndex | None = None
        self._drag_origin_pos = None
        self._drag_started = False
        self._scoped_services = None
        self._thumbnail_service = None
        self._file_ops_port = None
        self._tags_service = None
        self._tags_port = None
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

        self._header = QWidget()
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(scaled_px(10), scaled_px(3), scaled_px(6), scaled_px(3))
        header_layout.setSpacing(scaled_px(4))

        self._header_title = QLabel(tr("filelist.header"))
        header_layout.addWidget(self._header_title)
        header_layout.addStretch()
        self.content_layout.addWidget(self._header)

        # ── Toolbar ─────────────────────────────────────────────

        tb = QHBoxLayout()
        tb.setContentsMargins(scaled_px(4), scaled_px(4), scaled_px(4), scaled_px(2))
        tb.setSpacing(scaled_px(3))

        self._nav_buttons = []
        self._nav_tooltip_keys = ("filelist.back", "filelist.forward", "filelist.up")
        self._nav_buttons.append(self._make_nav_button("arrow_left", tr("filelist.back"), self._go_back))
        self._nav_buttons.append(self._make_nav_button("arrow_right", tr("filelist.forward"), self._go_forward))
        self._nav_buttons.append(self._make_nav_button("arrow_up", tr("filelist.up"), self._go_up))
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
        self._sort_combo.setToolTip(tr("filelist.sort_tooltip"))
        self._sort_combo.setAccessibleName(tr("filelist.sort_tooltip"))
        tb.addWidget(self._sort_combo)

        self._sort_btn = self._make_nav_button("arrow_up_down", tr("filelist.sort_dir"), self._toggle_sort_dir)
        tb.addWidget(self._sort_btn)

        self._filter_combo = QComboBox()
        for key, _label in FILTER_CATEGORY_LABELS:
            self._filter_combo.addItem(tr(f"filelist.filter.{key}"), key)
        self._filter_combo.currentTextChanged.connect(self._on_filter_changed)
        self._filter_combo.setToolTip(tr("filelist.filter_tooltip"))
        self._filter_combo.setAccessibleName(tr("filelist.filter_tooltip"))
        tb.addWidget(self._filter_combo)

        self._view_combo = QComboBox()
        self._view_combo.addItem(tr("filelist.view.grid"), userData="Grid")
        self._view_combo.addItem(tr("filelist.view.details"), userData="Details")
        self._view_combo.currentIndexChanged.connect(self._on_view_changed)
        self._view_combo.setToolTip(tr("filelist.view_tooltip"))
        self._view_combo.setAccessibleName(tr("filelist.view_tooltip"))
        tb.addWidget(self._view_combo)

        self._zoom_combo = QComboBox()
        for sz in ZOOM_PRESETS:
            self._zoom_combo.addItem(f"{sz}px")
        self._zoom_combo.setCurrentIndex(2)
        self._zoom_combo.currentTextChanged.connect(self._on_zoom_changed)
        self._zoom_combo.setToolTip(tr("filelist.zoom_tooltip"))
        self._zoom_combo.setAccessibleName(tr("filelist.zoom_tooltip"))
        tb.addWidget(self._zoom_combo)

        tb.addStretch()
        self._hidden_btn = self._make_nav_button("eye", tr("filelist.hidden"), self._toggle_hidden)
        tb.addWidget(self._hidden_btn)
        self._refresh_btn = self._make_nav_button("refresh", tr("filelist.refresh"), self._do_refresh)
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
        self._apply_chrome_style()

        # ── Breadcrumb ──────────────────────────────────────────

        self._breadcrumb = QWidget()
        self._breadcrumb.setStyleSheet("background: transparent;")
        self._bc_layout = QHBoxLayout(self._breadcrumb)
        self._bc_layout.setContentsMargins(scaled_px(4), 0, scaled_px(4), 0)
        self._bc_layout.setSpacing(0)
        self.content_layout.addWidget(self._breadcrumb)

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

        self.content_layout.setContentsMargins(scaled_px(2), 0, scaled_px(2), scaled_px(4))
        self._header.setProperty("central", True)

        self._grid_widget = FileListGridWidget()
        self._grid_widget.set_model(self._model)
        self._grid_layout = GridLayout()
        self._grid_widget.set_layout_ref(self._grid_layout)
        self._thumbnail_delivery = ThumbnailDeliveryCoordinator(self._model, self._grid_widget)
        self._grid_widget.clicked.connect(self._on_grid_click)
        self._grid_widget.double_clicked.connect(self._on_grid_double_click)
        self._grid_widget.context_menu.connect(self._on_grid_context)
        self._grid_widget.selection_changed.connect(self._update_status)
        self._grid_widget.selection_changed.connect(self._on_grid_selection_changed)
        self._grid_widget.rename_requested.connect(self._rename_grid_row)
        self._model.rename_requested.connect(self._rename_grid_row)
        self._model.modelAboutToBeReset.connect(self._capture_grid_selection)
        self._model.modelAboutToBeReset.connect(self._capture_detail_selection)
        self._model.modelReset.connect(self._on_grid_model_reset)
        self._model.scan_started.connect(self._on_scan_started)
        self._model.scan_committed.connect(self._on_scan_committed)
        self._model.state_changed.connect(self._on_file_list_state_changed)
        self._pending_scan_generation: int | None = None
        self._pending_selection_paths: set[str] | None = None
        self._pending_detail_paths: set[str] | None = None
        self._presentation_generation = -1

        # Reconnect scroll debounce to grid widget's scrollbar
        self._scroll_debounce.timeout.disconnect()
        self._grid_widget._scrollbar.valueChanged.connect(self._on_scroll_value_changed)
        self._scroll_debounce.timeout.connect(self._load_visible)

        self.content_layout.insertWidget(
            self.content_layout.indexOf(self._status_bar), self._grid_widget)
        self._grid_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._grid_widget.installEventFilter(self)
        self._grid_widget.setAcceptDrops(True)

        # ── Detail view (QTreeView + DetailModel) ─────────────
        self._detail_view = QTreeView()
        self._detail_model = DetailModel()
        self._detail_model.rename_requested.connect(self._rename_detail_row)
        self._detail_model.layoutAboutToBeChanged.connect(self._capture_detail_selection)
        self._detail_model.layoutChanged.connect(self._restore_detail_selection)
        self._detail_view.setModel(self._detail_model)
        self._detail_view.setRootIsDecorated(False)
        self._detail_view.setItemsExpandable(False)
        self._detail_view.setIndentation(0)
        self._detail_view.setItemDelegate(_DetailsItemDelegate(self._detail_view))
        self._detail_view.setUniformRowHeights(True)
        self._detail_view.setAlternatingRowColors(True)
        self._detail_view.setIconSize(QSize(scaled_px(18), scaled_px(18)))
        self._detail_view.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._detail_view.setAllColumnsShowFocus(False)
        detail_header = self._detail_view.header()
        detail_header.setStretchLastSection(True)
        detail_header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        detail_header.setMinimumHeight(scaled_px(30))
        detail_header.setMinimumSectionSize(scaled_px(72))
        detail_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        detail_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        detail_header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        detail_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        detail_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        self._detail_view.selectionModel().selectionChanged.connect(self._on_detail_selection_changed)
        detail_header.setSortIndicatorShown(True)
        self._detail_view.setSortingEnabled(True)
        self._detail_view.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self._detail_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._detail_view.setEditTriggers(QTreeView.EditTrigger.EditKeyPressed)
        self._detail_view.setDragEnabled(True)
        self._detail_view.setAcceptDrops(True)
        self._detail_view.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self._detail_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._detail_view.customContextMenuRequested.connect(self._on_detail_context)
        self._detail_view.clicked.connect(self._on_tree_click)
        self._detail_view.doubleClicked.connect(self._on_tree_double_click)
        self._detail_view.installEventFilter(self)
        self._detail_view.viewport().installEventFilter(self)
        self._detail_view.hide()
        self._apply_detail_theme()
        self.content_layout.insertWidget(
            self.content_layout.indexOf(self._status_bar), self._detail_view)

        self._connect_bus(bus().language_changed, self._refresh_language)
        self._connect_bus(bus().ui_scale_changed, self._on_ui_scale_changed)
        self.initialize_navigation()

        from AssetsManager.domain.events import FileSystemChanged
        self._file_op_timer = QTimer(self)
        self._file_op_timer.setSingleShot(True)
        self._file_op_timer.setInterval(500)
        self._file_op_timer.timeout.connect(self._post_refresh)
        self._connect_domain_event(FileSystemChanged, self._on_file_operation)

    def initialize_navigation(self):
        """Start filesystem watching after views exist."""
        self._start_fs_watcher()

    def _fst_status_style(self):
        t = themes.get()
        self._status_bar.setStyleSheet(
            f"background: transparent; "
            f"border-top: 1px solid {t['border_subtle']};")
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
        # Desktop ports: the panel holds injected port objects instead of
        # reaching into the scoped bundle for tag/metadata/file-operation
        # services (metadata flows through the model's own service binding).
        from AssetsManager.application.desktop_ports import RootBoundTagService
        self._file_ops_port = services.file_operation_service
        self._tags_service = services.tag_service
        self._tags_port = RootBoundTagService(services.session.root_str, services.tag_service)
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
            not getattr(self._model, "is_shutdown", False)
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
        warnings: tuple[object, ...] = (),
        running: bool = False,
    ) -> None:
        """Display session-bound operation feedback without affecting command state."""
        if (
            not self._is_current_operation_session(session)
        ):
            return
        text = operation_feedback_text(
            operation=operation,
            changed_count=changed_count,
            errors=errors,
            warnings=warnings,
            running=running,
        )
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

    def _set_grid_performance_context(self, recorder, session_token: str, generation: int) -> None:
        self._grid_widget.set_performance_context(recorder, session_token, generation)

    def _get_file_operation_service(self):
        if self._file_ops_port is None:
            raise RuntimeError("FileListPanel scoped services not injected")
        return self._file_ops_port

    def _get_tag_service(self):
        if not self._lib_root:
            raise RuntimeError("FileListPanel requires a library root for TagService")
        if self._tags_service is None:
            raise RuntimeError("FileListPanel scoped services not injected")
        return self._tags_service

    def _configure_library_runtime(self, root: str):
        """Bind file-list runtime helpers to a library root."""
        scoped = self._scoped_services
        if scoped is None:
            raise RuntimeError("FileListPanel scoped services not injected before navigate_to")
        if Path(scoped.session.root).resolve() != Path(root).resolve():
            raise RuntimeError("FileListPanel scoped services do not match navigation root")
        self._model.set_library_root(scoped.session.root_str, scoped.session)

    @staticmethod
    def _header_css(t: dict) -> str:
        return (
            f"background: {themes.header_for_dock()}; border: 1px solid {t['border']}; "
            f"border-top-left-radius: {scaled_px(7)}px; border-top-right-radius: {scaled_px(7)}px; "
        )

    @staticmethod
    def _header_title_css(t: dict) -> str:
        return (
            f"color: {t['heading']}; font-size: {scaled_pt(12)}px; font-weight: bold; "
            f"background: transparent; border: none; padding: {scaled_px(2)}px {scaled_px(4)}px;"
        )

    @staticmethod
    def _nav_button_css(t: dict) -> str:
        return (
            f"QPushButton {{ background: transparent; color: {t['body']}; "
            f"border: none; padding: 0; min-width: {scaled_px(26)}px; }} "
            f"QPushButton:hover {{ background: {alpha(t['panel'], 0.50)}; border-radius: {scaled_px(3)}px; "
            f"color: {t['heading']}; }}"
        )

    def _apply_chrome_style(self):
        """Single source for header/title/nav/status chrome styling."""
        t = themes.get()
        if hasattr(self, "_header"):
            self._header.setStyleSheet(self._header_css(t))
        if hasattr(self, "_header_title"):
            self._header_title.setStyleSheet(self._header_title_css(t))
        if hasattr(self, "_nav_buttons"):
            for btn in self._nav_buttons:
                btn.setStyleSheet(self._nav_button_css(t))
        if hasattr(self, "_status_bar"):
            self._fst_status_style()

    def refresh_header(self):
        """Re-apply header bar styling (called on bg opacity changes)."""
        self._apply_chrome_style()

    def refresh_contents(self):
        """Refresh the active directory after an application-wide update."""
        self._model.refresh()

    # ── View switching ──────────────────────────────────────────

    @property
    def _view_mode(self):
        return self._view_combo.currentData() or self._view_combo.currentText()

    def _apply_list_theme(self):
        pass

    def _view_selected_rows(self) -> list[QModelIndex]:
        """Native grid implementation of the list-view selection API."""
        rows = []
        for row in self._grid_widget.selection_model_rows():
            idx = self._model.index(row, 0)
            if idx.isValid():
                rows.append(idx)
        return rows

    def _view_edit_index(self, idx: QModelIndex) -> bool:
        """Native grid implementation of the list-view inline-rename API."""
        if idx.isValid() and hasattr(self._grid_widget, '_start_rename'):
            self._grid_widget._start_rename(idx.row())
            return True
        return False

    def _sync_selection_anim(self):
        pass

    def _on_theme_changed(self, _name):
        self._apply_chrome_style()
        self._grid_widget.refresh_theme()
        self._apply_detail_theme()

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
        self._model.set_sort_ascending(not self._model.sort_ascending)
        self._refresh_state_icons()
        self._model.set_sort(self._sort_key(), self._model.sort_ascending)
        if self._view_mode == "Details":
            self._populate_details()
        self._load_visible()

    def _toggle_hidden(self):
        self._model.set_show_hidden(not self._model.show_hidden)
        self._refresh_state_icons()
        self._post_refresh()

    def _post_refresh(self):
        if self._view_mode == "Details":
            self._capture_detail_selection()
        else:
            self._capture_grid_selection()
        self._model.refresh()
        if self._view_mode != "Details":
            self._grid_widget.update_layout(self._model.rowCount(), self._grid_widget.width())
            self._load_visible()
        self._refresh_state_icons()
        self._update_status()

    def _clear_selection_for_navigation(self) -> None:
        """Avoid carrying view selection into a different directory's scan."""
        self._pending_selection_paths = None
        self._pending_detail_paths = None
        self._pending_operation_selection = None
        self._grid_widget.clear_selection()
        self._detail_view.clearSelection()

    def _request_operation_selection(self, session, paths) -> None:
        """Restore the first successful result only in its originating session and directory."""
        self._pending_operation_selection = None
        scoped = self._scoped_services
        if scoped is None or getattr(scoped, "session", None) is not session:
            return
        if getattr(session, "is_closed", False):
            return
        current_dir = self._current.resolve()
        targets = tuple(
            str(Path(path).resolve())
            for path in paths
            if Path(path).resolve().parent == current_dir
        )
        if targets:
            self._pending_operation_selection = (session, current_dir, targets[:1])

    def _deletion_selection_candidates(self, paths) -> tuple[str, ...]:
        """Prefer the next visible survivor, then the previous visible survivor."""
        deleted = {str(Path(path).resolve()) for path in paths}
        entries = self._detail_model.entries if self._view_mode == "Details" else self._model.entries
        visible_paths = [str(Path(entry.path).resolve()) for entry in entries]
        deleted_rows = [row for row, path in enumerate(visible_paths) if path in deleted]
        if not deleted_rows:
            return ()
        first = min(deleted_rows)
        last = max(deleted_rows)
        return tuple(
            path
            for path in [*visible_paths[last + 1:], *reversed(visible_paths[:first])]
            if path not in deleted
        )

    def _on_view_changed(self, _index):
        mode = self._view_mode
        self._view_memory[str(self._current)] = mode
        self._loader.set_size(self._thumb_size)
        is_detail = mode == "Details"
        paths = (
            {
                path for row in self._grid_widget.selection_model_rows()
                if (path := self._model.path_at(row)) is not None
            }
            if is_detail
            else set(self._selected_detail_paths())
        )
        self._grid_widget.setVisible(not is_detail)
        self._detail_view.setVisible(is_detail)
        if not is_detail:
            self._grid_widget.update_layout(self._model.rowCount(), self._grid_widget.width())
            self._select_grid_paths(paths)
            self._detail_view.clearSelection()
            self._load_visible()
        else:
            self._populate_details()
            self._select_detail_paths(paths)
            self._select_grid_paths(set())
        self._update_status()

    def _on_zoom_changed(self, val):
        target = int(val.replace("px", ""))
        anchor_pos = getattr(self, "_pending_zoom_anchor", None)
        self._pending_zoom_anchor = None
        if not hasattr(self, '_zoom_anim'):
            self._zoom_anim = None
        self._zoom_generation = getattr(self, "_zoom_generation", 0) + 1
        generation = self._zoom_generation
        anim = self._zoom_anim
        if anim is not None and anim.state() == QVariantAnimation.State.Running:
            anim.stop()
        start = self._thumb_size
        if start == target:
            # Rebase an interrupted transition before committing its current
            # size, otherwise the previous target's scroll anchor can snap.
            if self._grid_widget.is_zoom_active():
                self._grid_widget.begin_zoom(target, anchor_pos)
                self._on_zoom_done(generation)
            return

        self._grid_widget.begin_zoom(target, anchor_pos)
        if self._grid_widget.reduce_motion_enabled() is True:
            self._thumb_size = target
            self._grid_widget.set_zoom_thumb_size(target)
            self._on_zoom_done(generation, target)
            return

        if anim is None:
            # Reuse a single animation object so rapid zoom changes do not
            # accumulate child QObject instances.
            anim = QVariantAnimation(self)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.valueChanged.connect(self._on_zoom_frame)
            anim.finished.connect(
                lambda: self._on_zoom_done(
                    getattr(self, "_zoom_generation", 0),
                    getattr(self, "_zoom_anim_target", None),
                )
            )
            self._zoom_anim = anim
        self._zoom_anim_target = target
        distance = abs(target - start)
        duration = min(220, 150 + round(distance * 1.1))
        anim.setDuration(duration)
        anim.setStartValue(start)
        anim.setEndValue(target)
        anim.start()

    def _on_zoom_frame(self, size: int):
        if getattr(self._model, "is_shutdown", False):
            return
        self._thumb_size = size
        self._grid_widget.set_zoom_thumb_size(size)

    def _on_zoom_done(self, generation: int | None = None, target_size: int | None = None):
        if getattr(self._model, "is_shutdown", False):
            return
        if generation is not None and generation != getattr(self, "_zoom_generation", 0):
            return
        if target_size is not None:
            self._thumb_size = target_size
        self._loader.set_size(self._thumb_size)
        self._grid_widget.set_thumb_size(self._thumb_size)
        self._grid_widget.update_layout(self._model.rowCount(), self._grid_widget.width())
        # finish_zoom commits the target-size textures pre-rendered during the
        # animation and marks any remaining stale rows dirty for the paced rebuild.
        self._grid_widget.finish_zoom()
        self._load_visible()

    def _wheel_zoom_evt(self, event, source=None):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            idx = self._zoom_combo.currentIndex()
            target_idx = idx
            if delta > 0 and idx < len(ZOOM_PRESETS) - 1:
                target_idx = idx + 1
            elif delta < 0 and idx > 0:
                target_idx = idx - 1
            if target_idx != idx:
                anchor_pos = None
                if source is self._grid_widget and callable(getattr(event, "position", None)):
                    candidate = event.position().toPoint()
                    if self._grid_widget.rect().contains(candidate):
                        anchor_pos = candidate
                self._pending_zoom_anchor = anchor_pos
                try:
                    self._zoom_combo.setCurrentIndex(target_idx)
                finally:
                    self._pending_zoom_anchor = None
            return
        self._grid_widget._scrollbar.wheelEvent(event)

    def _on_sort_changed(self):
        self._model.set_sort(self._sort_key(), self._model.sort_ascending)
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
        self._model.set_filter_text(text.lower())
        timer = self._search_timer
        if timer is None:
            timer = QTimer(self)
            self._search_timer = timer
            timer.setSingleShot(True)
            timer.timeout.connect(self._apply_search)
        timer.start(200)

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
            self._toast(tr("filelist.search.results", count=count, text=text))

    def _toast(self, text: str):
        Toast.info(self._grid_widget, text, duration=2000)

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
        _save_search_term(term)

    # ── Thumbnail loading ───────────────────────────────────────

    def _load_visible(self):
        if getattr(self._model, "is_shutdown", False):
            return
        total = self._model.rowCount()
        if total == 0:
            return
        if self._view_mode != "Grid":
            return
        vh = self._grid_widget.height()
        sy = self._grid_widget._scroll_y
        visible = self._grid_layout.visible_rows(sy, vh)
        visible_rows = [row for row in visible if 0 <= row < total]
        cols = self._grid_layout.columns
        extra = max(2, cols) * 3
        first = max(0, min(visible_rows[0] if visible_rows else 0, total - 1) - extra)
        last = min(total - 1, max(visible_rows[-1] if visible_rows else 0, 0) + extra)
        visible_set = set(visible_rows)
        prefetch_rows = [row for row in range(first, last + 1) if row not in visible_set]
        candidates = []
        retained_paths = set()
        for i in [*visible_rows, *prefetch_rows]:
            ent = self._model.entry_at(i)
            if not ent:
                continue
            priority = 0 if i in visible_set else 1
            if ent.is_dir():
                preview = self._first_image_cached(ent.path)
                if preview:
                    candidates.append((i, preview, priority, ent.path))
                    retained_paths.add(preview)
            elif ent.is_file() and Path(ent.name).suffix.lower() in IMAGE_EXTS | VIDEO_EXTS:
                candidates.append((i, ent.path, priority, None))
                retained_paths.add(ent.path)
        self._loader.retain_deferred(retained_paths)
        for row, path, priority, item_path in candidates:
            self._loader.request(row, path, priority=priority, item_path=item_path)

    def _on_thumbnail_ready(self, row: int, path: str, img):
        if getattr(self._model, "is_shutdown", False):
            return
        self._thumbnail_delivery.handle_ready(row, path, img)

    def _flush_thumb_batch(self):
        self._thumbnail_delivery.flush()

    def _start_fade_timer(self):
        """Start fade-in animation timer. Override in subclass."""
        pass

    @staticmethod
    def _first_image_in(dir_path: str) -> str | None:
        return _first_image_in(dir_path)

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
        if getattr(self._model, "is_shutdown", False):
            return
        self._model.discard_pending_dir_size(dir_path)
        if gen and gen != self._model.dir_size_generation:
            return
        if self._model.subtitle_for(dir_path) is None:
            return
        if self._model.subtitle_for(dir_path) == size_str:
            # Same rendered value: skip the dataChanged emission that would
            # otherwise trigger another in-place texture patch / rebuild.
            return
        self._model.set_subtitle(dir_path, size_str)
        row = self._model.row_for_path(dir_path)
        if row >= 0:
            idx = self._model.index(row, 0)
            if idx.isValid():
                self._model.dataChanged.emit(idx, idx, [FileSystemModel.SUBTITLE_ROLE])

    # ── Details view ────────────────────────────────────────────

    def _populate_details(self):
        self._capture_detail_selection()
        store = self._tags_port if self._lib_root else None
        self._detail_model.set_source(self._model, store=store, lib_root=self._lib_root)
        self._restore_detail_selection()
        self._update_status()


    def _on_detail_dir_size_ready(self, dir_path: str, size_str: str, gen: int = 0):
        if getattr(self._model, "is_shutdown", False):
            return
        if gen and gen != self._model.dir_size_generation:
            return
        self._model.discard_pending_dir_size(dir_path)
        self._model.set_subtitle(dir_path, size_str)
        self._model.set_dir_size(dir_path, size_str)
        # Find the row for this directory and emit dataChanged for Size column only
        for i, entry in enumerate(self._detail_model.entries):
            if entry.path == dir_path:
                idx = self._detail_model.index(i, 2)  # Size column
                if idx.isValid():
                    self._detail_model.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DisplayRole])
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
        self._cached_total_sz = compute_total_size(self._model)

    def _update_status(self):
        state = getattr(self._model, "list_state", None)
        if state is not None and state == getattr(self._model, "STATE_LOADING", None):
            self._status.setText(status_text(state=state, view_mode=self._view_mode, total=0, selected=0, size_str=""))
            return
        if state is not None and state == getattr(self._model, "STATE_SCAN_ERROR", None):
            self._status.setText(status_text(state=state, view_mode=self._view_mode, total=0, selected=0, size_str=""))
            return
        if state is not None and state == getattr(self._model, "STATE_EMPTY_FOLDER", None):
            self._status.setText(status_text(state=state, view_mode=self._view_mode, total=0, selected=0, size_str=""))
            return
        if state is not None and state == getattr(self._model, "STATE_EMPTY_FILTERED", None):
            self._status.setText(status_text(state=state, view_mode=self._view_mode, total=0, selected=0, size_str=""))
            return
        total = self._model.rowCount()
        mode = self._view_mode
        if self._view_mode == "Details":
            sel = len(self._detail_view.selectionModel().selectedRows())
            self._status.setText(status_text(state=state, view_mode=mode, total=total, selected=sel, size_str=""))
        elif hasattr(self, '_grid_widget') and self._grid_widget is not None:
            if self._cached_total_sz < 0:
                self._compute_total_sz()
            sz_str = self._controller.format_total_size_suffix(self._cached_total_sz)
            sel = len(self._grid_widget.selection_model_rows())
            self._status.setText(status_text(state=state, view_mode=mode, total=total, selected=sel, size_str=sz_str))
        else:
            self._status.setText(status_text(state=state, view_mode=mode, total=total, selected=0, size_str=""))

    # ── Keyboard ────────────────────────────────────────────────

    def eventFilter(self, obj, event):
        if not hasattr(self, '_grid_widget') or self._grid_widget is None:
            return QWidget.eventFilter(self, obj, event)
        t = event.type()

        if t == QEvent.Type.DragEnter:
            return self._on_drag_enter(event)
        if t == QEvent.Type.DragMove:
            return self._accept_drag(event)
        if t == QEvent.Type.Drop:
            return self._on_drop(event)
        if t == QEvent.Type.KeyPress:
            return self._handle_key(event)

        # Tolerate construction-time events before the detail view exists.
        detail_view = getattr(self, "_detail_view", None)
        if detail_view is not None and (obj is detail_view or obj is detail_view.viewport()):
            return QWidget.eventFilter(self, obj, event)

        if obj is self._grid_widget or obj is self._search:
            if t == QEvent.Type.Wheel:
                if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                    self._wheel_zoom_evt(event, obj)
                    return True
                self._smooth_scroll(event)
                return True
            if t in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove,
                     QEvent.Type.MouseButtonRelease):
                return QWidget.eventFilter(self, obj, event)
            return QWidget.eventFilter(self, obj, event)

        return QWidget.eventFilter(self, obj, event)

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
        sb = self._grid_widget._scrollbar
        target = sb.value() - event.angleDelta().y()
        anim = getattr(self, '_scroll_anim', None)
        if anim is not None and anim.state() == QVariantAnimation.State.Running:
            target = anim.endValue() - event.angleDelta().y()
            anim.stop()
        generation = self._begin_smooth_scroll()
        self._grid_widget.set_scrolling()
        if anim is None:
            # Reuse a single animation object instead of leaking one per wheel event.
            anim = QVariantAnimation(self)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.valueChanged.connect(lambda v: self._set_scroll_animation_value(sb, v))
            anim.finished.connect(self._on_smooth_scroll_finished)
            self._scroll_anim = anim
        self._scroll_anim_generation = generation
        anim.setDuration(120)
        anim.setStartValue(sb.value())
        anim.setEndValue(target)
        anim.start()

    def _handle_key(self, event):
        from AssetsManager.panels.file_list._shortcuts import handle_key
        return handle_key(self, event)

    def _on_drag_enter(self, event):
        if self._is_external_drop(event):
            event.acceptProposedAction()
            return True
        return False

    def _accept_drag(self, event):
        if self._is_external_drop(event):
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
        # Compare resolved paths throughout: QUrl.toLocalFile() yields forward
        # slashes while str(Path) uses the platform separator, so raw string
        # comparison would misclassify every drop on Windows.
        destination = Path(self._current).resolve()
        root = Path(root_path).resolve()
        resolved_sources = [Path(path).resolve() for path in paths]
        sources = [p for p in resolved_sources if p.parent != destination]
        if not sources:
            return False
        in_library = [p for p in sources if p.is_relative_to(root)]
        external = [p for p in sources if p not in in_library]

        service = self._get_file_operation_service()
        changed_paths = []
        errors = []
        warnings = []
        try:
            for source in in_library:
                result = service.move_to_directory(
                    [str(source)], str(destination), library_root=root_path,
                )
                for changed_path in result.changed_paths:
                    changed_paths.append(changed_path)
                    if self._undo_svc is not None:
                        self._undo_svc.record_rename(str(source), str(changed_path))
                for error in result.errors:
                    _log.error("Drag-drop move failed: %s", error)
                    errors.append(error)
                warnings.extend(getattr(result, "warnings", ()))
            if external:
                result = service.copy_to_directory(
                    [str(p) for p in external], str(destination), library_root=root_path,
                )
                changed_paths.extend(getattr(result, "changed_paths", ()))
                for error in result.errors:
                    _log.error("Drag-drop copy failed: %s", error)
                    errors.append(error)
                warnings.extend(getattr(result, "warnings", ()))
        except (ValueError, OSError) as exc:
            # The service only collects OSError per item; root-scope violations
            # surface as ValueError and must not escape the drop handler.
            _log.error("Drag-drop failed: %s", exc)
            errors.append(str(exc))
        for warning in warnings:
            _log.warning(
                "Drag-drop projection refresh degraded (%s): %s",
                getattr(warning, "code", "unknown"),
                getattr(warning, "path", destination),
            )
        self._show_operation_feedback(
            scoped.session,
            "drop",
            changed_count=len(changed_paths),
            errors=tuple(errors),
            warnings=tuple(warnings),
        )
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

    def _show_empty_if_needed(self):
        if self._model.rowCount() == 0:
            self._status.setText(tr("filelist.empty"))
        else:
            self._apply_list_theme()

    # ── Helpers ─────────────────────────────────────────────────

    def _refresh_state_icons(self) -> None:
        """Keep stateful toolbar controls icon-only across every refresh path."""
        sort_icon = "arrow_up" if self._model.sort_ascending else "arrow_down"
        hidden_icon = "eye" if self._model.show_hidden else "eye_off"
        for button, icon_name in (
            (self._sort_btn, sort_icon),
            (self._hidden_btn, hidden_icon),
        ):
            button.setIcon(icons.icon(icon_name, color="icon_secondary", size=scaled_px(16)))
            button.setIconSize(QSize(scaled_px(16), scaled_px(16)))
            button.setProperty("semanticIcon", icon_name)
            button.setText("")

    @staticmethod
    def _make_nav_button(icon_name, tooltip, callback):
        return _make_nav_button(icon_name, tooltip, callback)

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
        self._file_ops_port = None
        self._tags_service = None
        self._tags_port = None
        self._undo_svc = None
        self._clear_operation_feedback()
        super().shutdown()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    @staticmethod
    def _add_command_group(
        menu: QMenu,
        commands: tuple[FileListCommand, ...],
        context: FileListCommandContext,
        group: str,
    ) -> None:
        _add_command_group(menu, commands, context, group)
    @staticmethod
    def _always(_context: FileListCommandContext) -> bool:
        return _always(_context)
    def _apply_detail_theme(self):
        """Apply theme styling to the detail view (QTreeView)."""
        t = themes.get()
        self._detail_view.header().setStyleSheet(
            f"QHeaderView::section {{"
            f"  background: {t['header']}; color: {t['heading']}; "
            f"  border: none; border-right: 1px solid {alpha(t['border'], 0.25)}; "
            f"  padding: {scaled_px(5)}px {scaled_px(8)}px; "
            f"  font-size: {scaled_pt(12)}px; font-weight: bold; "
            f"}}"
            f"QHeaderView::down-arrow, QHeaderView::up-arrow {{ "
            f"  width: {scaled_px(10)}px; height: {scaled_px(10)}px; "
            f"}}"
            f"QHeaderView::section:hover {{"
            f"  background: {alpha(t['accent'], 0.12)}; "
            f"}}")
        self._detail_view.setStyleSheet(
            f"QTreeView {{"
            f"  background: {t['panel']}; color: {t['body']}; "
            f"  alternate-background-color: {alpha(t['header'], 0.24)}; "
            f"  selection-background-color: {alpha(t['accent'], 0.28)}; "
            f"  selection-color: {t['heading']}; "
            f"  border: none; outline: none; font-size: {scaled_pt(12)}px; "
            f"}}"
            f"QTreeView::item {{"
            f"  padding: {scaled_px(4)}px {scaled_px(8)}px; "
            f"  border: none; border-bottom: 1px solid {alpha(t['border'], 0.18)}; "
            f"}}"
            f"QTreeView::item:alternate {{"
            f"  background: {alpha(t['header'], 0.24)}; "
            f"}}"
            f"QTreeView::item:hover {{"
            f"  background: {alpha(t['accent'], 0.12)}; "
            f"}}"
            f"QTreeView::item:selected {{"
            f"  background: {alpha(t['accent'], 0.28)}; color: {t['heading']}; "
            f"  border-left: {scaled_px(2)}px solid {t['accent']}; "
            f"}}")
    def _build_context_menu(self, paths: list[str], global_pos: QPoint) -> QMenu:
        """Build the shared Grid and Details context menu without displaying it."""
        menu = QMenu(self)
        context = self._command_context(paths)
        if paths:
            p = paths[0]
            commands = self._selected_commands(context, global_pos, p)
            self._add_command_group(menu, commands, context, "open")
            if not os.path.isdir(p):
                open_with = menu.addMenu(tr("filelist.menu.open_with"))
                open_with.addAction(tr("filelist.menu.default"), lambda p=p: self._navigate_or_open(p))
                from AssetsManager.core.tool_scheduler import list_tools, run_tool
                for tool in list_tools():
                    if "{file}" in str(tool.get("args", [])):
                        action = open_with.addAction(
                            tool.get("name", "Tool"),
                            lambda checked, t=tool, fp=p: run_tool(t, file_path=fp),
                        )
                        action.setIcon(icons.icon(tool.get("icon_name") or tool.get("icon"), color="icon_primary", size=scaled_px(16), fallback="wrench"))
            self._add_command_group(menu, commands, context, "clipboard")
            self._add_command_group(menu, commands, context, "mutate")
            self._add_command_group(menu, commands, context, "history")
            tag_menu = menu.addMenu(tr("filelist.menu.tags"))
            tag_menu.addAction(tr("filelist.menu.apply_tag"), lambda: self._apply_tag_dialog(paths))
            tag_menu.addAction(tr("filelist.menu.remove_tag"), lambda: self._remove_tag_dialog(paths))
            tag_menu.addSeparator()
            tag_menu.addAction(tr("filelist.menu.manage_tags"), lambda: self._manage_tags_dialog(paths))
            tag_menu.setEnabled(context.can_mutate)
            menu.addSeparator()
            self._add_command_group(menu, commands, context, "organize")
            self._add_plugin_context_items(menu, p)
        else:
            commands = self._empty_commands(context)
            self._add_command_group(menu, commands, context, "clipboard")
            self._add_command_group(menu, commands, context, "browse")
            self._add_command_group(menu, commands, context, "history")
            self._add_command_group(menu, commands, context, "organize")
        return menu
    def _capture_detail_selection(self):
        if not hasattr(self, '_detail_model') or not hasattr(self, '_detail_view'):
            return
        sel = self._detail_view.selectionModel().selectedRows()
        paths = {
            path for path in (
                self._detail_model.data(i, Qt.ItemDataRole.UserRole) for i in sel if i.isValid()
            ) if isinstance(path, str)
        }
        if paths:
            self._pending_detail_paths = paths
    def _capture_grid_selection(self):
        if not hasattr(self, '_grid_widget'):
            return
        paths = {
            path for path in (
                self._model.path_at(r) for r in self._grid_widget.selection_model_rows()
            ) if path
        }
        if paths:
            self._pending_selection_paths = paths
    def _command_context(self, paths: list[str]) -> FileListCommandContext:
        can_mutate = self._get_scoped_services() is not None
        undo_service = self._undo_svc if can_mutate else None
        return FileListCommandContext(
            paths=tuple(paths),
            current_dir=self._current,
            view_mode=self._view_mode,
            clipboard_has_local_files=self._can_paste(),
            can_mutate=can_mutate,
            undo_available=undo_service is not None and undo_service.can_undo(),
            redo_available=undo_service is not None and undo_service.can_redo(),
        )
    def _consume_operation_selection(self) -> tuple[str, ...]:
        intent = getattr(self, "_pending_operation_selection", None)
        if intent is None:
            return ()
        self._pending_operation_selection = None
        session, current_dir, paths = intent
        scoped = self._scoped_services
        if (
            scoped is None
            or getattr(scoped, "session", None) is not session
            or getattr(session, "is_closed", False)
            or self._current.resolve() != current_dir
        ):
            return ()
        return paths
    def _copy_selected(self):
        self._copy_to_clipboard()
    def _cut_selected(self):
        self._cut_to_clipboard()
    def _empty_commands(self, _context: FileListCommandContext) -> tuple[FileListCommand, ...]:
        return (
            FileListCommand("paste", "filelist.menu.paste", "Ctrl+V", "clipboard", self._always,
                            lambda value: value.can_mutate and value.clipboard_has_local_files,
                            lambda: self._invoke_command("paste", _context)),
            FileListCommand("new_folder", "filelist.menu.new_folder", "Ctrl+Shift+N", "clipboard", self._always,
                            lambda value: value.can_mutate, lambda: self._invoke_command("new_folder", _context)),
            FileListCommand("select_all", "filelist.menu.select_all", "Ctrl+A", "browse", self._always,
                            self._always, lambda: self._invoke_command("select_all", _context)),
            FileListCommand("refresh", "filelist.menu.refresh", "F5", "browse", self._always,
                            self._always, lambda: self._invoke_command("refresh", _context)),
            FileListCommand("toggle_hidden", "filelist.menu.toggle_hidden", "Ctrl+H", "browse", self._always,
                            self._always, lambda: self._invoke_command("toggle_hidden", _context)),
            FileListCommand("undo", "filelist.menu.undo", "Ctrl+Z", "history", self._always,
                            lambda value: value.undo_available, lambda: self._invoke_command("undo", _context)),
            FileListCommand("redo", "filelist.menu.redo", "Ctrl+Y", "history", self._always,
                            lambda value: value.redo_available, lambda: self._invoke_command("redo", _context)),
            FileListCommand("reveal", "filelist.menu.open_explorer", None, "organize", self._always,
                            self._always, lambda: self._invoke_command("reveal", _context)),
            FileListCommand("help", "filelist.menu.keyboard_help", "F4", "organize", self._always,
                            self._always, lambda: self._invoke_command("help", _context)),
        )
    def _invoke_command(
        self,
        command_id: str,
        context: FileListCommandContext | None = None,
        global_pos: QPoint | None = None,
        *,
        shortcut: bool = False,
    ) -> None:
        """Invoke an existing FileList action through its stable command ID."""
        context = context or self._command_context(self._selected_paths())
        paths = context.paths
        path = paths[0] if paths else None
        if command_id == "open" and path:
            self._navigate_or_open(path)
        elif command_id == "copy":
            self._copy_paths(paths, False)
        elif command_id == "cut":
            self._copy_paths(paths, True)
        elif command_id == "copy_path" and path:
            QApplication.clipboard().setText(path)
        elif command_id == "rename" and path:
            if shortcut:
                self._inline_rename()
            else:
                self._rename(path)
        elif command_id == "duplicate":
            self._duplicate_selected()
        elif command_id == "trash":
            self._delete(list(paths))
        elif command_id == "permanent_delete":
            self._delete_permanent(list(paths))
        elif command_id == "undo":
            self._undo()
        elif command_id == "redo":
            self._redo()
        elif command_id == "properties" and path:
            self._show_properties(path)
        elif command_id == "reveal":
            target = str(Path(path).parent) if path and not os.path.isdir(path) else path or str(self._current)
            self._open_in_explorer(target)
        elif command_id == "quick_share":
            self._quick_share_from_context(list(paths), global_pos or QPoint())
        elif command_id == "paste":
            self._paste()
        elif command_id == "new_folder":
            self._new_folder()
        elif command_id == "select_all":
            self._select_all()
        elif command_id == "refresh":
            self._do_refresh()
        elif command_id == "toggle_hidden":
            self._toggle_hidden()
        elif command_id == "help":
            self._show_filelist_shortcuts()
    @staticmethod
    def _is_external_drop(event) -> bool:
        return _is_external_drop(event)
    def _load_visible_if_active(self):
        """Ignore delayed scan presentation work after panel shutdown."""
        if not getattr(self._model, "is_shutdown", False):
            self._load_visible()
    def _navigate_or_open(self, path: str):
        if os.path.isdir(path):
            self.navigate_to(path)
        else:
            self.file_double_clicked.emit(path)
    def _on_detail_context(self, pos: QPoint):
        idx = self._detail_view.indexAt(pos)
        if idx.isValid() and not self._detail_view.selectionModel().isSelected(idx):
            self._detail_view.selectionModel().clearSelection()
            self._detail_view.selectionModel().select(
                idx,
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
            )
        sel = self._detail_view.selectionModel().selectedRows()
        paths = [self._detail_model.data(i, Qt.ItemDataRole.UserRole) for i in sel if i.isValid()]
        self._show_context_menu(
            [path for path in paths if isinstance(path, str)],
            self._detail_view.viewport().mapToGlobal(pos),
        )
    def _on_detail_selection_changed(self):
        if self._pending_scan_generation == self._model.scan_generation:
            self._pending_detail_paths = set(self._selected_detail_paths())
        self._update_status()
        sel = self._detail_view.selectionModel().selectedRows()
        if sel:
            path = self._detail_model.data(sel[0], Qt.ItemDataRole.UserRole)
            if isinstance(path, str):
                info = QFileInfo(path)
                self.file_selected.emit(info)
                bus().file_focused.emit(str(path))
    def _on_file_list_state_changed(self, _state: str, generation: int, _error) -> None:
        if generation == self._model.scan_generation:
            self._update_status()
    def _on_file_operation(self, event):
        if getattr(self._model, "is_shutdown", False):
            return
        scoped = self._scoped_services
        if scoped is None or event.session_token != scoped.session.event_token:
            return
        fs_timer = getattr(self, "_fs_refresh_timer", None)
        if fs_timer is not None:
            fs_timer.stop()
        if hasattr(self, "_pending_fs_changed_path"):
            self._pending_fs_changed_path = None
        self._file_op_timer.start()
    def _on_grid_click(self, row: int):
        self._last_click_row = row
        path = self._model.path_at(row)
        if path:
            info = QFileInfo(path)
            self.file_selected.emit(info)
            bus().file_focused.emit(str(path))
    def _on_grid_context(self, global_pos: QPoint):
        sel_rows = self._grid_widget.selection_model_rows()
        paths = [self._model.path_at(r) for r in sel_rows]
        self._show_context_menu([p for p in paths if p], global_pos)
    def _on_grid_double_click(self, row: int):
        ent = self._model.entry_at(row)
        if ent:
            if ent.is_dir():
                self.navigate_to(ent.path)
            else:
                self.file_double_clicked.emit(ent.path)
    def _on_grid_model_reset(self):
        self._thumbnail_delivery.clear()
        self._grid_widget.set_performance_generation(self._model.scan_generation)
        if self._pending_scan_generation == self._model.scan_generation:
            # Both async-refresh resets can be delivered after the model has
            # left its committing state. Preserve paths until scan_committed.
            if not self._model.is_committing_scan:
                self._grid_widget.update_layout(0, self._grid_widget.width())
            return
        if self._view_mode == "Details":
            # The first reset of an async refresh clears source entries. Keep
            # the captured paths until the populated scan result arrives.
            if self._model.rowCount():
                self._populate_details()
            return
        self._grid_widget.update_layout(self._model.rowCount(), self._grid_widget.width())
        if self._view_mode == "Grid":
            self._restore_grid_selection()
    def _on_grid_selection_changed(self) -> None:
        if self._pending_scan_generation == self._model.scan_generation:
            self._pending_selection_paths = {
                path for row in self._grid_widget.selection_model_rows()
                if (path := self._model.path_at(row)) is not None
            }
    def _on_scan_committed(self, generation: int):
        """Present each populated scan generation once after its model reset completes."""
        if generation != self._pending_scan_generation:
            return
        self._pending_scan_generation = None
        if generation <= self._presentation_generation:
            return
        self._presentation_generation = generation
        result_paths = self._consume_operation_selection()
        scan_reused = self._model.last_scan_reused
        self._model.clear_last_scan_reused()
        if scan_reused:
            self._grid_widget.set_performance_generation(generation)
            # A reused scan emits scan_committed without a model reset; clear the
            # grid's scan-reset guard so a later sort/filter still captures the
            # path texture cache instead of dropping it and rebuilding all cards.
            self._grid_widget.mark_scan_settled()
            # The reused scan skips the model reset, so the grid may still show
            # the 0-row layout left by an in-flight sort/filter reset. Repopulate
            # it with the preserved (possibly re-sorted) entry count.
            self._grid_widget.update_layout(self._model.rowCount(), self._grid_widget.width())
            if result_paths:
                self._restore_operation_selection(result_paths)
            self._update_status()
            return
        if self._view_mode == "Grid":
            self._restore_grid_selection()
        if not self._model.rowCount():
            self._grid_widget.discard_pending_presentation(generation)
            return
        self._grid_widget.update_layout(self._model.rowCount(), self._grid_widget.width())
        visible_rows = self._grid_layout.visible_rows(
            self._grid_widget._scroll_y, self._grid_widget.height())
        self._grid_widget.begin_presentation(generation, visible_rows)
        if self._view_mode == "Details":
            self._populate_details()
        else:
            QTimer.singleShot(80, self._load_visible_if_active)
        if result_paths:
            self._restore_operation_selection(result_paths)
    def _on_scan_started(self, generation: int):
        self._pending_scan_generation = generation
    def _on_smooth_scroll_finished(self):
        self._finish_smooth_scroll(getattr(self, "_scroll_anim_generation", 0))
    def _on_ui_scale_changed(self, _scale: float) -> None:
        """Re-measure canvas text and Details chrome after a live scale change."""
        self._apply_chrome_style()
        self._grid_widget.refresh_scale()
        self._grid_widget.update_layout(self._model.rowCount(), self._grid_widget.width())
        self._detail_view.setIconSize(QSize(scaled_px(18), scaled_px(18)))
        self._detail_view.header().setMinimumHeight(scaled_px(30))
        self._apply_detail_theme()
    def _quick_share_from_context(self, paths: list[str], global_pos):
        """Delegate Quick Share to the canonical LAN share-link creator."""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return
        win = app.activeWindow()
        if win is None:
            for w in app.topLevelWidgets():
                if w.isVisible() and hasattr(w, '_open_share_link_dialog'):
                    win = w
                    break
        open_share_link_dialog = getattr(win, "_open_share_link_dialog", None)
        if callable(open_share_link_dialog):
            open_share_link_dialog(paths=paths)
    def _refresh_language(self, _code=""):
        self._retranslate_controls()
        self._detail_model.headerDataChanged.emit(
            Qt.Orientation.Horizontal, 0, len(self._detail_model.HEADER_KEYS) - 1)
        self._update_status()
    def _rename_detail_row(self, row: int, new_name: str):
        if not (0 <= row < len(self._detail_model.entries)):
            return
        self._rename_path(self._detail_model.entries[row].path, new_name)
    def _rename_grid_row(self, row: int, new_name: str):
        ent = self._model.entry_at(row)
        if not ent:
            return
        self._rename_path(ent.path, new_name)
    def _rename_path(self, old_path: str, new_name: str):
        session = getattr(self._get_scoped_services(), "session", None)
        self._show_operation_feedback(session, "rename", running=True)
        try:
            new_path = self._rename_file_path(old_path, new_name)
            self._request_operation_selection(session, [new_path])
            self._show_operation_feedback(session, "rename", changed_count=1)
            self._post_refresh()
        except OSError as e:
            self._show_operation_feedback(session, "rename", errors=(str(e),))
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, tr("dialog.error"), str(e))
    def _restore_detail_selection(self):
        paths = self._pending_detail_paths
        if paths is None:
            return
        self._pending_detail_paths = None
        self._select_detail_paths(paths)
    def _restore_grid_selection(self):
        paths = self._pending_selection_paths
        if paths is None:
            return
        self._pending_selection_paths = None
        self._select_grid_paths(paths)
    def _restore_operation_selection(self, paths: tuple[str, ...]) -> None:
        if self._view_mode == "Details":
            self._pending_detail_paths = set(paths)
            self._restore_detail_selection()
        else:
            self._pending_selection_paths = set(paths)
            self._restore_grid_selection()
    def _select_all(self):
        if self._view_mode == "Details":
            self._detail_view.selectAll()
        else:
            self._grid_widget.select_all()
        self._update_status()
    def _select_detail_paths(self, paths: set[str]) -> None:
        sm = self._detail_view.selectionModel()
        sm.clearSelection()
        for row, entry in enumerate(self._detail_model.entries):
            if entry.path in paths:
                idx = self._detail_model.index(row, 0)
                if idx.isValid():
                    sm.select(idx, QItemSelectionModel.SelectionFlag.Select
                              | QItemSelectionModel.SelectionFlag.Rows)
    def _select_grid_paths(self, paths: set[str]) -> None:
        self._grid_widget.set_selection_rows({
            row
            for path in paths
            if (row := self._model.row_for_path(path)) >= 0
        })
    def _selected_commands(
        self, context: FileListCommandContext, global_pos: QPoint, path: str,
    ) -> tuple[FileListCommand, ...]:
        return (
            FileListCommand("open", "filelist.menu.open", "Enter", "open", self._always, self._always,
                            lambda: self._invoke_command("open", context)),
            FileListCommand("copy", "filelist.menu.copy", "Ctrl+C", "clipboard", self._always, self._always,
                            lambda: self._invoke_command("copy", context)),
            FileListCommand("cut", "filelist.menu.cut", "Ctrl+X", "clipboard", self._always, self._always,
                            lambda: self._invoke_command("cut", context)),
            FileListCommand("copy_path", "filelist.menu.copy_path", None, "clipboard", self._always, self._always,
                            lambda: self._invoke_command("copy_path", context)),
            FileListCommand("rename", "filelist.menu.rename", "F2", "mutate", self._always,
                            lambda value: value.can_mutate and len(value.paths) == 1,
                            lambda: self._invoke_command("rename", context)),
            FileListCommand("duplicate", "filelist.menu.duplicate", "Ctrl+D", "mutate", self._always,
                            lambda value: value.can_mutate, lambda: self._invoke_command("duplicate", context)),
            FileListCommand("trash", "filelist.menu.delete", "Delete", "mutate", self._always,
                            lambda value: value.can_mutate, lambda: self._invoke_command("trash", context)),
            FileListCommand("permanent_delete", "filelist.menu.delete_permanent", "Shift+Delete", "mutate",
                            self._always, lambda value: value.can_mutate,
                            lambda: self._invoke_command("permanent_delete", context)),
            FileListCommand("undo", "filelist.menu.undo", "Ctrl+Z", "history", self._always,
                            lambda value: value.undo_available, lambda: self._invoke_command("undo", context)),
            FileListCommand("redo", "filelist.menu.redo", "Ctrl+Y", "history", self._always,
                            lambda value: value.redo_available, lambda: self._invoke_command("redo", context)),
            FileListCommand("properties", "filelist.properties", "Alt+Enter", "organize", self._always,
                            self._always, lambda: self._invoke_command("properties", context)),
            FileListCommand("reveal", "filelist.menu.open_explorer", None, "organize", self._always,
                            self._always, lambda: self._invoke_command("reveal", context)),
            FileListCommand("quick_share", "sharing.quick_share", None, "organize", self._always,
                            self._always, lambda: self._invoke_command("quick_share", context, global_pos)),
            FileListCommand("help", "filelist.menu.keyboard_help", "F4", "organize", self._always,
                            self._always, lambda: self._invoke_command("help", context)),
        )
    def _selected_detail_paths(self) -> list[str]:
        sel = self._detail_view.selectionModel().selectedRows()
        return [p for p in (
            self._detail_model.data(i, Qt.ItemDataRole.UserRole)
            for i in sel if i.isValid()
        ) if isinstance(p, str)]
    def _show_context_menu(self, paths: list[str], global_pos: QPoint):
        self._build_context_menu(paths, global_pos).exec(global_pos)
    def _show_filelist_shortcuts(self) -> None:
        """Show FileList's stable shortcuts without depending on its host window."""
        from AssetsManager.core.settings import AppSettings
        from PySide6.QtWidgets import QMessageBox

        settings = AppSettings.instance()
        if not settings.get("filelist_shortcut_hints_seen", False):
            settings.set("filelist_shortcut_hints_seen", True)
            settings.save()
        lines = [
            f"F4 - {tr('filelist.help.keyboard_help')}",
            f"Ctrl+F - {tr('shortcuts.filelist_filter')}",
            f"Enter - {tr('filelist.menu.open')}",
            f"Alt+Enter - {tr('filelist.properties')}",
            f"Backspace - {tr('filelist.help.up')}",
            f"Ctrl+C / Ctrl+X / Ctrl+V - {tr('filelist.help.clipboard')}",
            f"Ctrl+D - {tr('filelist.menu.duplicate')}",
            f"F2 - {tr('filelist.menu.rename')}",
            f"Delete / Shift+Delete - {tr('filelist.help.delete')}",
            f"Ctrl+Z / Ctrl+Y - {tr('filelist.help.history')}",
            f"Ctrl+Shift+N - {tr('filelist.menu.new_folder')}",
            f"Ctrl+A - {tr('filelist.menu.select_all')}",
            f"F5 - {tr('filelist.menu.refresh')}",
            f"Ctrl+H - {tr('filelist.menu.toggle_hidden')}",
            f"Escape - {tr('filelist.help.clear')}",
        ]
        QMessageBox.information(self, tr("filelist.help.title"), "\n".join(lines))


if TYPE_CHECKING:
    from AssetsManager.panels.file_list._host import FileListHost

    # Lock the mixin host contract: FileListPanel must provide the surface
    # NavigationMixin relies on (see _host.FileListHost).
    _host_contract: FileListHost = FileListPanel()
