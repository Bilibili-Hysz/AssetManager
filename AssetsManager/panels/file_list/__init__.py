"""File list panel — QWidget grid canvas replacing QListView.

QWidgetFileListPanel is the default implementation. FileListPanel (in _base.py)
is the original QListView-based panel kept for compatibility.
"""
import logging
import os
from pathlib import Path

from PySide6.QtCore import (
    Qt, QTimer, QEasingCurve, QVariantAnimation, QModelIndex, QRect, QPoint, QEvent, Signal, QFileInfo, QObject, QSize,
    QItemSelectionModel,
)
from PySide6.QtWidgets import (
    QWidget, QMenu, QApplication, QSizePolicy, QTreeView, QAbstractItemView, QHeaderView, QStyledItemDelegate,
)
from AssetsManager.core import icons

from AssetsManager.core import themes
from AssetsManager.core.signal_bus import get as bus
from AssetsManager.core.color_utils import alpha
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager import i18n
from AssetsManager.panels.file_list._base import FileListPanel
from AssetsManager.panels.file_list._common import IMAGE_EXTS, ZOOM_PRESETS
from AssetsManager.panels.file_list._grid_layout import GridLayout
from AssetsManager.panels.file_list._grid_widget import FileListGridWidget
from AssetsManager.panels.file_list._thumbnail_delivery import ThumbnailDeliveryCoordinator
from AssetsManager.panels.file_list._detail_model import DetailModel
from AssetsManager.panels.file_list._commands import FileListCommand, FileListCommandContext
from AssetsManager.application.tag_service import TagServiceAdapter

_log = logging.getLogger(__name__)
tr = i18n.tr


class _DetailsItemDelegate(QStyledItemDelegate):
    """Keep Details rows comfortably readable without per-row widgets."""

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        size.setHeight(max(size.height(), scaled_px(32)))
        return size


class _ListShim:
    """Thin compatibility shim bridging _list_view API to _grid_widget."""

    def __init__(self, panel):
        self._p = panel
        self._selection_model = _SelShim(panel)

    @property
    def gw(self):
        return self._p._grid_widget

    def viewport(self):
        return self.gw

    def verticalScrollBar(self):
        return self.gw._scrollbar

    def selectionModel(self):
        return self._selection_model

    def clearSelection(self):
        self.gw.clear_selection()

    def selectAll(self):
        self.gw.select_all()

    def indexAt(self, pos):
        row = self.gw._layout.row_at(pos.x(), pos.y() + self.gw._scroll_y) if self.gw._layout else -1
        if row >= 0:
            return self._p._model.index(row, 0)
        return QModelIndex()

    def visualRect(self, idx):
        if self._p._grid_layout and idx.isValid():
            r = self._p._grid_layout.rect_at(idx.row())
            if r:
                return QRect(r.x(), r.y() - self.gw._scroll_y, r.width(), r.height())
        return QRect()

    def edit(self, idx):
        if idx.isValid() and hasattr(self.gw, '_start_rename'):
            self.gw._start_rename(idx.row())
            return True
        return False

    def setVisible(self, v): self.gw.setVisible(v)
    def setViewMode(self, _m): pass
    def setIconSize(self, _sz): pass
    def scheduleDelayedItemsLayout(self): self.gw.update()
    def set_zoom_in_progress(self, _v): pass
    def clear_render_cache(self): self.gw.invalidate_textures()
    def setStyleSheet(self, _s): pass
    def hide(self): self.gw.hide()
    def deleteLater(self): pass


class _SelShim(QObject):
    """SelectionModel shim for ActionsMixin compatibility."""
    selectionChanged = Signal()
    Select = QItemSelectionModel.SelectionFlag.Select

    def __init__(self, panel):
        super().__init__(panel)
        self._p = panel

    def clear(self):
        self._p._grid_widget.clear_selection()

    def select(self, idx, flags):
        if not idx.isValid():
            return
        gw = self._p._grid_widget
        old = gw._selection.copy()
        if flags & QItemSelectionModel.SelectionFlag.Clear:
            gw._selection.clear()
        if flags & QItemSelectionModel.SelectionFlag.Select:
            gw._selection.add(idx.row())
        if old != gw._selection:
            gw._apply_selection_progress(old)
            gw.selection_changed.emit()
            self.selectionChanged.emit()
            gw.update()

    def currentIndex(self):
        row = self._p._last_click_row
        if row < 0 and self._p._grid_widget._selection:
            row = next(iter(self._p._grid_widget._selection))
        if row >= 0:
            return self._p._model.index(row, 0)
        return QModelIndex()

    def selectedRows(self):
        rows = []
        for r in self._p._grid_widget.selection_model_rows():
            idx = self._p._model.index(r, 0)
            if idx.isValid():
                rows.append(idx)
        return rows

    def isSelected(self, idx):
        return idx.row() in self._p._grid_widget.selection_model_rows()


class QWidgetFileListPanel(FileListPanel):
    """Drop-in QWidget-canvas variant. Inherits all toolbar/header from FileListPanel."""

    def __init__(self, parent=None):
        super().__init__(parent)

        # Remove top margin for header alignment; keep side/bottom margins matching dock panels
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

        self._list_view = _ListShim(self)
        self._connect_bus(bus().language_changed, self._refresh_language)
        self._connect_bus(bus().ui_scale_changed, self._on_ui_scale_changed)
        self.initialize_navigation()

        from AssetsManager.domain.events import FileSystemChanged
        self._file_op_timer = QTimer(self)
        self._file_op_timer.setSingleShot(True)
        self._file_op_timer.setInterval(500)
        self._file_op_timer.timeout.connect(self._post_refresh)
        self._connect_domain_event(FileSystemChanged, self._on_file_operation)

    def _set_grid_performance_context(self, recorder, session_token: str, generation: int) -> None:
        self._grid_widget.set_performance_context(recorder, session_token, generation)

    def _refresh_language(self, _code=""):
        self._retranslate_controls()
        self._detail_model.headerDataChanged.emit(
            Qt.Orientation.Horizontal, 0, len(self._detail_model.HEADER_KEYS) - 1)
        self._update_status()

    def _on_ui_scale_changed(self, _scale: float) -> None:
        """Re-measure canvas text and Details chrome after a live scale change."""
        self._grid_widget.refresh_scale()
        self._grid_widget.update_layout(self._model.rowCount(), self._grid_widget.width())
        self._detail_view.setIconSize(QSize(scaled_px(18), scaled_px(18)))
        self._detail_view.header().setMinimumHeight(scaled_px(30))
        self._apply_detail_theme()

    def _on_file_operation(self, event):
        if getattr(self._model, "_is_shutdown", False):
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

    def clone(self):
        new = QWidgetFileListPanel()
        new.navigate_to(str(self._current))
        return new

    def _on_grid_click(self, row: int):
        self._last_click_row = row
        path = self._model.path_at(row)
        if path:
            info = QFileInfo(path)
            self.file_selected.emit(info)
            bus().file_focused.emit(str(path))

    def _on_grid_double_click(self, row: int):
        ent = self._model.entry_at(row)
        if ent:
            if ent.is_dir():
                self.navigate_to(ent.path)
            else:
                self.file_double_clicked.emit(ent.path)

    def _on_grid_context(self, global_pos: QPoint):
        sel_rows = self._grid_widget.selection_model_rows()
        paths = [self._model.path_at(r) for r in sel_rows]
        self._show_context_menu([p for p in paths if p], global_pos)

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

    def _show_context_menu(self, paths: list[str], global_pos: QPoint):
        self._build_context_menu(paths, global_pos).exec(global_pos)

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
                        action.setIcon(icons.icon(tool.get("icon_name") or tool.get("icon"), color=themes.get()["heading"], size=scaled_px(16), fallback="wrench"))
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

    @staticmethod
    def _always(_context: FileListCommandContext) -> bool:
        return True

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

    @staticmethod
    def _add_command_group(
        menu: QMenu,
        commands: tuple[FileListCommand, ...],
        context: FileListCommandContext,
        group: str,
    ) -> None:
        projected = [command for command in commands if command.group == group and command.visible_when(context)]
        if not projected:
            return
        if menu.actions():
            menu.addSeparator()
        for command in projected:
            action = menu.addAction(tr(command.label_key), command.invoke)
            action.setEnabled(command.enabled_when(context))
            if command.shortcut:
                action.setShortcut(command.shortcut)

    def _select_all(self):
        if self._view_mode == "Details":
            self._detail_view.selectAll()
        else:
            self._grid_widget.select_all()
        self._update_status()

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

    def _rename_grid_row(self, row: int, new_name: str):
        ent = self._model.entry_at(row)
        if not ent:
            return
        self._rename_path(ent.path, new_name)

    def _rename_detail_row(self, row: int, new_name: str):
        if not (0 <= row < len(self._detail_model._entries)):
            return
        self._rename_path(self._detail_model._entries[row].path, new_name)

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

    def _navigate_or_open(self, path: str):
        if os.path.isdir(path):
            self.navigate_to(path)
        else:
            self.file_double_clicked.emit(path)

    def _populate_details(self):
        self._capture_detail_selection()
        scoped = self._get_scoped_services()
        store = (
            TagServiceAdapter(self._lib_root, scoped.tag_service)
            if scoped is not None and self._lib_root
            else None
        )
        self._detail_model.set_source(self._model, store=store, lib_root=self._lib_root)
        self._restore_detail_selection()
        self._update_status()

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

    def _selected_detail_paths(self) -> list[str]:
        sel = self._detail_view.selectionModel().selectedRows()
        return [p for p in (
            self._detail_model.data(i, Qt.ItemDataRole.UserRole)
            for i in sel if i.isValid()
        ) if isinstance(p, str)]

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

    def _restore_detail_selection(self):
        paths = self._pending_detail_paths
        if paths is None:
            return
        self._pending_detail_paths = None
        self._select_detail_paths(paths)

    def _select_detail_paths(self, paths: set[str]) -> None:
        sm = self._detail_view.selectionModel()
        sm.clearSelection()
        for row, entry in enumerate(self._detail_model._entries):
            if entry.path in paths:
                idx = self._detail_model.index(row, 0)
                if idx.isValid():
                    sm.select(idx, QItemSelectionModel.SelectionFlag.Select
                              | QItemSelectionModel.SelectionFlag.Rows)

    def _on_detail_dir_size_ready(self, dir_path: str, size_str: str, gen: int = 0):
        if getattr(self._model, "_is_shutdown", False):
            return
        if gen and gen != self._model._dir_size_gen:
            return
        self._model._pending_dir_sizes.discard(dir_path)
        self._model._subtitle_cache[dir_path] = size_str
        self._model._dir_size_cache[dir_path] = size_str
        # Find the row for this directory and emit dataChanged for Size column only
        for i, entry in enumerate(self._detail_model._entries):
            if entry.path == dir_path:
                idx = self._detail_model.index(i, 2)  # Size column
                if idx.isValid():
                    self._detail_model.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DisplayRole])
                break

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

    def _on_scan_started(self, generation: int):
        self._pending_scan_generation = generation

    def _on_file_list_state_changed(self, _state: str, generation: int, _error) -> None:
        if generation == self._model.scan_generation:
            self._update_status()

    def _on_scan_committed(self, generation: int):
        """Present each populated scan generation once after its model reset completes."""
        if generation != self._pending_scan_generation:
            return
        self._pending_scan_generation = None
        if generation <= self._presentation_generation:
            return
        self._presentation_generation = generation
        result_paths = self._consume_operation_selection()
        scan_reused = bool(getattr(self._model, "_last_scan_reused", False))
        self._model._last_scan_reused = False
        if scan_reused:
            self._grid_widget.set_performance_generation(generation)
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

    def _load_visible_if_active(self):
        """Ignore delayed scan presentation work after panel shutdown."""
        if not self._model._is_shutdown:
            self._load_visible()

    def _apply_list_theme(self):
        pass

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

    def _on_theme_changed(self, _name):
        t = themes.get()
        self._header.setStyleSheet(
            f"background: {themes.header_for_dock()}; border: 1px solid {t['border']}; "
            f"border-top-left-radius: {scaled_px(7)}px; border-top-right-radius: {scaled_px(7)}px; ")
        self._header_title.setStyleSheet(
            f"color: {t['heading']}; font-size: {scaled_pt(12)}px; font-weight: bold; "
            f"background: transparent; border: none; padding: 2px 4px;")
        self._fst_status_style()
        for btn in self._nav_buttons:
            btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {t['body']}; "
                f"border: none; padding: 0; font-size: {scaled_pt(10)}px; }} "
                f"QPushButton:hover {{ background: {alpha(t['panel'], 0.50)}; border-radius: {scaled_px(3)}px; "
                f"color: {t['heading']}; }}")
        self._grid_widget.refresh_theme()
        self._apply_detail_theme()

    def _sync_selection_anim(self):
        pass

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

    def _restore_grid_selection(self):
        paths = self._pending_selection_paths
        if paths is None:
            return
        self._pending_selection_paths = None
        self._select_grid_paths(paths)

    def _on_grid_selection_changed(self) -> None:
        if self._pending_scan_generation == self._model.scan_generation:
            self._pending_selection_paths = {
                path for row in self._grid_widget.selection_model_rows()
                if (path := self._model.path_at(row)) is not None
            }

    def _select_grid_paths(self, paths: set[str]) -> None:
        old = self._grid_widget._selection.copy()
        self._grid_widget._selection = {
            row for path, row in self._model._path_index.items()
            if path in paths
        }
        if old != self._grid_widget._selection:
            self._grid_widget._apply_selection_progress(old)
            self._grid_widget.selection_changed.emit()
            self._grid_widget.update()

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
        entries = self._detail_model._entries if self._view_mode == "Details" else self._model._entries
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

    def _restore_operation_selection(self, paths: tuple[str, ...]) -> None:
        if self._view_mode == "Details":
            self._pending_detail_paths = set(paths)
            self._restore_detail_selection()
        else:
            self._pending_selection_paths = set(paths)
            self._restore_grid_selection()

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
        if self._zoom_anim and self._zoom_anim.state() == QVariantAnimation.State.Running:
            self._zoom_anim.stop()
        start = self._thumb_size
        if start == target:
            # Rebase an interrupted transition before committing its current
            # size, otherwise the previous target's scroll anchor can snap.
            if self._grid_widget._zoom_relayout_active:
                self._grid_widget.begin_zoom(target, anchor_pos)
                self._on_zoom_done(generation)
            return

        self._grid_widget.begin_zoom(target, anchor_pos)
        if getattr(self._grid_widget, "_reduce_motion", False) is True:
            self._thumb_size = target
            self._grid_widget.set_zoom_thumb_size(target)
            self._on_zoom_done(generation, target)
            return

        distance = abs(target - start)
        duration = min(220, 150 + round(distance * 1.1))
        self._zoom_anim = QVariantAnimation(self)
        self._zoom_anim.setDuration(duration)
        self._zoom_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._zoom_anim.setStartValue(start)
        self._zoom_anim.setEndValue(target)
        self._zoom_anim.valueChanged.connect(self._on_zoom_frame)
        self._zoom_anim.finished.connect(lambda: self._on_zoom_done(generation, target))
        self._zoom_anim.start()

    def _on_zoom_frame(self, size: int):
        if getattr(self._model, "_is_shutdown", False):
            return
        self._thumb_size = size
        self._grid_widget.set_zoom_thumb_size(size)

    def _on_zoom_done(self, generation: int | None = None, target_size: int | None = None):
        if getattr(self._model, "_is_shutdown", False):
            return
        if generation is not None and generation != getattr(self, "_zoom_generation", 0):
            return
        if target_size is not None:
            self._thumb_size = target_size
        self._loader.set_size(self._thumb_size)
        self._grid_widget.set_thumb_size(self._thumb_size)
        self._grid_widget.update_layout(self._model.rowCount(), self._grid_widget.width())
        self._grid_widget.finish_zoom()
        self._grid_widget.invalidate_textures()
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

    def _smooth_scroll(self, event):
        sb = self._grid_widget._scrollbar
        target = sb.value() - event.angleDelta().y()
        if not hasattr(self, '_scroll_anim'):
            self._scroll_anim = None
        if self._scroll_anim and self._scroll_anim.state() == QVariantAnimation.State.Running:
            target = self._scroll_anim.endValue() - event.angleDelta().y()
            self._scroll_anim.stop()
        generation = self._begin_smooth_scroll()
        self._grid_widget.set_scrolling()
        self._scroll_anim = QVariantAnimation(self)
        self._scroll_anim.setDuration(120)
        self._scroll_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._scroll_anim.setStartValue(sb.value())
        self._scroll_anim.setEndValue(target)
        self._scroll_anim.valueChanged.connect(lambda v: self._set_scroll_animation_value(sb, v))
        self._scroll_anim.finished.connect(lambda: self._finish_smooth_scroll(generation))
        self._scroll_anim.start()

    def _load_visible(self):
        if getattr(self._model, "_is_shutdown", False):
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
            elif ent.is_file() and Path(ent.name).suffix.lower() in IMAGE_EXTS:
                candidates.append((i, ent.path, priority, None))
                retained_paths.add(ent.path)
        self._loader.retain_deferred(retained_paths)
        for row, path, priority, item_path in candidates:
            self._loader.request(row, path, priority=priority, item_path=item_path)

    def _on_thumbnail_ready(self, row: int, path: str, img):
        if getattr(self._model, "_is_shutdown", False):
            return
        self._thumbnail_delivery.handle_ready(row, path, img)

    def _flush_thumb_batch(self):
        self._thumbnail_delivery.flush()

    def _toast(self, text: str):
        from AssetsManager.panels.file_list._toast import Toast
        Toast(text, parent=self._grid_widget, duration_ms=2000)

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

    def _update_status(self):
        state = getattr(self._model, "list_state", None)
        if state is not None and state == getattr(self._model, "STATE_LOADING", None):
            self._status.setText(tr("filelist.state.loading"))
            return
        if state is not None and state == getattr(self._model, "STATE_SCAN_ERROR", None):
            self._status.setText(tr("filelist.state.scan_error"))
            return
        if state is not None and state == getattr(self._model, "STATE_EMPTY_FOLDER", None):
            self._status.setText(tr("filelist.empty"))
            return
        if state is not None and state == getattr(self._model, "STATE_EMPTY_FILTERED", None):
            self._status.setText(tr("filelist.state.empty_filtered"))
            return
        total = self._model.rowCount()
        mode = self._view_mode
        if self._view_mode == "Details":
            sel = len(self._detail_view.selectionModel().selectedRows())
            if sel > 0:
                self._status.setText(tr("filelist.status_selected", sel=sel, total=total, sz="", mode=mode))
            else:
                self._status.setText(tr("filelist.status_total", total=total, sz="", mode=mode))
        elif hasattr(self, '_grid_widget') and self._grid_widget is not None:
            if self._cached_total_sz < 0:
                self._compute_total_sz()
            sz_str = self._controller.format_total_size_suffix(self._cached_total_sz)
            sel = len(self._grid_widget.selection_model_rows())
            if sel > 0:
                self._status.setText(tr("filelist.status_selected", sel=sel, total=total, sz=sz_str, mode=mode))
            else:
                self._status.setText(tr("filelist.status_total", total=total, sz=sz_str, mode=mode))
        else:
            self._status.setText(tr("filelist.status_total", total=total, sz="", mode=mode))

    def _handle_key(self, event):
        from AssetsManager.panels.file_list._shortcuts import handle_key
        return handle_key(self, event)

    def _copy_selected(self):
        self._copy_to_clipboard()

    def _cut_selected(self):
        self._cut_to_clipboard()

    def eventFilter(self, obj, event):
        if not hasattr(self, '_grid_widget') or self._grid_widget is None:
            return super().eventFilter(obj, event)
        t = event.type()

        if t == QEvent.Type.DragEnter:
            return self._on_drag_enter(event)
        if t == QEvent.Type.DragMove:
            return self._accept_drag(event)
        if t == QEvent.Type.Drop:
            return self._on_drop(event)
        if t == QEvent.Type.KeyPress:
            return self._handle_key(event)

        if self._detail_view and (obj is self._detail_view or obj is self._detail_view.viewport()):
            return super().eventFilter(obj, event)

        if obj is self._grid_widget or obj is self._search:
            if t == QEvent.Type.Wheel:
                if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                    self._wheel_zoom_evt(event, obj)
                    return True
                self._smooth_scroll(event)
                return True
            if t in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove,
                     QEvent.Type.MouseButtonRelease):
                return super().eventFilter(obj, event)
            return QWidget.eventFilter(self, obj, event)

        return super().eventFilter(obj, event)

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
        return super()._on_drop(event)

    @staticmethod
    def _is_external_drop(event) -> bool:
        urls = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile()]
        return bool(urls)
