"""Actions mixin for FileListPanel — context menu, file ops, undo, tags."""
import os
import logging
from contextlib import nullcontext
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QMimeData, QFileInfo, QObject
from PySide6.QtWidgets import (
    QApplication, QInputDialog, QMessageBox,
)
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
        self._undo_svc = None
        self._background_ops: list[QObject] = []

    @staticmethod
    def _consume_refresh_warnings(service) -> tuple[object, ...]:
        """Consume only the diagnostics belonging to the current Path command."""
        operation_id = getattr(service, "last_operation_id", None)
        drain = getattr(service, "drain_refresh_diagnostics", None)
        if callable(drain):
            try:
                diagnostics = drain(operation_id)
            except TypeError:
                diagnostics = drain()
            try:
                diagnostics = tuple(diagnostics)
            except TypeError:
                diagnostics = ()
            warnings = []
            for diagnostic_id, diagnostic_warnings in diagnostics:
                if operation_id is None or diagnostic_id == operation_id:
                    warnings.extend(diagnostic_warnings)
            return tuple(warnings)
        return tuple(getattr(service, "last_refresh_warnings", ()))

    # ── Clicks ───────────────────────────────────────────────────

    def _on_click(self, idx):
        # Only the legacy QListView surface reaches this handler; the grid
        # panel routes clicks through _on_grid_click. Guard defensively so a
        # viewless panel can never crash on a stray click event.
        if self._list_view is None:
            return
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
        if widget is self._list_view:
            idxs = self._view_selected_rows()
            paths = [self._model.path_at(i.row()) for i in idxs if i.isValid()]
        else:
            sel = self._detail_view.selectionModel().selectedRows()
            paths = [self._detail_model.data(i, Qt.ItemDataRole.UserRole)
                     for i in sel if i.isValid()]
        self._show_context_menu(
            [path for path in paths if isinstance(path, str)],
            widget.viewport().mapToGlobal(pos),
        )

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
        mutation = self._capture_mutation_context()
        if mutation is None:
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
        session, service, undo_service, lib_root = mutation
        dest = str(Path(self._current).resolve())
        is_cut = self._clipboard_cut
        operation = "move" if is_cut else "copy"
        self._show_operation_feedback(session, operation, running=True)
        if is_cut:
            self._clipboard_source = []
            self._clipboard_cut = False
        result_holder: list = []

        def _do_paste():
            with self._session_operation(session):
                try:
                    if is_cut:
                        result = service.move_to_directory(sources, dest, library_root=lib_root)
                        pairs = tuple(getattr(result, "moved_pairs", ()) or ())
                        if not pairs:
                            pairs = tuple(
                                zip(sources, getattr(result, "changed_paths", ()))
                            ) if result.ok else ()
                        for source, destination in pairs:
                            undo_service.record_rename(str(source), str(destination))
                    else:
                        result = service.copy_to_directory(sources, dest)
                except ValueError as error:
                    # The service collects OSError failures into result.errors
                    # but refuses out-of-library sources with ValueError, which
                    # would otherwise die silently inside the worker thread.
                    # Route the refusal through the normal feedback path.
                    from AssetsManager.application.file_operation_service import FileOperationResult
                    result = FileOperationResult((), (str(error),))
            result_holder.append(result)

        def _on_paste_done():
            if not self._is_current_operation_session(session):
                return
            if result_holder:
                result = result_holder[0]
                self._request_operation_selection(session, getattr(result, "changed_paths", ()))
                self._show_operation_feedback(
                    session,
                    operation,
                    changed_count=len(getattr(result, "changed_paths", ())),
                    errors=tuple(getattr(result, "errors", ())),
                    warnings=tuple(getattr(result, "warnings", ())),
                )
                if is_cut and not result.ok and not getattr(result, "changed_paths", ()):
                    # The cut markers were cleared before the worker ran; a
                    # wholly refused move (e.g. sources outside the library
                    # root) must not silently lose them.
                    self._clipboard_source = list(sources)
                    self._clipboard_cut = True
            self._post_refresh()
            if result_holder and not result_holder[0].ok:
                QMessageBox.warning(self, tr("filelist.dialog.paste_error"), "\n".join(result_holder[0].errors))

        self._run_in_background(_do_paste, on_done=_on_paste_done)

    def _can_paste(self) -> bool:
        """Expose both FileList and valid external file clipboard sources."""
        if self._clipboard_source:
            return True
        mime = QApplication.clipboard().mimeData()
        if mime is None:
            return False
        return any(
            url.isLocalFile() and url.toLocalFile()
            for url in mime.urls()
        )

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
            session = getattr(self._get_scoped_services(), "session", None)
            self._show_operation_feedback(session, "rename", running=True)
            try:
                new_path = self._rename_file_path(path, name.strip())
                service = self._get_file_operation_service()
                warnings = self._consume_refresh_warnings(service)
                self._request_operation_selection(session, [new_path])
                self._show_operation_feedback(
                    session,
                    "rename",
                    changed_count=1,
                    warnings=warnings,
                )
                self._post_refresh()
            except OSError as e:
                self._show_operation_feedback(session, "rename", errors=(str(e),))
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
        mutation = self._capture_mutation_context()
        if mutation is None:
            return
        names = "\n".join(f"  {Path(p).name}" for p in paths[:10])
        if len(paths) > 10:
            names += f"\n  ... and {len(paths) - 10} more"
        if QMessageBox.question(self, tr("filelist.dialog.move_trash"), f"Move to Recycle Bin?\n\n{names}",
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        session, service, _undo_service, lib_root = mutation
        path_list = [str(Path(path).resolve()) for path in paths]
        result_holder: list = []
        self._show_operation_feedback(session, "trash", running=True)

        def _do_delete():
            with self._session_operation(session):
                result = service.delete_to_trash(path_list, library_root=lib_root)
            result_holder.append(result)
            for error in result.errors:
                _log.error("Move to trash failed: %s", error)

        def _on_delete_done():
            if not self._is_current_operation_session(session):
                return
            if result_holder:
                result = result_holder[0]
                changed_paths = getattr(result, "changed_paths", ())
                errors = tuple(getattr(result, "errors", ()))
                if changed_paths:
                    candidates = self._deletion_selection_candidates(changed_paths)
                    self._request_operation_selection(session, candidates)
                self._show_operation_feedback(
                    session,
                    "trash",
                    changed_count=len(changed_paths),
                    errors=errors,
                    warnings=tuple(getattr(result, "warnings", ())),
                )
            self._post_refresh()

        self._run_in_background(_do_delete, on_done=_on_delete_done)

    def _delete_permanent(self, paths):
        mutation = self._capture_mutation_context()
        if mutation is None:
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
        session, service, undo_service, lib_root = mutation
        path_list = [str(Path(path).resolve()) for path in paths]
        result_holder: list = []
        self._show_operation_feedback(session, "permanent_delete", running=True)

        def _do_perm_delete():
            with self._session_operation(session):
                entries = [undo_service.prepare_delete(path) for path in path_list]
                try:
                    result = service.delete_permanent(path_list, library_root=lib_root)
                except Exception:
                    for entry in entries:
                        undo_service.discard_delete(entry)
                    raise
                changed_paths = {Path(path).resolve() for path in result.changed_paths}
                for path, entry in zip(path_list, entries):
                    if Path(path).resolve() in changed_paths:
                        if entry is not None:
                            undo_service.commit_delete(entry)
                    else:
                        undo_service.discard_delete(entry)
            result_holder.append(result)
            for error in result.errors:
                _log.error("Permanent delete failed: %s", error)

        def _on_perm_delete_done():
            if not self._is_current_operation_session(session):
                return
            if result_holder:
                result = result_holder[0]
                changed_paths = getattr(result, "changed_paths", ())
                errors = tuple(getattr(result, "errors", ()))
                if changed_paths:
                    candidates = self._deletion_selection_candidates(changed_paths)
                    self._request_operation_selection(session, candidates)
                self._show_operation_feedback(
                    session,
                    "permanent_delete",
                    changed_count=len(changed_paths),
                    errors=errors,
                    warnings=tuple(getattr(result, "warnings", ())),
                )
            self._post_refresh()

        self._run_in_background(_do_perm_delete, on_done=_on_perm_delete_done)

    def _new_folder(self):
        if self._get_scoped_services() is None:
            return
        name, ok = QInputDialog.getText(self, tr("filelist.dialog.new_folder"), tr("filelist.dialog.new_folder_label"), text="New Folder")
        if ok and name.strip():
            session = getattr(self._get_scoped_services(), "session", None)
            self._show_operation_feedback(session, "new_folder", running=True)
            try:
                service = self._get_file_operation_service()
                created = service.create_folder(self._current, name.strip())
                warnings = self._consume_refresh_warnings(service)
                self._request_operation_selection(session, [created])
                self._show_operation_feedback(
                    session,
                    "new_folder",
                    changed_count=1,
                    warnings=warnings,
                )
                self._post_refresh()
            except OSError as e:
                self._show_operation_feedback(session, "new_folder", errors=(str(e),))
                QMessageBox.warning(self, tr("dialog.error"), str(e))

    def _duplicate_selected(self):
        mutation = self._capture_mutation_context()
        if mutation is None:
            return
        session, service, _undo_service, _lib_root = mutation
        paths = [str(Path(path).resolve()) for path in self._selected_paths()]
        results: list[Path] = []
        errors: list[str] = []
        warnings: list = []
        self._show_operation_feedback(session, "duplicate", running=True)
        def _do_dup():
            with self._session_operation(session):
                for p in paths:
                    try:
                        results.append(service.duplicate(p, copy_label=" - Copy"))
                        warnings.extend(self._consume_refresh_warnings(service))
                    except OSError as error:
                        errors.append(str(error))
                        warnings.extend(self._consume_refresh_warnings(service))
        def _on_duplicate_done():
            if not self._is_current_operation_session(session):
                return
            self._request_operation_selection(session, results)
            self._show_operation_feedback(
                session,
                "duplicate",
                changed_count=len(results),
                errors=tuple(errors),
                warnings=tuple(warnings),
            )
            self._post_refresh()

        self._run_in_background(_do_dup, on_done=_on_duplicate_done)

    # ── Undo ─────────────────────────────────────────────────────

    def _undo(self):
        mutation = self._capture_mutation_context()
        if mutation is None:
            return
        session, service, undo_service, lib_root = mutation
        if not undo_service.can_undo():
            return
        entry = undo_service.peek_undo()
        target = self._history_selection_target(entry, undo=True)
        result_holder: list[bool] = []
        warnings_holder: list = []
        self._show_operation_feedback(session, "undo", running=True)

        def _do_undo():
            with self._session_operation(session):
                result_holder.append(undo_service.perform_undo(service, lib_root))
                warnings_holder.extend(self._consume_refresh_warnings(service))

        def _on_undo_done():
            if not self._is_current_operation_session(session):
                return
            if result_holder == [True] and target is not None:
                self._request_operation_selection(session, [target])
            self._show_operation_feedback(
                session, "undo", changed_count=1 if result_holder == [True] else 0,
                errors=() if result_holder == [True] else ("undo_failed",),
                warnings=tuple(warnings_holder),
            )
            if result_holder != [True]:
                self._offer_skip_poisoned_entry(undo=True)
            self._post_refresh()

        self._run_in_background(_do_undo, on_done=_on_undo_done)

    def _redo(self):
        mutation = self._capture_mutation_context()
        if mutation is None:
            return
        session, service, undo_service, lib_root = mutation
        if not undo_service.can_redo():
            return
        entry = undo_service.peek_redo()
        target = self._history_selection_target(entry, undo=False)
        deletion_candidates = (
            self._deletion_selection_candidates([entry.path])
            if getattr(entry, "type", None) == "delete"
            else ()
        )
        result_holder: list[bool] = []
        warnings_holder: list = []
        self._show_operation_feedback(session, "redo", running=True)

        def _do_redo():
            with self._session_operation(session):
                result_holder.append(undo_service.perform_redo(service, lib_root))
                warnings_holder.extend(self._consume_refresh_warnings(service))

        def _on_redo_done():
            if not self._is_current_operation_session(session):
                return
            if result_holder == [True]:
                if target is not None:
                    self._request_operation_selection(session, [target])
                elif deletion_candidates:
                    self._request_operation_selection(session, deletion_candidates)
            self._show_operation_feedback(
                session, "redo", changed_count=1 if result_holder == [True] else 0,
                errors=() if result_holder == [True] else ("redo_failed",),
                warnings=tuple(warnings_holder),
            )
            if result_holder != [True]:
                self._offer_skip_poisoned_entry(undo=False)
            self._post_refresh()

        self._run_in_background(_do_redo, on_done=_on_redo_done)

    @staticmethod
    def _history_selection_target(entry, *, undo: bool) -> str | None:
        """Return the path made visible by a successful undo or redo operation."""
        if getattr(entry, "type", None) == "rename":
            return entry.old if undo else entry.new
        if getattr(entry, "type", None) == "delete" and undo:
            return entry.path
        return None

    def _offer_skip_poisoned_entry(self, *, undo: bool):
        """Ask whether to drop a history entry whose execution keeps failing.

        A blocked entry would otherwise remain at the top of the stack and
        prevent every later undo/redo (LIFO), so the user gets an explicit
        skip option instead of a permanently poisoned history.
        """
        svc = self._undo_svc
        if svc is None:
            return
        method = "skip_poisoned_undo" if undo else "skip_poisoned_redo"
        skip = getattr(svc, method, None)
        if not callable(skip):
            return
        if QMessageBox.question(
            self,
            "Undo Failed",
            "The previous operation could not be completed.\n\n"
            "Skip this history entry? Skipping discards it permanently.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) == QMessageBox.StandardButton.Yes:
            skip()

    # ── Selection helpers ────────────────────────────────────────

    def _selected_paths(self):
        if self._view_mode == "Details":
            sel = self._detail_view.selectionModel().selectedRows()
            return [self._detail_model.data(i, Qt.ItemDataRole.UserRole)
                    for i in sel if i.isValid()]
        idxs = self._view_selected_rows()
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
        indices = self._view_selected_rows()
        if not indices:
            return
        paths = [self._model.path_at(i.row()) for i in indices if i.isValid()]
        if len(paths) > 1:
            self._batch_rename(paths)
        else:
            self._view_edit_index(indices[0])

    def _batch_rename(self, paths):
        from AssetsManager.panels.file_list._batch_rename_dialog import BatchRenameDialog

        dialog = BatchRenameDialog(paths, self)
        if dialog.exec() != dialog.DialogCode.Accepted or dialog.plan is None:
            return
        mutation = self._capture_mutation_context()
        if mutation is None:
            return
        session, service, undo_service, lib_root = mutation
        renamed = []
        errors = []
        warnings = []
        self._show_operation_feedback(session, "batch_rename", running=True)

        def _do_batch_rename():
            with self._session_operation(session):
                for entry in dialog.plan.changed_entries:
                    old = str(Path(entry.source).resolve())
                    new = str(Path(entry.target).resolve())
                    if old == new:
                        renamed.append(new)
                        continue
                    try:
                        service.move(old, new, library_root=lib_root or None)
                        undo_service.record_rename(old, new)
                        renamed.append(new)
                        warnings.extend(self._consume_refresh_warnings(service))
                    except (OSError, ValueError) as error:
                        errors.append(str(error))
                        warnings.extend(self._consume_refresh_warnings(service))

        def _on_batch_rename_done():
            if not self._is_current_operation_session(session):
                return
            self._request_operation_selection(session, renamed)
            self._show_operation_feedback(
                session,
                "batch_rename",
                changed_count=len(renamed),
                errors=tuple(errors),
                warnings=tuple(warnings),
            )
            self._post_refresh()

        self._run_in_background(_do_batch_rename, on_done=_on_batch_rename_done)

    # ── Tag dialogs ──────────────────────────────────────────────

    def _apply_tag_dialog(self, paths):
        if not self._lib_root:
            return
        svc = self._get_tag_service()
        tags = svc.get_all_tags(self._lib_root)
        tag, ok = QInputDialog.getItem(
            self, tr("filelist.dialog.apply_tag"), tr("filelist.dialog.tag_label"), tags, 0, True,
        )
        if ok and tag.strip():
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

    def _capture_mutation_context(self):
        """Snapshot scoped dependencies before a mutation reaches a worker."""
        scoped = self._get_scoped_services()
        if scoped is None:
            return None
        session = getattr(scoped, "session", None)
        root = getattr(session, "root", None)
        if not isinstance(root, (str, Path)):
            # Compatibility for unit seams; production scoped bundles always
            # supply a canonical session and root.
            session = None
            root = self._lib_root
        return (
            session,
            self._get_file_operation_service(),
            self._undo_svc,
            str(Path(root).resolve()) if root else None,
        )

    @staticmethod
    def _session_operation(session):
        return session.operation() if session is not None else nullcontext()

    def _run_in_background(self, func, *args, on_done=None):
        """Run func(*args) on a worker thread. If on_done provided, called on main thread."""
        from AssetsManager.panels.file_list._background import run_in_background
        run_in_background(func, *args, on_done=on_done, background_ops=self._background_ops)
