"""File list panel — QWidget grid canvas replacing QListView.

QWidgetFileListPanel is the default implementation. FileListPanel (in _base.py)
is the original QListView-based panel kept for compatibility.
"""
import logging
import os
from pathlib import Path

from PySide6.QtCore import (
    Qt, QTimer, QEasingCurve, QVariantAnimation, QModelIndex, QRect, QPoint, QEvent, Signal, QFileInfo, QObject,
    QItemSelectionModel,
)
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QWidget, QMenu, QApplication, QSizePolicy, QTreeView, QAbstractItemView,
)

from AssetsManager.core import themes
from AssetsManager.core.signal_bus import get as bus
from AssetsManager.core.color_utils import alpha
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager import i18n
from AssetsManager.panels.file_list._base import FileListPanel
from AssetsManager.panels.file_list._model import FileSystemModel
from AssetsManager.panels.file_list._common import IMAGE_EXTS, ZOOM_PRESETS
from AssetsManager.panels.file_list._grid_layout import GridLayout
from AssetsManager.panels.file_list._grid_widget import FileListGridWidget
from AssetsManager.panels.file_list._detail_model import DetailModel

_log = logging.getLogger(__name__)
tr = i18n.tr


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

        # Thumbnail batch processing
        self._thumb_batch: set[int] = set()
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(50)
        self._thumb_timer.timeout.connect(self._flush_thumb_batch)

        self._grid_widget = FileListGridWidget()
        self._grid_widget.set_model(self._model)
        self._grid_layout = GridLayout()
        self._grid_widget.set_layout_ref(self._grid_layout)
        self._grid_widget.clicked.connect(self._on_grid_click)
        self._grid_widget.double_clicked.connect(self._on_grid_double_click)
        self._grid_widget.context_menu.connect(self._on_grid_context)
        self._grid_widget.selection_changed.connect(self._update_status)
        self._grid_widget.rename_requested.connect(self._rename_grid_row)
        self._model.modelAboutToBeReset.connect(self._capture_grid_selection)
        self._model.modelAboutToBeReset.connect(self._capture_detail_selection)
        self._model.modelReset.connect(self._on_grid_model_reset)

        # Reconnect scroll debounce to grid widget's scrollbar
        self._scroll_debounce.timeout.disconnect()
        self._grid_widget._scrollbar.valueChanged.connect(
            lambda: self._scroll_debounce.start())
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
        self._detail_view.setModel(self._detail_model)
        self._detail_view.setRootIsDecorated(False)
        self._detail_view.setItemsExpandable(False)
        self._detail_view.setIndentation(0)
        self._detail_view.selectionModel().selectionChanged.connect(self._on_detail_selection_changed)
        self._detail_view.header().setStretchLastSection(True)
        self._detail_view.header().setSortIndicatorShown(True)
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
        self.initialize_navigation()

        from AssetsManager.domain.events import FileRenamed, FileDeleted, FileCreated
        self._file_op_timer = QTimer(self)
        self._file_op_timer.setSingleShot(True)
        self._file_op_timer.setInterval(200)
        self._file_op_timer.timeout.connect(self._post_refresh)
        self._connect_domain_event(FileRenamed, self._on_file_operation)
        self._connect_domain_event(FileDeleted, self._on_file_operation)
        self._connect_domain_event(FileCreated, self._on_file_operation)

    def _refresh_language(self, _code=""):
        self._detail_model.headerDataChanged.emit(
            Qt.Orientation.Horizontal, 0, len(self._detail_model.HEADER_KEYS) - 1)
        self._update_status()

    def _on_file_operation(self, event):
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
        self._show_context_menu([p for p in paths if p], self._detail_view.viewport().mapToGlobal(pos))

    def _show_context_menu(self, paths: list[str], global_pos: QPoint):
        menu = QMenu(self)
        if paths:
            p = paths[0]
            menu.addAction(tr("filelist.menu.open"), lambda p=p: self._navigate_or_open(p))
            if not os.path.isdir(p):
                open_with = menu.addMenu(tr("filelist.menu.open_with"))
                open_with.addAction(tr("filelist.menu.default"), lambda p=p: self._navigate_or_open(p))
                from AssetsManager.core.tool_scheduler import list_tools, run_tool
                for tool in list_tools():
                    if "{file}" in str(tool.get("args", [])):
                        icon = tool.get("icon", "") or "🔧"
                        text = f"{icon}  {tool.get('name', 'Tool')}"
                        open_with.addAction(text, lambda checked, t=tool, fp=p: run_tool(t, file_path=fp))
            menu.addAction(tr("filelist.menu.copy"), lambda: self._copy_paths(paths, False))
            menu.addAction(tr("filelist.menu.cut"), lambda: self._copy_paths(paths, True))
            menu.addAction(tr("filelist.menu.copy_path"), lambda p=p: QApplication.clipboard().setText(p))
            if len(paths) == 1:
                menu.addAction(tr("filelist.menu.rename"), lambda: self._rename(p))
            menu.addAction(tr("filelist.menu.delete"), lambda: self._delete(paths))
            menu.addAction(tr("filelist.menu.delete_permanent"), lambda: self._delete_permanent(paths))
            menu.addSeparator()
            menu.addAction(tr("filelist.menu.duplicate"), self._duplicate_selected)
            menu.addAction(tr("filelist.menu.undo"), self._undo)
            tag_menu = menu.addMenu(tr("filelist.menu.tags"))
            tag_menu.addAction(tr("filelist.menu.apply_tag"), lambda: self._apply_tag_dialog(paths))
            tag_menu.addAction(tr("filelist.menu.remove_tag"), lambda: self._remove_tag_dialog(paths))
            tag_menu.addSeparator()
            tag_menu.addAction(tr("filelist.menu.manage_tags"), lambda: self._manage_tags_dialog(paths))
            menu.addSeparator()
            menu.addAction(tr("filelist.properties"), lambda: self._show_properties(p))
            menu.addSeparator()
            menu.addAction(tr("filelist.menu.open_explorer"), lambda: self._open_in_explorer(
                str(Path(p).parent) if not os.path.isdir(p) else p))
            menu.addSeparator()
            menu.addAction(tr("sharing.quick_share"), lambda: self._quick_share_from_context(paths, global_pos))
        else:
            if self._clipboard_source:
                menu.addAction(tr("filelist.menu.paste"), self._paste)
            menu.addAction(tr("filelist.menu.new_folder"), self._new_folder)
            menu.addSeparator()
            menu.addAction(tr("filelist.menu.open_explorer"), lambda: self._open_in_explorer(str(self._current)))
        menu.exec(global_pos)

    def _quick_share_from_context(self, paths: list[str], global_pos):
        """Delegate Quick Share to the main window's LanSharingMixin."""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        win = app.activeWindow() if app else None
        if win is None and app:
            for w in app.topLevelWidgets():
                if w.isVisible() and hasattr(w, '_show_quick_share_card'):
                    win = w
                    break
        if win and hasattr(win, '_show_quick_share_card'):
            win._show_quick_share_card(paths, global_pos)

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
        try:
            self._rename_file_path(old_path, new_name)
            self._post_refresh()
        except OSError as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, tr("dialog.error"), str(e))

    def _navigate_or_open(self, path: str):
        if os.path.isdir(path):
            self.navigate_to(path)
        else:
            self.file_double_clicked.emit(path)

    def _populate_details(self):
        self._capture_detail_selection()
        store = self._get_tag_store(self._lib_root)
        self._detail_model.set_source(self._model, store=store, lib_root=self._lib_root)
        self._restore_detail_selection()
        self._update_status()

    def _on_detail_selection_changed(self):
        self._update_status()
        sel = self._detail_view.selectionModel().selectedRows()
        if sel:
            path = self._detail_model.data(sel[0], Qt.ItemDataRole.UserRole)
            if path:
                info = QFileInfo(path)
                self.file_selected.emit(info)
                bus().file_focused.emit(str(path))

    def _selected_detail_paths(self) -> list[str]:
        sel = self._detail_view.selectionModel().selectedRows()
        return [p for p in (
            self._detail_model.data(i, Qt.ItemDataRole.UserRole)
            for i in sel if i.isValid()
        ) if p]

    def _capture_detail_selection(self):
        if not hasattr(self, '_detail_model') or not hasattr(self, '_detail_view'):
            return
        sel = self._detail_view.selectionModel().selectedRows()
        paths = {
            path for path in (
                self._detail_model.data(i, Qt.ItemDataRole.UserRole) for i in sel if i.isValid()
            ) if path
        }
        if paths:
            self._pending_detail_paths = paths

    def _restore_detail_selection(self):
        paths = getattr(self, '_pending_detail_paths', set())
        if not paths:
            return
        self._pending_detail_paths = set()
        sm = self._detail_view.selectionModel()
        sm.clearSelection()
        for row, entry in enumerate(self._detail_model._entries):
            if entry.path in paths:
                idx = self._detail_model.index(row, 0)
                if idx.isValid():
                    sm.select(idx, QItemSelectionModel.SelectionFlag.Select
                              | QItemSelectionModel.SelectionFlag.Rows)

    def _on_detail_dir_size_ready(self, dir_path: str, size_str: str, gen: int = 0):
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
        if self._view_mode == "Details":
            # The first reset of an async refresh clears source entries. Keep
            # the captured paths until the populated scan result arrives.
            if self._model.rowCount():
                self._populate_details()
            return
        self._grid_widget.update_layout(self._model.rowCount(), self._grid_widget.width())
        self._restore_grid_selection()
        self._grid_widget._start_entrance_stagger()
        QTimer.singleShot(80, self._load_visible)

    def _apply_list_theme(self):
        pass

    def _apply_detail_theme(self):
        """Apply theme styling to the detail view (QTreeView)."""
        t = themes.get()
        self._detail_view.header().setStyleSheet(
            f"QHeaderView::section {{"
            f"  background: {t['header']}; color: {t['heading']}; "
            f"  border: none; border-right: 1px solid {alpha(t['border'], 0.25)}; "
            f"  padding: 4px 8px; font-size: {scaled_pt(12)}px; font-weight: bold; "
            f"}}"
            f"QHeaderView::down-arrow, QHeaderView::up-arrow {{ "
            f"  width: 10px; height: 10px; "
            f"}}")
        self._detail_view.setStyleSheet(
            f"QTreeView {{"
            f"  background: {t['panel']}; color: {t['body']}; "
            f"  border: none; font-size: {scaled_pt(12)}px; "
            f"}}"
            f"QTreeView::item {{"
            f"  padding: 3px 6px; border: none; "
            f"}}"
            f"QTreeView::item:selected {{"
            f"  background: {alpha(t['accent'], 0.30)}; color: {t['heading']}; "
            f"}}"
            f"QTreeView::item:hover {{"
            f"  background: {alpha(t['accent'], 0.12)}; "
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
        self._pending_selection_paths = {
            path for path in (
                self._model.path_at(r) for r in self._grid_widget.selection_model_rows()
            ) if path
        }

    def _restore_grid_selection(self):
        paths = getattr(self, '_pending_selection_paths', set())
        if not paths:
            return
        old = self._grid_widget._selection.copy()
        self._grid_widget._selection = {
            row for path, row in self._model._path_index.items()
            if path in paths
        }
        self._pending_selection_paths = set()
        if old != self._grid_widget._selection:
            self._grid_widget._apply_selection_progress(old)
            self._grid_widget.selection_changed.emit()
            self._grid_widget.update()

    def _on_view_changed(self, _index):
        mode = self._view_mode
        self._view_memory[str(self._current)] = mode
        self._loader.set_size(self._thumb_size)
        is_detail = mode == "Details"
        self._grid_widget.setVisible(not is_detail)
        self._detail_view.setVisible(is_detail)
        if not is_detail:
            self._grid_widget.update_layout(self._model.rowCount(), self._grid_widget.width())
            self._load_visible()
        else:
            self._populate_details()
        self._update_status()

    def _on_zoom_changed(self, val):
        target = int(val.replace("px", ""))
        if not hasattr(self, '_zoom_anim'):
            self._zoom_anim = None
        if self._zoom_anim and self._zoom_anim.state() == QVariantAnimation.State.Running:
            self._zoom_anim.stop()
        start = self._thumb_size
        if start == target:
            return
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
        self._grid_widget.set_thumb_size(size)
        self._grid_widget.update_layout(self._model.rowCount(), self._grid_widget.width())

    def _on_zoom_done(self):
        self._loader.set_size(self._thumb_size)
        self._grid_widget.set_thumb_size(self._thumb_size)
        self._grid_widget.invalidate_textures()
        self._grid_widget.update_layout(self._model.rowCount(), self._grid_widget.width())
        self._load_visible()

    def _wheel_zoom_evt(self, event):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            idx = self._zoom_combo.currentIndex()
            if delta > 0 and idx < len(ZOOM_PRESETS) - 1:
                self._zoom_combo.setCurrentIndex(idx + 1)
            elif delta < 0 and idx > 0:
                self._zoom_combo.setCurrentIndex(idx - 1)
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
        self._scroll_anim = QVariantAnimation()
        self._scroll_anim.setDuration(120)
        self._scroll_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._scroll_anim.setStartValue(sb.value())
        self._scroll_anim.setEndValue(target)
        self._scroll_anim.valueChanged.connect(lambda v: sb.setValue(int(v)))
        self._scroll_anim.start()

    def _load_visible(self):
        total = self._model.rowCount()
        if total == 0:
            return
        if self._view_mode != "Grid":
            return
        vh = self._grid_widget.height()
        sy = self._grid_widget._scroll_y
        visible = self._grid_layout.visible_rows(sy, vh)
        cols = self._grid_layout.columns
        extra = max(2, cols) * 3
        first = max(0, min(visible[0] if visible else 0, total - 1) - extra)
        last = min(total - 1, max(visible[-1] if visible else 0, 0) + extra)
        for i in range(first, last + 1):
            ent = self._model.entry_at(i)
            if not ent:
                continue
            if ent.is_dir():
                preview = self._first_image_cached(ent.path)
                if preview:
                    self._loader.request(i, preview, priority=0, item_path=ent.path)
            elif ent.is_file() and Path(ent.name).suffix.lower() in IMAGE_EXTS:
                self._loader.request(i, ent.path, priority=0)

    def _on_thumbnail_ready(self, row: int, path: str, img):
        """Main-thread handler — convert QImage to QPixmap."""
        if img is None or img.isNull():
            return
        pixmap = QPixmap.fromImage(img)
        idx = self._model.index(row, 0)
        if not idx.isValid():
            return
        if self._model.path_at(row) != path:
            return
        ent = self._model.entry_at(row)
        if ent:
            self._model._raw_pixmaps[ent.path] = pixmap
        self._model.setData(idx, QIcon(pixmap), Qt.ItemDataRole.DecorationRole)
        self._thumb_batch.add(row)
        self._thumb_timer.start()
        self._grid_widget.mark_loaded(row)

    def _flush_thumb_batch(self):
        if not self._thumb_batch:
            return
        rows = sorted(self._thumb_batch)
        self._thumb_batch.clear()
        start = prev = rows[0]
        for row in rows[1:] + [None]:
            if row is not None and row == prev + 1:
                prev = row
                continue
            self._model.dataChanged.emit(
                self._model.index(start, 0),
                self._model.index(prev, 0),
                [FileSystemModel.RAW_PIXMAP_ROLE])
            if row is not None:
                start = prev = row
        self._grid_widget.on_thumb_batch(rows)

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
        self._hidden_btn.setText("◉" if self._model._show_hidden else "•")
        self._update_status()

    def _update_status(self):
        total = self._model.rowCount()
        mode = self._view_mode
        if self._view_mode == "Details":
            sel = len(self._detail_view.selectionModel().selectedRows())
            if sel > 0:
                self._status.setText(tr("filelist.status_selected", sel=sel, total=total, sz="", mode=mode))
            else:
                self._status.setText(tr("filelist.status_total", total=total, sz="", mode=mode))
        elif hasattr(self, '_grid_widget') and self._grid_widget is not None:
            self._compute_total_sz()
            sz_str = ""
            if self._cached_total_sz > 0:
                sz_str = f"  |  {FileSystemModel._fmt_size(self._cached_total_sz)}"
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
                    self._wheel_zoom_evt(event)
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
        urls = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile()]
        if not urls:
            return False
        dest = str(self._current)
        external = [u for u in urls if os.path.dirname(u) != dest]
        if not external:
            return False
        result = self._get_file_operation_service().copy_to_directory(external, dest)
        for error in result.errors:
            _log.error("Drag-drop copy failed: %s", error)
        self._post_refresh()
        if self._view_mode == "Details":
            self._populate_details()
        self._load_visible()
        return True

    @staticmethod
    def _is_external_drop(event) -> bool:
        urls = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile()]
        return bool(urls)
