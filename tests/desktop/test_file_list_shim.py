import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelectionModel, QMimeData, QUrl
from PySide6.QtWidgets import QApplication

from AssetsManager.application.bootstrap import ApplicationBootstrap
from AssetsManager.panels.file_list import QWidgetFileListPanel


def test_grid_selection_shim_supports_actions_api(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel.navigate_to(str(tmp_path), set_root=True)
        panel._model._wait_for_scan()
        panel._grid_widget.update_layout(panel._model.rowCount(), 400)

        selection = panel._list_view.selectionModel()
        first = panel._model.index(0, 0)
        selection.select(first, QItemSelectionModel.SelectionFlag.Select)

        assert selection.currentIndex().isValid()
        assert [idx.row() for idx in selection.selectedRows()] == [0]

        selection.clear()

        assert selection.selectedRows() == []
    finally:
        panel.shutdown()
        app.processEvents()


def test_grid_selection_shim_emits_selection_changed(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel.navigate_to(str(tmp_path), set_root=True)
        panel._model._wait_for_scan()
        panel._grid_widget.update_layout(panel._model.rowCount(), 400)

        selection = panel._list_view.selectionModel()
        seen = []
        selection.selectionChanged.connect(lambda: seen.append(True))

        selection.select(panel._model.index(0, 0), QItemSelectionModel.SelectionFlag.Select)

        assert seen == [True]
    finally:
        panel.shutdown()
        app.processEvents()


def test_grid_selection_survives_sort_by_path(tmp_path):
    (tmp_path / "b.txt").write_text("b")
    (tmp_path / "a.txt").write_text("a")
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel.navigate_to(str(tmp_path), set_root=True)
        panel._model._wait_for_scan()
        panel._grid_widget.update_layout(panel._model.rowCount(), 400)
        target = str(tmp_path / "b.txt")
        row = panel._model._path_index[target]
        panel._grid_widget._selection = {row}

        panel._model.set_sort("name", asc=True)

        selected = [panel._model.path_at(r) for r in panel._grid_widget.selection_model_rows()]
        assert selected == [target]
    finally:
        panel.shutdown()
        app.processEvents()


def test_grid_selection_drops_filtered_paths(tmp_path):
    (tmp_path / "image.png").write_text("image")
    (tmp_path / "readme.txt").write_text("readme")
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel.navigate_to(str(tmp_path), set_root=True)
        panel._model._wait_for_scan()
        panel._grid_widget.update_layout(panel._model.rowCount(), 400)
        panel._grid_widget._selection = {panel._model._path_index[str(tmp_path / "readme.txt")]}

        panel._model.set_filter(category="images")

        assert panel._grid_widget.selection_model_rows() == set()
    finally:
        panel.shutdown()
        app.processEvents()


def test_set_root_uses_injected_scoped_library_runtime(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    try:
        session = bootstrap.library_service.open_session(tmp_path)
        panel.set_scoped_services(bootstrap.for_library(session))

        panel.navigate_to(str(tmp_path), set_root=True)

        assert panel._model._metadata_service is not None
        assert panel._model._metadata_service._connection(tmp_path) is session.db_conn
        assert panel._loader._db_conn is session.db_conn
        assert panel._loader._cache_dir == session.thumb_dir_str
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_external_drop_uses_scoped_file_operation_service(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from AssetsManager.panels.file_list._base import FileListPanel

    library = tmp_path / "library"
    library.mkdir()
    external = tmp_path / "external.txt"
    external.write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    try:
        scoped = bootstrap.for_library(bootstrap.library_service.open_session(library))
        panel.set_scoped_services(scoped)
        panel.navigate_to(str(library), set_root=True)
        panel._post_refresh = Mock()
        panel._load_visible = Mock()

        class DropEvent:
            def __init__(self, *paths):
                self.paths = paths

            def mimeData(self):
                class MimeData:
                    def urls(self):
                        class Url:
                            def toLocalFile(self):
                                return str(external)
                        return [Url()]
                return MimeData()

        copied = Mock(return_value=type("Result", (), {"errors": ()})())
        monkeypatch.setattr(scoped.file_operation_service, "copy_to_directory", copied)

        assert panel._on_drop(DropEvent()) is True
        copied.assert_called_once_with(
            [str(external)], str(library), library_root=str(library),
        )

        copied.reset_mock()
        assert FileListPanel._on_drop(panel, DropEvent()) is True
        copied.assert_called_once_with(
            [str(external)], str(library), library_root=str(library),
        )
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_in_library_drop_moves_and_records_only_successful_undo_entries(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from AssetsManager.application.file_operation_service import FileOperationResult
    from AssetsManager.panels.file_list._base import FileListPanel

    library = tmp_path / "library"
    source = library / "asset.txt"
    failed_source = library / "failed.txt"
    destination = library / "destination"
    library.mkdir()
    destination.mkdir()
    source.write_text("asset")
    failed_source.write_text("failed")
    moved = destination / "asset-renamed.txt"
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    try:
        scoped = bootstrap.for_library(bootstrap.library_service.open_session(library))
        panel.set_scoped_services(scoped)
        panel._current = destination
        panel._post_refresh = Mock()
        panel._load_visible = Mock()
        panel._undo_svc = Mock()

        class DropEvent:
            def __init__(self, *paths):
                self.paths = paths

            def mimeData(self):
                class MimeData:
                    def __init__(self, paths):
                        self.paths = paths

                    def urls(self):
                        class Url:
                            def __init__(self, path):
                                self.path = path

                            def toLocalFile(self):
                                return str(self.path)
                        return [Url(path) for path in self.paths]
                return MimeData(self.paths)

        move = Mock(side_effect=[
            FileOperationResult((moved,), ()),
            FileOperationResult((), ("move failed",)),
        ])
        copy = Mock()
        monkeypatch.setattr(scoped.file_operation_service, "move_to_directory", move)
        monkeypatch.setattr(scoped.file_operation_service, "copy_to_directory", copy)

        assert panel._on_drop(DropEvent(source, failed_source)) is True

        assert move.call_args_list == [
            (([str(source)], str(destination)), {"library_root": str(library)}),
            (([str(failed_source)], str(destination)), {"library_root": str(library)}),
        ]
        copy.assert_not_called()
        panel._undo_svc.record_rename.assert_called_once_with(str(source), str(moved))

        panel._undo_svc.reset_mock()
        move.reset_mock()
        move.side_effect = None
        move.return_value = FileOperationResult((moved,), ())
        assert FileListPanel._on_drop(panel, DropEvent(source)) is True
        panel._undo_svc.record_rename.assert_called_once_with(str(source), str(moved))

    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_external_drop_without_scoped_services_refuses_copy(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from AssetsManager.panels.file_list._base import FileListPanel

    library = tmp_path / "library"
    external = tmp_path / "external.txt"
    library.mkdir()
    external.write_text("asset")
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel._current = library
        copy_service = Mock()
        monkeypatch.setattr(panel, "_get_file_operation_service", copy_service)

        class DropEvent:
            def mimeData(self):
                class MimeData:
                    def urls(self):
                        class Url:
                            def toLocalFile(self):
                                return str(external)
                        return [Url()]
                return MimeData()

        assert panel._on_drop(DropEvent()) is False
        assert FileListPanel._on_drop(panel, DropEvent()) is False
        copy_service.assert_not_called()
    finally:
        panel.shutdown()
        app.processEvents()


def test_paste_uses_scoped_service_for_local_system_clipboard_urls(tmp_path, monkeypatch):
    from unittest.mock import Mock

    library = tmp_path / "library"
    library.mkdir()
    external = tmp_path / "external.txt"
    external.write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    try:
        scoped = bootstrap.for_library(bootstrap.library_service.open_session(library))
        panel.set_scoped_services(scoped)
        panel.navigate_to(str(library), set_root=True)
        panel._run_in_background = lambda func, *args, on_done=None: (func(), on_done and on_done())
        panel._post_refresh = Mock()
        copied = Mock(return_value=type("Result", (), {"ok": True, "errors": ()})())
        monkeypatch.setattr(scoped.file_operation_service, "copy_to_directory", copied)

        mime = QMimeData()
        local_url = QUrl.fromLocalFile(str(external))
        mime.setUrls([local_url])
        QApplication.clipboard().setMimeData(mime)

        panel._paste()

        copied.assert_called_once_with([local_url.toLocalFile()], str(library))
        panel._post_refresh.assert_called_once()

        copied.reset_mock()
        panel._post_refresh.reset_mock()
        mime = QMimeData()
        mime.setUrls([QUrl("https://example.com/asset"), QUrl()])
        QApplication.clipboard().setMimeData(mime)

        panel._paste()

        copied.assert_not_called()
        panel._post_refresh.assert_not_called()
    finally:
        QApplication.clipboard().clear()
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_paste_without_scoped_services_refuses_external_and_internal_clipboards(tmp_path, monkeypatch):
    from unittest.mock import Mock

    library = tmp_path / "library"
    library.mkdir()
    external = tmp_path / "external.txt"
    external.write_text("asset")
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel._current = library
        panel._post_refresh = Mock()
        service = Mock()
        monkeypatch.setattr(panel, "_get_file_operation_service", service)

        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(external))])
        QApplication.clipboard().setMimeData(mime)

        panel._paste()

        service.assert_not_called()
        panel._post_refresh.assert_not_called()

        panel._clipboard_source = [str(external)]
        panel._clipboard_cut = True
        panel._paste()

        service.assert_not_called()
        panel._post_refresh.assert_not_called()
        assert panel._clipboard_source == [str(external)]
        assert panel._clipboard_cut is True
    finally:
        QApplication.clipboard().clear()
        panel.shutdown()
        app.processEvents()


def test_cut_paste_records_undo_only_after_successful_move(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from AssetsManager.application.file_operation_service import FileOperationResult

    library = tmp_path / "library"
    library.mkdir()
    source = library / "asset.txt"
    source.write_text("asset")
    second_source = library / "second.txt"
    second_source.write_text("second")
    destination = library / "destination"
    destination.mkdir()
    moved = destination / source.name
    second_moved = destination / second_source.name
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    try:
        scoped = bootstrap.for_library(bootstrap.library_service.open_session(library))
        panel.set_scoped_services(scoped)
        panel._current = destination

        def run_inline(func, *args, on_done=None):
            func()
            if on_done:
                on_done()

        panel._run_in_background = run_inline
        panel._post_refresh = Mock()
        panel._undo_svc = Mock()
        move = Mock(return_value=FileOperationResult((moved, second_moved), ()))
        monkeypatch.setattr(scoped.file_operation_service, "move_to_directory", move)
        monkeypatch.setattr(
            "AssetsManager.panels.file_list._actions.QMessageBox.warning",
            Mock(),
        )

        panel._clipboard_source = [str(source), str(second_source)]
        panel._clipboard_cut = True
        panel._paste()

        move.assert_called_once_with(
            [str(source), str(second_source)], str(destination), library_root=str(library),
        )
        assert panel._undo_svc.record_rename.call_args_list == [
            ((str(source), str(moved)),),
            ((str(second_source), str(second_moved)),),
        ]

        panel._undo_svc.reset_mock()
        move.reset_mock()
        panel._clipboard_source = [str(source), str(second_source)]
        panel._clipboard_cut = True
        move.return_value = FileOperationResult((moved, second_moved), ("move failed",))

        panel._paste()

        panel._undo_svc.record_rename.assert_not_called()
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_delete_to_trash_skips_undo_backup_and_scopes_service(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from PySide6.QtWidgets import QMessageBox

    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    target = tmp_path / "asset.txt"
    target.write_text("asset")
    try:
        panel.navigate_to(str(tmp_path), set_root=True)
        panel.set_scoped_services(bootstrap.for_library(bootstrap.library_service.open_session(tmp_path)))
        panel._undo_svc = Mock()
        panel._post_refresh = Mock()
        service = Mock()
        service.delete_to_trash.return_value = type("Result", (), {"errors": ()})()
        monkeypatch.setattr(panel, "_get_file_operation_service", lambda: service)
        monkeypatch.setattr(
            "AssetsManager.panels.file_list._actions.QMessageBox.question",
            lambda *args: QMessageBox.StandardButton.Yes,
        )
        def run_inline(func, *args, on_done=None):
            func()
            if on_done:
                on_done()

        panel._run_in_background = run_inline

        panel._delete([str(target)])

        panel._undo_svc.record_delete.assert_not_called()
        service.delete_to_trash.assert_called_once_with([str(target)], library_root=str(tmp_path))
        panel._post_refresh.assert_called_once()
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_permanent_delete_records_undo_only_after_scoped_delete_succeeds(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from AssetsManager.application.file_operation_service import FileOperationResult
    from PySide6.QtWidgets import QMessageBox

    library = tmp_path / "library"
    target = library / "asset.txt"
    library.mkdir()
    target.write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    try:
        scoped = bootstrap.for_library(bootstrap.library_service.open_session(library))
        panel.set_scoped_services(scoped)
        panel._run_in_background = lambda func, *args, on_done=None: (func(), on_done and on_done())
        panel._post_refresh = Mock()
        service = Mock()
        service.delete_permanent.return_value = FileOperationResult((target,), ())
        monkeypatch.setattr(panel, "_get_file_operation_service", lambda: service)
        monkeypatch.setattr(
            "AssetsManager.panels.file_list._actions.QMessageBox.warning",
            lambda *args: QMessageBox.StandardButton.Yes,
        )

        panel._delete_permanent([str(target)])

        service.delete_permanent.assert_called_once_with([str(target)], library_root=str(library))
        assert panel._undo_svc.can_undo()
        assert panel._undo_svc.peek_undo().path == str(target)
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_failed_permanent_delete_discards_backup_without_undo_history(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from AssetsManager.application.file_operation_service import FileOperationResult
    from PySide6.QtWidgets import QMessageBox

    library = tmp_path / "library"
    target = library / "asset.txt"
    library.mkdir()
    target.write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    try:
        scoped = bootstrap.for_library(bootstrap.library_service.open_session(library))
        panel.set_scoped_services(scoped)
        panel._run_in_background = lambda func, *args, on_done=None: (func(), on_done and on_done())
        panel._post_refresh = Mock()
        service = Mock()
        service.delete_permanent.return_value = FileOperationResult((), ("blocked",))
        monkeypatch.setattr(panel, "_get_file_operation_service", lambda: service)
        monkeypatch.setattr(
            "AssetsManager.panels.file_list._actions.QMessageBox.warning",
            lambda *args: QMessageBox.StandardButton.Yes,
        )

        panel._delete_permanent([str(target)])

        service.delete_permanent.assert_called_once_with([str(target)], library_root=str(library))
        assert not panel._undo_svc.can_undo()
        assert list(Path(panel._undo_svc._undo_dir).iterdir()) == []
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_partial_permanent_delete_commits_only_changed_path_backups(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from AssetsManager.application.file_operation_service import FileOperationResult
    from PySide6.QtWidgets import QMessageBox

    library = tmp_path / "library"
    first_target = library / "first.txt"
    second_target = library / "second.txt"
    library.mkdir()
    first_target.write_text("first")
    second_target.write_text("second")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    try:
        scoped = bootstrap.for_library(bootstrap.library_service.open_session(library))
        panel.set_scoped_services(scoped)
        panel._run_in_background = lambda func, *args, on_done=None: (func(), on_done and on_done())
        panel._post_refresh = Mock()
        service = Mock()
        service.delete_permanent.return_value = FileOperationResult(
            (first_target,), ("second delete failed",),
        )
        monkeypatch.setattr(panel, "_get_file_operation_service", lambda: service)
        monkeypatch.setattr(
            "AssetsManager.panels.file_list._actions.QMessageBox.warning",
            lambda *args: QMessageBox.StandardButton.Yes,
        )

        panel._delete_permanent([str(first_target), str(second_target)])

        assert panel._undo_svc.can_undo()
        assert panel._undo_svc.peek_undo().path == str(first_target)
        assert len(list(Path(panel._undo_svc._undo_dir).iterdir())) == 1
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_panel_undo_redo_use_perform_methods(tmp_path, monkeypatch):
    from unittest.mock import Mock

    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel._run_in_background = lambda func, *args, on_done=None: (func(), on_done and on_done())
        panel._post_refresh = Mock()
        panel._undo_svc = Mock()
        panel._undo_svc.can_undo.return_value = True
        panel._undo_svc.can_redo.return_value = True
        service = Mock()
        monkeypatch.setattr(panel, "_get_scoped_services", lambda: Mock())
        monkeypatch.setattr(panel, "_get_file_operation_service", lambda: service)

        panel._undo()
        panel._redo()

        panel._undo_svc.perform_undo.assert_called_once_with(service, panel._lib_root)
        panel._undo_svc.perform_redo.assert_called_once_with(service, panel._lib_root)
    finally:
        panel.shutdown()
        app.processEvents()


def test_failed_grid_rename_does_not_record_undo(tmp_path, monkeypatch):
    from unittest.mock import Mock

    source = tmp_path / "asset.txt"
    source.write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    try:
        panel.set_scoped_services(bootstrap.for_library(bootstrap.library_service.open_session(tmp_path)))
        panel._undo_svc = Mock()
        service = Mock()
        service.move.side_effect = OSError("rename failed")
        monkeypatch.setattr(panel, "_get_file_operation_service", lambda: service)

        import pytest

        with pytest.raises(OSError, match="rename failed"):
            panel._rename_file_path(str(source), "renamed.txt")

        service.move.assert_called_once()
        panel._undo_svc.record_rename.assert_not_called()
        assert source.exists()
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_covered_mutations_refuse_without_scoped_services(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from PySide6.QtWidgets import QMessageBox

    source = tmp_path / "asset.txt"
    destination = tmp_path / "renamed.txt"
    source.write_text("asset")
    QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        service = Mock()
        panel._post_refresh = Mock()
        panel._undo_svc = Mock()
        panel._undo_svc.can_undo.return_value = True
        panel._undo_svc.can_redo.return_value = True
        run_in_background = Mock()
        panel._run_in_background = run_in_background
        monkeypatch.setattr(panel, "_get_file_operation_service", lambda: service)
        question = Mock(return_value=QMessageBox.StandardButton.Yes)
        warning = Mock(return_value=QMessageBox.StandardButton.Yes)
        monkeypatch.setattr(
            "AssetsManager.panels.file_list._actions.QMessageBox.question", question,
        )
        monkeypatch.setattr(
            "AssetsManager.panels.file_list._actions.QMessageBox.warning", warning,
        )

        assert panel._rename_absolute(str(source), str(destination)) == str(source.resolve())
        panel._delete([str(source)])
        panel._delete_permanent([str(source)])
        panel._undo()
        panel._redo()

        service.assert_not_called()
        question.assert_not_called()
        warning.assert_not_called()
        panel._undo_svc.perform_undo.assert_not_called()
        panel._undo_svc.perform_redo.assert_not_called()
        run_in_background.assert_not_called()
        panel._post_refresh.assert_not_called()
        assert source.exists()
    finally:
        panel.shutdown()


def test_unscoped_mutations_never_construct_unbound_services(tmp_path, monkeypatch):
    """Mutation paths must fail closed before reaching fallback constructors."""
    from unittest.mock import Mock

    from AssetsManager.panels.file_list._base import FileListPanel

    source = tmp_path / "asset.txt"
    destination = tmp_path / "renamed.txt"
    source.write_text("asset")
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        panel._clipboard_source = [str(source)]
        panel._clipboard_cut = False
        panel._post_refresh = Mock()
        panel._run_in_background = Mock()
        panel._undo_svc = Mock()
        panel._undo_svc.can_undo.return_value = True
        panel._undo_svc.can_redo.return_value = True
        monkeypatch.setattr(
            "AssetsManager.application.FileOperationService",
            lambda: (_ for _ in ()).throw(AssertionError("unbound FileOperationService constructed")),
        )
        monkeypatch.setattr(
            "AssetsManager.application.UndoService",
            lambda: (_ for _ in ()).throw(AssertionError("unbound UndoService constructed")),
        )

        assert panel._rename_absolute(str(source), str(destination)) == str(source.resolve())
        panel._paste()
        assert FileListPanel._on_drop(panel, type("Drop", (), {"mimeData": lambda self: type("Mime", (), {"urls": lambda self: [type("Url", (), {"toLocalFile": lambda self: str(source)})()]})()})()) is False
        panel._delete([str(source)])
        panel._delete_permanent([str(source)])
        panel._new_folder()
        panel._duplicate_selected()
        panel._undo()
        panel._redo()

        panel._run_in_background.assert_not_called()
        panel._post_refresh.assert_not_called()
    finally:
        panel.shutdown()
        app.processEvents()


def test_panel_shutdown_does_not_cleanup_bootstrap_owned_undo_service(tmp_path, monkeypatch):
    from unittest.mock import Mock

    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    scoped = bootstrap.for_library(bootstrap.library_service.open_session(tmp_path))
    panel.set_scoped_services(scoped)
    cleanup = Mock()
    monkeypatch.setattr(scoped.undo_service, "cleanup", cleanup)

    try:
        panel.shutdown()
        cleanup.assert_not_called()
    finally:
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_file_list_does_not_construct_unbound_undo_service(monkeypatch):
    """The panel receives its undo service only through scoped injection."""
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(
        "AssetsManager.application.UndoService",
        lambda: (_ for _ in ()).throw(AssertionError("unbound UndoService constructed")),
    )

    panel = QWidgetFileListPanel()
    try:
        assert panel._undo_svc is None
    finally:
        panel.shutdown()
        app.processEvents()
