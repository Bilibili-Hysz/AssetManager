import os
from pathlib import Path
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelectionModel, QMimeData, QUrl
from PySide6.QtWidgets import QApplication

from AssetsManager.application.bootstrap import ApplicationBootstrap
from AssetsManager.panels.file_list import QWidgetFileListPanel
from AssetsManager.panels.file_list._base import FileListPanel


class _ScrollTimer:
    def __init__(self):
        self.start_calls = 0
        self.stop_calls = 0

    def start(self):
        self.start_calls += 1

    def stop(self):
        self.stop_calls += 1


def _bare_scroll_panel():
    panel = type("_Panel", (), {})()
    panel._scroll_debounce = _ScrollTimer()
    panel._scroll_animating = False
    panel._scroll_animation_generation = 0
    panel._scroll_animation_setting_value = False
    return panel


def test_manual_scroll_value_change_starts_thumbnail_debounce():
    panel = _bare_scroll_panel()

    FileListPanel._on_scroll_value_changed(panel)

    assert panel._scroll_debounce.start_calls == 1


def test_scroll_value_changes_during_smooth_animation_do_not_start_thumbnail_debounce():
    panel = _bare_scroll_panel()
    panel._scroll_animating = True
    panel._scroll_animation_setting_value = True

    FileListPanel._on_scroll_value_changed(panel)

    assert panel._scroll_debounce.start_calls == 0


def test_only_latest_smooth_scroll_completion_starts_thumbnail_debounce():
    panel = _bare_scroll_panel()

    first = FileListPanel._begin_smooth_scroll(panel)
    second = FileListPanel._begin_smooth_scroll(panel)
    FileListPanel._finish_smooth_scroll(panel, first)

    assert panel._scroll_debounce.start_calls == 0
    FileListPanel._finish_smooth_scroll(panel, second)

    assert panel._scroll_debounce.start_calls == 1


def test_user_scroll_during_smooth_animation_stops_animation_and_starts_debounce():
    panel = _bare_scroll_panel()
    animation = Mock()
    panel._scroll_anim = animation
    FileListPanel._begin_smooth_scroll(panel)

    FileListPanel._on_scroll_value_changed(panel)

    animation.stop.assert_called_once_with()
    assert panel._scroll_animating is False
    assert panel._scroll_debounce.start_calls == 1


def test_animation_scroll_value_change_does_not_cancel_its_own_animation():
    panel = _bare_scroll_panel()
    animation = Mock()
    panel._scroll_anim = animation
    FileListPanel._begin_smooth_scroll(panel)
    panel._scroll_animation_setting_value = True

    FileListPanel._on_scroll_value_changed(panel)

    animation.stop.assert_not_called()
    assert panel._scroll_debounce.start_calls == 0


def test_grid_scrollbar_uses_shared_animation_gate():
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    try:
        timer = _ScrollTimer()
        panel._scroll_debounce = timer
        scrollbar = panel._grid_widget._scrollbar
        scrollbar.setRange(0, 100)

        scrollbar.setValue(10)
        assert timer.start_calls == 1

        panel._scroll_animating = True
        panel._scroll_animation_setting_value = True
        scrollbar.setValue(20)
        assert timer.start_calls == 1
    finally:
        panel.shutdown()
        app.processEvents()


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


def test_root_refresh_retains_injected_session_and_closed_worker_rejects_write(tmp_path, monkeypatch):
    """Root refreshes retain the leased session, including its close rejection."""
    class CapturingPool:
        def __init__(self):
            self.tasks = []

        def setMaxThreadCount(self, _count):
            pass

        def start(self, task):
            self.tasks.append(task)

        def waitForDone(self):
            pass

    library = tmp_path / "library"
    folder = library / "folder"
    folder.mkdir(parents=True)
    (folder / "asset.bin").write_bytes(b"abc")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    pool = CapturingPool()
    panel = QWidgetFileListPanel()
    try:
        session = bootstrap.library_service.open_session(library)
        scoped = bootstrap.for_library(session)
        get_dir_size = Mock(wraps=scoped.metadata_service.get_dir_size)
        monkeypatch.setattr(scoped.metadata_service, "get_dir_size", get_dir_size)
        panel.set_scoped_services(scoped)
        panel._model._size_pool = pool

        panel.navigate_to(str(library), set_root=True)
        panel.navigate_to(str(folder))
        panel.navigate_to(str(library), set_root=True)

        assert panel._model._session is session
        panel._model._start_async_dir_size(str(folder))
        bootstrap.library_service.close_session(session)
        with pytest.raises(RuntimeError, match="closed LibrarySession"):
            pool.tasks.pop().run()
        get_dir_size.assert_not_called()
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


def test_duplicate_captures_originating_service_and_closed_session_refuses(tmp_path, monkeypatch):
    """Queued duplicates stay bound to the service injected when requested."""
    from unittest.mock import Mock

    import pytest

    library_a = tmp_path / "library-a"
    library_b = tmp_path / "library-b"
    source = library_a / "asset.txt"
    library_a.mkdir()
    library_b.mkdir()
    source.write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    queued = []
    try:
        scoped_a = bootstrap.for_library(bootstrap.library_service.open_session(library_a))
        scoped_b = bootstrap.for_library(bootstrap.library_service.open_session(library_b))
        duplicate_a = Mock(wraps=scoped_a.file_operation_service.duplicate)
        duplicate_b = Mock(wraps=scoped_b.file_operation_service.duplicate)
        monkeypatch.setattr(scoped_a.file_operation_service, "duplicate", duplicate_a)
        monkeypatch.setattr(scoped_b.file_operation_service, "duplicate", duplicate_b)
        panel.set_scoped_services(scoped_a)
        monkeypatch.setattr(panel, "_selected_paths", lambda: [str(source)])
        monkeypatch.setattr(
            panel, "_run_in_background", lambda operation, *args, on_done=None: queued.append(operation),
        )
        panel._post_refresh = Mock()

        panel._duplicate_selected()
        panel.set_scoped_services(scoped_b)

        queued.pop()()
        assert (library_a / "asset - Copy.txt").read_text() == "asset"
        assert not (library_b / "asset - Copy.txt").exists()
        duplicate_a.assert_called_once_with(str(source), copy_label=" - Copy")
        duplicate_b.assert_not_called()

        panel.set_scoped_services(scoped_a)
        panel._duplicate_selected()
        panel.set_scoped_services(scoped_b)
        bootstrap.library_service.close_session(scoped_a.session)

        with pytest.raises(RuntimeError, match="closed LibrarySession"):
            queued.pop()()
        assert duplicate_a.call_count == 1
        duplicate_b.assert_not_called()
        assert not (library_a / "asset - Copy_1.txt").exists()
        assert not (library_b / "asset - Copy.txt").exists()
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()


def test_queued_mutations_capture_originating_scoped_dependencies(tmp_path, monkeypatch):
    """Switching panels cannot redirect queued mutations to another library."""
    from types import SimpleNamespace
    from unittest.mock import Mock

    import pytest
    from PySide6.QtWidgets import QMessageBox

    library_a = tmp_path / "library-a"
    library_b = tmp_path / "library-b"
    library_a.mkdir()
    library_b.mkdir()
    source = library_a / "asset.txt"
    source.write_text("asset")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    queued = []
    try:
        scoped_a = bootstrap.for_library(bootstrap.library_service.open_session(library_a))
        scoped_b = bootstrap.for_library(bootstrap.library_service.open_session(library_b))
        for scoped in (scoped_a, scoped_b):
            scoped.file_operation_service.copy_to_directory = Mock(
                return_value=SimpleNamespace(ok=True, changed_paths=(), errors=()),
            )
            scoped.file_operation_service.move_to_directory = Mock(
                return_value=SimpleNamespace(ok=True, changed_paths=(), errors=()),
            )
            scoped.file_operation_service.delete_to_trash = Mock(
                return_value=SimpleNamespace(errors=()),
            )
            scoped.file_operation_service.delete_permanent = Mock(
                return_value=SimpleNamespace(changed_paths=(), errors=()),
            )
            scoped.undo_service.prepare_delete = Mock(return_value=None)
            scoped.undo_service.commit_delete = Mock()
            scoped.undo_service.discard_delete = Mock()
            scoped.undo_service.perform_undo = Mock()
            scoped.undo_service.perform_redo = Mock()
            scoped.undo_service.can_undo = Mock(return_value=True)
            scoped.undo_service.can_redo = Mock(return_value=True)
        panel._run_in_background = lambda operation, *args, on_done=None: queued.append(operation)
        monkeypatch.setattr(
            "AssetsManager.panels.file_list._actions.QMessageBox.question",
            Mock(return_value=QMessageBox.StandardButton.Yes),
        )
        monkeypatch.setattr(
            "AssetsManager.panels.file_list._actions.QMessageBox.warning",
            Mock(return_value=QMessageBox.StandardButton.Yes),
        )

        actions = [
            lambda: (setattr(panel, "_clipboard_source", [str(source)]), setattr(panel, "_clipboard_cut", False), panel._paste()),
            lambda: panel._delete([str(source)]),
            lambda: panel._delete_permanent([str(source)]),
            panel._undo,
            panel._redo,
        ]
        for action in actions:
            panel.set_scoped_services(scoped_a)
            action()
            panel.set_scoped_services(scoped_b)
            queued.pop()()

        assert scoped_a.file_operation_service.copy_to_directory.called
        assert scoped_a.file_operation_service.delete_to_trash.called
        assert scoped_a.file_operation_service.delete_permanent.called
        scoped_a.undo_service.perform_undo.assert_called_once_with(
            scoped_a.file_operation_service, str(library_a.resolve()),
        )
        scoped_a.undo_service.perform_redo.assert_called_once_with(
            scoped_a.file_operation_service, str(library_a.resolve()),
        )
        assert not scoped_b.file_operation_service.copy_to_directory.called
        assert not scoped_b.file_operation_service.delete_to_trash.called
        assert not scoped_b.file_operation_service.delete_permanent.called
        assert not scoped_b.undo_service.perform_undo.called
        assert not scoped_b.undo_service.perform_redo.called

        for action in actions:
            session_a = bootstrap.library_service.open_session(library_a)
            scoped_a = bootstrap.for_library(session_a)
            scoped_a.undo_service.can_undo = Mock(return_value=True)
            scoped_a.undo_service.can_redo = Mock(return_value=True)
            panel.set_scoped_services(scoped_a)
            panel._clipboard_source = [str(source)]
            panel._clipboard_cut = False
            panel._run_in_background = lambda operation, *args, on_done=None: queued.append(operation)
            action()
            panel.set_scoped_services(scoped_b)
            bootstrap.library_service.close_session(session_a)
            with pytest.raises(RuntimeError, match="closed LibrarySession"):
                queued.pop()()
        assert not scoped_b.file_operation_service.move_to_directory.called
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
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
