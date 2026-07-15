"""Actions mixin for FileListPanel — context menu, file ops, undo, tags."""
import os
import logging
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QMimeData, QFileInfo, QObject
from PySide6.QtWidgets import (
    QApplication, QMenu, QInputDialog, QMessageBox,
)
from AssetsManager.application import UndoService
from AssetsManager.core.signal_bus import get as bus
from AssetsManager import i18n

tr = i18n.tr
_log = logging.getLogger(__name__)


class ActionsMixin:
    """Provides context menu, file operations, undo stack, and tag dialogs."""

    def _init_actions(self):
        """Call from FileListPanel.__init__ to set up action state."""
        self._clipboard_source: list[str] = []
        self._clipboard_cut = False
        self._undo_svc = UndoService()
        self._background_ops: list[QObject] = []

    # ── Clicks ───────────────────────────────────────────────────

    def _on_click(self, idx):
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
            if self._last_click_row >= 0:
                start = min(self._last_click_row, idx.row())
                end = max(self._last_click_row, idx.row())
                sel = self._list_view.selectionModel()
                sel.clear()
                for r in range(start, end + 1):
                    sel.select(self._model.index(r, 0), sel.Select)
            return
        self._last_click_row = idx.row()
        path = self._model.path_at(idx.row())
        if path:
            self.file_selected.emit(QFileInfo(path))
            bus().file_focused.emit(str(path))

    def _on_double_click(self, idx):
        path = self._model.path_at(idx.row())
        if path and os.path.isdir(path):
            self.navigate_to(path)
        elif path:
            self.file_double_clicked.emit(path)

    def _on_tree_click(self, index, col=0):
        path = self._detail_model.data(index, Qt.ItemDataRole.UserRole)
        if not path:
            return
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
            if self._last_tree_item:
                sel_model = self._detail_view.selectionModel()
                prev_idx = sel_model.currentIndex()
                if prev_idx.isValid():
                    lo = min(prev_idx.row(), index.row())
                    hi = max(prev_idx.row(), index.row())
                    sel_model.clear()
                    for i in range(lo, hi + 1):
                        idx = self._detail_model.index(i, 0)
                        sel_model.select(idx, sel_model.SelectionFlag.Select | sel_model.SelectionFlag.Rows)
            return
        self._last_tree_item = index
        self.file_selected.emit(QFileInfo(path))
        bus().file_focused.emit(str(path))

    def _on_tree_double_click(self, index, col=0):
        path = self._detail_model.data(index, Qt.ItemDataRole.UserRole)
        if path and os.path.isdir(path):
            self.navigate_to(path)
        elif path:
            self.file_double_clicked.emit(path)

    # ── Context menu ────────────────────────────────────────────

    def _ctx_menu(self, pos):
        widget = self.sender()
        menu = QMenu(self)
        if widget is self._list_view:
            idxs = self._list_view.selectionModel().selectedRows()
            paths = [self._model.path_at(i.row()) for i in idxs if i.isValid()]
        else:
            sel = self._detail_view.selectionModel().selectedRows()
            paths = [self._detail_model.data(i, Qt.ItemDataRole.UserRole)
                     for i in sel if i.isValid()]

        if paths:
            p = paths[0]
            menu.addAction(tr("filelist.menu.open"), lambda: self._open_file(p))
            if os.path.isdir(p):
                menu.addAction(tr("filelist.menu.copy"), lambda: self._copy_paths(paths, False))
                menu.addAction(tr("filelist.menu.cut"), lambda: self._copy_paths(paths, True))
            else:
                open_with = menu.addMenu(tr("filelist.menu.open_with"))
                open_with.addAction(tr("filelist.menu.default"), lambda: self._open_file(p))
                from AssetsManager.core.tool_scheduler import list_tools, run_tool
                for tool in list_tools():
                    if "{file}" in str(tool.get("args", [])):
                        icon = tool.get("icon", "") or "🔧"
                        text = f"{icon}  {tool.get('name', 'Tool')}"
                        open_with.addAction(text, lambda checked, t=tool, fp=p: run_tool(t, file_path=fp))
            menu.addAction(tr("filelist.menu.copy_path"), lambda: QApplication.clipboard().setText(p))
            if os.path.isdir(p):
                menu.addAction(tr("filelist.menu.rename"), lambda: self._rename(p))
            menu.addAction(tr("filelist.menu.delete"), lambda: self._delete([p]))
            menu.addAction(tr("filelist.menu.delete_permanent"), lambda: self._delete_permanent([p]))
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
            # Plugin-contributed context menu items
            self._add_plugin_context_items(menu, p)
        else:
            if self._clipboard_source:
                menu.addAction(tr("filelist.menu.paste"), self._paste)
            menu.addAction(tr("filelist.menu.new_folder"), self._new_folder)
            menu.addSeparator()
            menu.addAction(tr("filelist.menu.open_explorer"), lambda: self._open_in_explorer(str(self._current)))
        menu.exec(widget.viewport().mapToGlobal(pos))

    def _open_file(self, path):
        if os.path.isdir(path):
            self.navigate_to(path)
        else:
            self._open_in_explorer(path)

    def _add_plugin_context_items(self, menu, file_path: str):
        """Add plugin-contributed context menu items to the menu."""
        try:
            from AssetsManager.application.plugin_service import PluginService
            from AssetsManager.core.plugins.manager import PluginManagerService
            svc = PluginService(PluginManagerService.get())
            host = getattr(svc, "_manager", None)
            if host is None:
                return
            ctx = getattr(host, "_host_context", None)
            if ctx is None:
                return
            items = ctx.context_menu_items(file_path)
            if items:
                plugin_menu = menu.addMenu(tr("filelist.menu.plugins"))
                for item in items:
                    plugin_menu.addAction(item.label, lambda cmd=item.command_id: self._run_plugin_command(cmd, file_path))
        except Exception:
            pass

    def _run_plugin_command(self, command_id: str, file_path: str):
        """Execute a plugin-contributed command."""
        try:
            app = QApplication.instance()
            if app:
                plugin_ctx = app.property("plugin_host_context")
                if plugin_ctx:
                    for cmd in plugin_ctx.commands():
                        if getattr(cmd, 'id', None) == command_id:
                            handler = getattr(cmd, 'handler', None)
                            if handler and callable(handler):
                                handler(file_path)
                                return
            _log.info("Plugin command '%s' triggered for %s (no handler found)", command_id, file_path)
        except Exception:
            _log.warning("Failed to execute plugin command '%s'", command_id, exc_info=True)

    @staticmethod
    def _open_in_explorer(path: str):
        """Open path in system file manager or default app (cross-platform)."""
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ── Clipboard ────────────────────────────────────────────────

    def _copy_paths(self, paths, cut):
        self._clipboard_source = list(paths)
        self._clipboard_cut = cut
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
        QApplication.clipboard().setMimeData(mime)

    def _paste(self):
        if self._get_scoped_services() is None:
            return
        sources = list(self._clipboard_source)
        if not sources:
            sources = [
                url.toLocalFile()
                for url in QApplication.clipboard().mimeData().urls()
                if url.isLocalFile() and url.toLocalFile()
            ]
        if not sources:
            return
        dest = str(self._current)
        is_cut = self._clipboard_cut
        lib_root = self._lib_root or None
        if is_cut:
            self._clipboard_source = []
            self._clipboard_cut = False
        panel = self
        result_holder: list = []

        def _do_paste():
            svc = panel._get_file_operation_service()
            if is_cut:
                result = svc.move_to_directory(sources, dest, library_root=lib_root)
                if result.ok:
                    for source, destination in zip(sources, result.changed_paths):
                        panel._undo_svc.record_rename(str(source), str(destination))
            else:
                result = svc.copy_to_directory(sources, dest)
            result_holder.append(result)

        def _on_paste_done():
            panel._post_refresh()
            if result_holder and not result_holder[0].ok:
                QMessageBox.warning(panel, tr("filelist.dialog.paste_error"), "\n".join(result_holder[0].errors))

        self._run_in_background(_do_paste, on_done=_on_paste_done)

    def _copy(self):
        p = self._selected_paths()
        if p:
            self._clipboard_source = p
            self._clipboard_cut = False

    def _copy_to_clipboard(self):
        p = self._selected_paths()
        if p:
            self._copy_paths(p, False)

    def _cut_to_clipboard(self):
        p = self._selected_paths()
        if p:
            self._copy_paths(p, True)

    def _cut(self):
        p = self._selected_paths()
        if p:
            self._clipboard_source = p
            self._clipboard_cut = True

    # ── File operations ──────────────────────────────────────────

    def _rename(self, path):
        old = Path(path).name
        name, ok = QInputDialog.getText(self, tr("filelist.dialog.rename"), tr("filelist.dialog.rename_label"), text=old)
        if ok and name.strip() and name.strip() != old:
            try:
                self._rename_file_path(path, name.strip())
                self._post_refresh()
            except OSError as e:
                QMessageBox.warning(self, tr("dialog.error"), str(e))

    def _rename_file_path(self, old_path: str, new_name: str, *, add_undo: bool = True) -> str:
        return self._rename_absolute(
            old_path,
            os.path.join(os.path.dirname(old_path), new_name),
            add_undo=add_undo,
        )

    def _rename_absolute(self, old_path: str, new_path: str, *, add_undo: bool = True) -> str:
        old = str(Path(old_path).resolve())
        new = str(Path(new_path).resolve())
        if old == new:
            return new
        if self._get_scoped_services() is None:
            return old
        try:
            self._get_file_operation_service().move(old, new, library_root=self._lib_root or None)
        except Exception:
            _log.exception("Rename failed: %s -> %s", old, new)
            raise
        if add_undo:
            self._undo_svc.record_rename(old, new)
        return new

    def _delete(self, paths, *, add_undo=True):
        if self._get_scoped_services() is None:
            return
        names = "\n".join(f"  {Path(p).name}" for p in paths[:10])
        if len(paths) > 10:
            names += f"\n  ... and {len(paths) - 10} more"
        if QMessageBox.question(self, tr("filelist.dialog.move_trash"), f"Move to Recycle Bin?\n\n{names}",
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        path_list = list(paths)
        panel = self

        def _do_delete():
            result = panel._get_file_operation_service().delete_to_trash(
                path_list, library_root=panel._lib_root or None,
            )
            for error in result.errors:
                _log.error("Move to trash failed: %s", error)

        self._run_in_background(_do_delete, on_done=lambda: panel._post_refresh())

    def _delete_permanent(self, paths):
        if self._get_scoped_services() is None:
            return
        names = "\n".join(f"  {Path(p).name}" for p in paths[:10])
        if len(paths) > 10:
            names += f"\n  ... and {len(paths) - 10} more"
        r = QMessageBox.warning(self, tr("filelist.dialog.delete_permanent"),
            f"Permanently delete?\n\n{names}\n\nYou can undo this deletion.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if r != QMessageBox.StandardButton.Yes:
            return
        path_list = list(paths)
        panel = self

        def _do_perm_delete():
            entries = [panel._undo_svc.prepare_delete(path) for path in path_list]
            try:
                result = panel._get_file_operation_service().delete_permanent(
                    path_list, library_root=panel._lib_root or None,
                )
            except Exception:
                for entry in entries:
                    panel._undo_svc.discard_delete(entry)
                raise
            changed_paths = {Path(path).resolve() for path in result.changed_paths}
            for path, entry in zip(path_list, entries):
                if Path(path).resolve() in changed_paths:
                    if entry is not None:
                        panel._undo_svc.commit_delete(entry)
                else:
                    panel._undo_svc.discard_delete(entry)
            for error in result.errors:
                _log.error("Permanent delete failed: %s", error)

        self._run_in_background(_do_perm_delete, on_done=lambda: panel._post_refresh())

    def _new_folder(self):
        name, ok = QInputDialog.getText(self, tr("filelist.dialog.new_folder"), tr("filelist.dialog.new_folder_label"), text="New Folder")
        if ok and name.strip():
            try:
                self._get_file_operation_service().create_folder(self._current, name.strip())
                self._post_refresh()
            except OSError as e:
                QMessageBox.warning(self, tr("dialog.error"), str(e))

    def _duplicate_selected(self):
        paths = list(self._selected_paths())
        panel = self
        def _do_dup():
            for p in paths:
                try:
                    panel._get_file_operation_service().duplicate(p, copy_label=" - Copy")
                except OSError:
                    pass
        self._run_in_background(_do_dup, on_done=lambda: panel._post_refresh())

    # ── Undo ─────────────────────────────────────────────────────

    def _undo(self):
        if self._get_scoped_services() is None:
            return
        if not self._undo_svc.can_undo():
            return
        panel = self
        def _do_undo():
            panel._undo_svc.perform_undo(
                panel._get_file_operation_service(), panel._lib_root
            )
        self._run_in_background(_do_undo, on_done=lambda: panel._post_refresh())

    def _redo(self):
        if self._get_scoped_services() is None:
            return
        if not self._undo_svc.can_redo():
            return
        panel = self
        def _do_redo():
            panel._undo_svc.perform_redo(
                panel._get_file_operation_service(), panel._lib_root
            )
        self._run_in_background(_do_redo, on_done=lambda: panel._post_refresh())

    # ── Selection helpers ────────────────────────────────────────

    def _selected_paths(self):
        if self._view_mode == "Details":
            sel = self._detail_view.selectionModel().selectedRows()
            return [self._detail_model.data(i, Qt.ItemDataRole.UserRole)
                    for i in sel if i.isValid()]
        idxs = self._list_view.selectionModel().selectedRows()
        return [self._model.path_at(i.row()) for i in idxs if i.isValid()]

    def _open_selected(self):
        paths = self._selected_paths()
        if paths:
            self._open_file(paths[0])

    def _delete_selected(self):
        self._delete(self._selected_paths())

    def _delete_selected_permanent(self):
        self._delete_permanent(self._selected_paths())

    def _inline_rename(self):
        if self._view_mode == "Details":
            sel = self._detail_view.selectionModel().selectedRows()
            if sel:
                if len(sel) > 1:
                    self._batch_rename([self._detail_model.data(i, Qt.ItemDataRole.UserRole)
                                         for i in sel if i.isValid()])
                else:
                    self._detail_view.edit(sel[0])
            return
        indices = self._list_view.selectionModel().selectedRows()
        if not indices:
            return
        paths = [self._model.path_at(i.row()) for i in indices if i.isValid()]
        if len(paths) > 1:
            self._batch_rename(paths)
        else:
            self._list_view.edit(indices[0])

    def _batch_rename(self, paths):
        name, ok = QInputDialog.getText(self, tr("filelist.dialog.batch_rename"),
            tr("filelist.dialog.batch_pattern"), text="{name}_{n}")
        if ok and name.strip():
            pattern = name.strip()
            counter = 1
            for p in sorted(paths):
                src = Path(p)
                new_name = pattern.replace("{name}", src.stem).replace("{n}", str(counter))
                new = os.path.join(str(src.parent), new_name + src.suffix)
                if new != str(src):
                    try:
                        self._rename_absolute(str(src), new)
                        counter += 1
                    except OSError:
                        pass
            self._post_refresh()

    # ── Tag dialogs ──────────────────────────────────────────────

    def _apply_tag_dialog(self, paths):
        if not self._lib_root:
            return
        tag, ok = QInputDialog.getText(self, tr("filelist.dialog.apply_tag"), tr("filelist.dialog.tag_label"))
        if ok and tag.strip():
            svc = self._get_tag_service()
            for p in paths:
                svc.add_tag(self._lib_root, p, tag.strip())
            self._post_refresh()

    def _remove_tag_dialog(self, paths):
        if not self._lib_root:
            return
        tag, ok = QInputDialog.getText(self, tr("filelist.dialog.remove_tag"), tr("filelist.dialog.tag_label"))
        if ok and tag.strip():
            svc = self._get_tag_service()
            for p in paths:
                svc.remove_tag(self._lib_root, p, tag.strip())
            self._post_refresh()

    def _manage_tags_dialog(self, paths):
        if not self._lib_root:
            return
        from AssetsManager.application.tag_service import TagServiceAdapter
        from AssetsManager.dialogs.tag_editor_dialog import TagEditorDialog
        scoped = self._get_scoped_services()
        adapter = TagServiceAdapter(self._lib_root, scoped.tag_service if scoped is not None else None)
        dlg = TagEditorDialog(adapter, paths[0] if paths else str(self._current), self)
        dlg.exec()
        self._post_refresh()

    # ── Properties ───────────────────────────────────────────────

    def _show_properties(self, path):
        fi = QFileInfo(path)
        size = fi.size()
        sz = f"{size:.1f} B"
        for unit in ["KB", "MB", "GB", "TB"]:
            size /= 1024
            if size < 1024:
                sz = f"{size:.1f} {unit}"
                break
        type_str = tr("filelist.prop_folder") if fi.isDir() else tr("filelist.prop_file", ext=fi.suffix().upper())
        info = (
            f"{tr('filelist.prop_name')}: {fi.fileName()}\n"
            f"{tr('filelist.prop_type')}: {type_str}\n"
            f"{tr('filelist.prop_size')}: {sz}\n"
            f"{tr('filelist.prop_modified')}: {fi.lastModified().toString('yyyy-MM-dd HH:mm:ss')}\n"
            f"{tr('filelist.prop_path')}: {fi.absolutePath()}"
        )
        QMessageBox.information(self, tr("filelist.properties"), info)

    # ── Background ops ───────────────────────────────────────────

    def _run_in_background(self, func, *args, on_done=None):
        """Run func(*args) on a worker thread. If on_done provided, called on main thread."""
        from AssetsManager.panels.file_list._background import run_in_background
        run_in_background(func, *args, on_done=on_done, background_ops=self._background_ops)
