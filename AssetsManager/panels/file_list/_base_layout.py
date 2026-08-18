"""UI construction and chrome styling for the file list panel.

``LayoutMixin`` builds every widget the panel renders — header, toolbar,
breadcrumb, status bar, grid canvas and the details QTreeView — and owns
their styling (chrome CSS, detail theme, state icons, translations), the
status-bar rendering, and the context-menu construction with its command
definitions.

Business logic lives in ``_base_logic.py``; signal wiring and interaction
handling live in ``_base_events.py``; ``_base.py`` composes the three.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import Qt, QSize, QPoint
from PySide6.QtWidgets import (
    QHBoxLayout, QComboBox, QLabel, QWidget, QMenu,
    QSizePolicy, QTreeView, QAbstractItemView, QHeaderView,
)

from AssetsManager.core import icons
from AssetsManager.core import themes
from AssetsManager.core.color_utils import alpha
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager import i18n

from AssetsManager.panels.file_list._common import (
    FILTER_CATEGORY_LABELS,
    ZOOM_PRESETS,
)
from AssetsManager.panels.file_list._grid_layout import GridLayout
from AssetsManager.panels.file_list._grid_widget import FileListGridWidget
from AssetsManager.panels.file_list._thumbnail_delivery import ThumbnailDeliveryCoordinator
from AssetsManager.panels.file_list._detail_model import DetailModel
from AssetsManager.panels.file_list._commands import FileListCommand, FileListCommandContext
from AssetsManager.panels.file_list._ui_helpers import (
    _add_command_group,
    _always,
    _DetailsItemDelegate,
    _make_nav_button,
)
from AssetsManager.panels.file_list._status_helpers import (
    compute_total_size,
    status_text,
)
from AssetsManager.widgets.toast import Toast

if TYPE_CHECKING:
    from pathlib import Path

    from AssetsManager.controllers.file_list_controller import FileListController
    from AssetsManager.panels.file_list._model import FileSystemModel

tr = i18n.tr


class LayoutMixin:
    """Widget creation, layout management and chrome styling."""

    if TYPE_CHECKING:
        # Host surface owned by FileListPanel / sibling mixins.
        _model: FileSystemModel
        _controller: FileListController
        _current: Path
        _cached_total_sz: int
        _undo_svc: Any
        content_layout: Any

        def setFocusProxy(self, w: Any) -> None: ...
        def _go_back(self) -> None: ...
        def _go_forward(self) -> None: ...
        def _go_up(self) -> None: ...
        def _toggle_sort_dir(self) -> None: ...
        def _toggle_hidden(self) -> None: ...
        def _do_refresh(self) -> None: ...
        def _on_sort_changed(self) -> None: ...
        def _on_filter_changed(self) -> None: ...
        def _on_view_changed(self, index: int) -> None: ...
        def _on_zoom_changed(self, val: str) -> None: ...
        def _on_search_changed(self, text: str) -> None: ...
        def _invoke_command(
            self,
            command_id: str,
            context: FileListCommandContext | None = None,
            global_pos: QPoint | None = None,
            *,
            shortcut: bool = False,
        ) -> None: ...
        def _navigate_or_open(self, path: str) -> None: ...
        def _add_plugin_context_items(self, menu: QMenu, file_path: str) -> None: ...
        def _can_paste(self) -> bool: ...
        def _get_scoped_services(self) -> Any: ...
        def _apply_tag_dialog(self, paths: list[str]) -> None: ...
        def _remove_tag_dialog(self, paths: list[str]) -> None: ...
        def _manage_tags_dialog(self, paths: list[str]) -> None: ...

    def _build_ui(self) -> None:
        """Build header, toolbar, breadcrumb, status bar, grid and detail views."""
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
        self._sort_combo.setToolTip(tr("filelist.sort_tooltip"))
        self._sort_combo.setAccessibleName(tr("filelist.sort_tooltip"))
        tb.addWidget(self._sort_combo)

        self._sort_btn = self._make_nav_button("arrow_up_down", tr("filelist.sort_dir"), self._toggle_sort_dir)
        tb.addWidget(self._sort_btn)

        self._filter_combo = QComboBox()
        for key, _label in FILTER_CATEGORY_LABELS:
            self._filter_combo.addItem(tr(f"filelist.filter.{key}"), key)
        self._filter_combo.setToolTip(tr("filelist.filter_tooltip"))
        self._filter_combo.setAccessibleName(tr("filelist.filter_tooltip"))
        tb.addWidget(self._filter_combo)

        self._view_combo = QComboBox()
        self._view_combo.addItem(tr("filelist.view.grid"), userData="Grid")
        self._view_combo.addItem(tr("filelist.view.details"), userData="Details")
        self._view_combo.setToolTip(tr("filelist.view_tooltip"))
        self._view_combo.setAccessibleName(tr("filelist.view_tooltip"))
        tb.addWidget(self._view_combo)

        self._zoom_combo = QComboBox()
        for sz in ZOOM_PRESETS:
            self._zoom_combo.addItem(f"{sz}px")
        self._zoom_combo.setCurrentIndex(2)
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
        self._search.installEventFilter(cast(QWidget, self))
        self._setup_search_history(self._search)
        tb.addWidget(self._search, stretch=1)
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
        self._fst_status_style()
        self.content_layout.addWidget(self._status_bar)

        self.content_layout.setContentsMargins(scaled_px(2), 0, scaled_px(2), scaled_px(4))
        self._header.setProperty("central", True)

        self._grid_widget = FileListGridWidget()
        self._grid_widget.set_model(self._model)
        self._grid_layout = GridLayout()
        self._grid_widget.set_layout_ref(self._grid_layout)
        self._thumbnail_delivery = ThumbnailDeliveryCoordinator(self._model, self._grid_widget)

        self.content_layout.insertWidget(
            self.content_layout.indexOf(self._status_bar), self._grid_widget)
        self._grid_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._grid_widget.installEventFilter(cast(QWidget, self))
        self._grid_widget.setAcceptDrops(True)

        # ── Detail view (QTreeView + DetailModel) ─────────────
        self._detail_view = QTreeView()
        self._detail_model = DetailModel()
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
        detail_header.setSortIndicatorShown(True)
        self._detail_view.setSortingEnabled(True)
        self._detail_view.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self._detail_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._detail_view.setEditTriggers(QTreeView.EditTrigger.EditKeyPressed)
        self._detail_view.setDragEnabled(True)
        self._detail_view.setAcceptDrops(True)
        self._detail_view.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self._detail_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._detail_view.installEventFilter(cast(QWidget, self))
        self._detail_view.viewport().installEventFilter(cast(QWidget, self))
        self._detail_view.hide()
        self._apply_detail_theme()
        self.content_layout.insertWidget(
            self.content_layout.indexOf(self._status_bar), self._detail_view)





    def _fst_status_style(self):
        t = themes.get()
        self._status_bar.setStyleSheet(
            f"background: transparent; "
            f"border-top: 1px solid {t['border_subtle']};")
        self._status.setStyleSheet(
            f"color: {t['muted']}; font-size: {scaled_pt(int(themes.prop('font_size', 'sm')))}px; "
            f"background: transparent; "
            f"padding: {scaled_px(int(themes.prop('spacing', 'xs')))}px 0;")
        self._operation_feedback.setStyleSheet(
            f"color: {t['muted']}; font-size: {scaled_pt(int(themes.prop('font_size', 'sm')))}px; "
            f"background: transparent; "
            f"padding: {scaled_px(int(themes.prop('spacing', 'xs')))}px 0;")

    @staticmethod
    def _header_css(t: dict) -> str:
        return (
            f"background: {themes.header_for_dock()}; border: 1px solid {t['border_subtle']}; "
            f"border-top-left-radius: {scaled_px(int(themes.prop('border_radius', 'md')))}px; "
            f"border-top-right-radius: {scaled_px(int(themes.prop('border_radius', 'md')))}px; "
        )

    @staticmethod
    def _header_title_css(t: dict) -> str:
        return (
            f"color: {t['heading']}; font-size: {scaled_pt(int(themes.prop('font_size', 'sm')))}px; "
            f"font-weight: bold; "
            f"background: transparent; border: none; "
            f"padding: {scaled_px(int(themes.prop('spacing', 'xs')))}px {scaled_px(int(themes.prop('spacing', 'sm')))}px;"
        )

    @staticmethod
    def _nav_button_css(t: dict) -> str:
        return (
            f"QPushButton {{ background: transparent; color: {t['body']}; "
            f"border: none; padding: 0; min-width: {scaled_px(26)}px; }} "
            f"QPushButton:hover {{ background: {alpha(t['hover_overlay'], themes.prop('opacity', 'hover'))}; "
            f"border-radius: {scaled_px(int(themes.prop('border_radius', 'sm')))}px; "
            f"color: {t['heading']}; }}"
            f"QPushButton:pressed {{ background: {alpha(t['hover_overlay'], themes.prop('opacity', 'hover'))}; "
            f"border-radius: {scaled_px(int(themes.prop('border_radius', 'sm')))}px; "
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

    @property
    def _view_mode(self):
        return self._view_combo.currentData() or self._view_combo.currentText()

    def _apply_list_theme(self):
        pass

    def _sync_selection_anim(self):
        pass

    def _retranslate_controls(self):
        self._header_title.setText(tr("filelist.header"))
        for button, key in zip(self._nav_buttons, self._nav_tooltip_keys, strict=True):
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

    def _toast(self, text: str):
        Toast.info(self._grid_widget, text, duration=2000)

    def _sort_key(self):
        return self._sort_combo.currentData() or self._sort_combo.currentText()

    def _filter_key(self):
        return self._filter_combo.currentData() or self._filter_combo.currentText()

    def _setup_search_history(self, line_edit):
        from PySide6.QtWidgets import QCompleter
        from AssetsManager.controllers.file_list_controller import FileListController
        history = FileListController.get_search_history()
        if history:
            completer = QCompleter(history, line_edit)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            line_edit.setCompleter(completer)

    def _on_detail_header_clicked(self, col: int):
        """Tweak column widths after sort for better readability."""
        detail_view = self._detail_view
        if detail_view is not None:
            detail_view.resizeColumnToContents(col)

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

    def _show_empty_if_needed(self):
        if self._model.rowCount() == 0:
            self._status.setText(tr("filelist.empty"))
        else:
            self._apply_list_theme()

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
            f"  padding: {scaled_px(int(themes.prop('spacing', 'xs')))}px {scaled_px(int(themes.prop('spacing', 'sm')))}px; "
            f"  font-size: {scaled_pt(int(themes.prop('font_size', 'sm')))}px; font-weight: bold; "
            f"}}"
            f"QHeaderView::down-arrow, QHeaderView::up-arrow {{ "
            f"  width: {scaled_px(10)}px; height: {scaled_px(10)}px; "
            f"}}"
            f"QHeaderView::section:hover {{"
            f"  background: {alpha(t['hover_overlay'], themes.prop('opacity', 'hover'))}; "
            f"}}")
        self._detail_view.setStyleSheet(
            f"QTreeView {{"
            f"  background: {t['panel']}; color: {t['body']}; "
            f"  alternate-background-color: {alpha(t['header'], 0.24)}; "
            f"  selection-background-color: {alpha(t['accent'], 0.28)}; "
            f"  selection-color: {t['heading']}; "
            f"  border: none; outline: none; font-size: {scaled_pt(int(themes.prop('font_size', 'sm')))}px; "
            f"}}"
            f"QTreeView::item {{"
            f"  padding: {scaled_px(int(themes.prop('spacing', 'xs')))}px {scaled_px(int(themes.prop('spacing', 'sm')))}px; "
            f"  border: none; border-bottom: 1px solid {t['border_subtle']}; "
            f"}}"
            f"QTreeView::item:alternate {{"
            f"  background: {alpha(t['header'], 0.24)}; "
            f"}}"
            f"QTreeView::item:hover {{"
            f"  background: {alpha(t['hover_overlay'], themes.prop('opacity', 'hover'))}; "
            f"}}"
            f"QTreeView::item:selected {{"
            f"  background: {alpha(t['accent'], 0.28)}; color: {t['heading']}; "
            f"  border-left: {scaled_px(2)}px solid {t['accent']}; "
            f"}}")

    def _build_context_menu(self, paths: list[str], global_pos: QPoint) -> QMenu:
        """Build the shared Grid and Details context menu without displaying it."""
        menu = QMenu(cast(QWidget, self))
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
        QMessageBox.information(cast(QWidget, self), tr("filelist.help.title"), "\n".join(lines))
