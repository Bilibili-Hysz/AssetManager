"""Tests for Details view: selection, keyboard, status, and path-based restore."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QItemSelectionModel
from PySide6.QtWidgets import QApplication

from AssetsManager.i18n import tr
from AssetsManager.panels.file_list import QWidgetFileListPanel


def _make_panel(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.png").write_bytes(b"\x89PNG")
    (tmp_path / "sub").mkdir()
    app = QApplication.instance() or QApplication([])
    bootstrap = app.property("bootstrap")
    panel = QWidgetFileListPanel()
    session = bootstrap.library_service.open_session(tmp_path)
    panel.set_scoped_services(bootstrap.runtime_for(session).services)
    panel.navigate_to(str(tmp_path), set_root=True)
    panel._model._wait_for_scan()
    return app, panel


def _switch_to_details(panel):
    panel._view_combo.setCurrentIndex(1)
    panel._populate_details()


def test_file_list_language_refresh_preserves_control_values(tmp_path):
    app, panel = _make_panel(tmp_path)
    try:
        panel._sort_combo.setCurrentIndex(2)
        panel._filter_combo.setCurrentIndex(3)
        panel._view_combo.setCurrentIndex(1)

        panel._refresh_language("zh")

        assert panel._sort_combo.currentData() == "size"
        assert panel._filter_combo.currentData() == "videos"
        assert panel._view_combo.currentData() == "Details"
        assert panel._search.placeholderText()
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_selected_paths_returns_detail_view_selection(tmp_path):
    app, panel = _make_panel(tmp_path)
    try:
        _switch_to_details(panel)
        panel._populate_details()
        sm = panel._detail_view.selectionModel()
        first = panel._detail_model.index(0, 0)
        sm.select(first, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)

        paths = panel._selected_detail_paths()
        assert len(paths) == 1
        assert paths[0] == panel._detail_model._entries[0].path
    finally:
        panel.shutdown()
        app.processEvents()


def test_selected_detail_paths_ignores_non_path_user_role(tmp_path, monkeypatch):
    app, panel = _make_panel(tmp_path)
    try:
        _switch_to_details(panel)
        panel._populate_details()
        first = panel._detail_model.index(0, 0)
        panel._detail_view.selectionModel().select(
            first,
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
        )
        original_data = panel._detail_model.data
        monkeypatch.setattr(
            panel._detail_model,
            "data",
            lambda index, role: object()
            if role == Qt.ItemDataRole.UserRole
            else original_data(index, role),
        )

        assert panel._selected_detail_paths() == []
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_model_returns_empty_display_after_source_shutdown(tmp_path):
    app, panel = _make_panel(tmp_path)
    try:
        _switch_to_details(panel)
        index = panel._detail_model.index(0, 0)
        panel._model.shutdown()

        assert panel._detail_model.data(index, Qt.ItemDataRole.DisplayRole) == ""
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_status_shows_selected_count(tmp_path):
    app, panel = _make_panel(tmp_path)
    try:
        _switch_to_details(panel)
        panel._populate_details()
        sm = panel._detail_view.selectionModel()
        first = panel._detail_model.index(0, 0)
        sm.select(first, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)

        panel._update_status()
        status = panel._status.text()
        assert "1" in status
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_select_all_selects_detail_rows(tmp_path):
    app, panel = _make_panel(tmp_path)
    try:
        _switch_to_details(panel)
        panel._populate_details()
        panel._detail_view.selectAll()

        sel = panel._detail_view.selectionModel().selectedRows()
        assert len(sel) == panel._detail_model.rowCount()
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_escape_clears_detail_selection(tmp_path):
    app, panel = _make_panel(tmp_path)
    try:
        _switch_to_details(panel)
        panel._populate_details()
        panel._detail_view.selectAll()
        assert len(panel._detail_view.selectionModel().selectedRows()) > 0

        panel._detail_view.clearSelection()
        assert len(panel._detail_view.selectionModel().selectedRows()) == 0
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_selection_survives_refresh_by_path(tmp_path):
    app, panel = _make_panel(tmp_path)
    try:
        _switch_to_details(panel)
        panel._populate_details()
        target = str(tmp_path / "b.png")
        row = next(i for i, e in enumerate(panel._detail_model._entries) if e.path == target)
        sm = panel._detail_view.selectionModel()
        idx = panel._detail_model.index(row, 0)
        sm.select(idx, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)

        panel._model.refresh()
        panel._model._wait_for_scan()
        panel._populate_details()

        sel_paths = [panel._detail_model.data(i, Qt.ItemDataRole.UserRole)
                     for i in panel._detail_view.selectionModel().selectedRows()]
        assert target in sel_paths
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_selection_survives_post_refresh(tmp_path):
    app, panel = _make_panel(tmp_path)
    try:
        _switch_to_details(panel)
        target = str(tmp_path / "b.png")
        row = next(i for i, e in enumerate(panel._detail_model._entries) if e.path == target)
        idx = panel._detail_model.index(row, 0)
        panel._detail_view.selectionModel().select(
            idx, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        )

        panel._post_refresh()
        panel._model._wait_for_scan()

        sel_paths = [panel._detail_model.data(i, Qt.ItemDataRole.UserRole)
                     for i in panel._detail_view.selectionModel().selectedRows()]
        assert target in sel_paths
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_selects_requested_operation_result_after_refresh(tmp_path):
    app, panel = _make_panel(tmp_path)
    try:
        _switch_to_details(panel)
        target = tmp_path / "created.txt"
        target.write_text("created")

        panel._request_operation_selection(panel._scoped_services.session, [target])
        panel._post_refresh()
        panel._model._wait_for_scan()
        app.processEvents()
        panel._model._wait_for_scan()
        panel._model._wait_for_scan()

        selected = [
            panel._detail_model.data(index, Qt.ItemDataRole.UserRole)
            for index in panel._detail_view.selectionModel().selectedRows()
        ]
        assert selected == [str(target)]

    finally:
        panel.shutdown()
        app.processEvents()


def test_details_projects_shared_empty_and_filtered_states(tmp_path):
    app, panel = _make_panel(tmp_path)
    try:
        _switch_to_details(panel)
        panel._model.set_filter(text="missing")
        panel._populate_details()

        assert panel._detail_model.rowCount() == 0
        assert panel._status.text() == tr("filelist.state.empty_filtered")
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_clear_selection_during_refresh_overrides_path_restore(tmp_path):
    app, panel = _make_panel(tmp_path)
    try:
        _switch_to_details(panel)
        target = str(tmp_path / "b.png")
        row = next(index for index, entry in enumerate(panel._detail_model._entries) if entry.path == target)
        panel._detail_view.selectionModel().select(
            panel._detail_model.index(row, 0),
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
        )

        panel._post_refresh()
        panel._detail_view.clearSelection()
        panel._model._wait_for_scan()
        app.processEvents()

        assert panel._detail_view.selectionModel().selectedRows() == []
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_deletion_candidates_follow_details_sort_order(tmp_path):
    app, panel = _make_panel(tmp_path)
    try:
        _switch_to_details(panel)
        panel._detail_view.sortByColumn(0, Qt.SortOrder.DescendingOrder)
        deleted = tmp_path / "b.png"
        candidates = panel._deletion_selection_candidates([deleted])
        deleted.unlink()
        panel._request_operation_selection(panel._scoped_services.session, candidates)
        panel._post_refresh()
        panel._model._wait_for_scan()
        app.processEvents()
        panel._model._wait_for_scan()

        selected = [
            panel._detail_model.data(index, Qt.ItemDataRole.UserRole)
            for index in panel._detail_view.selectionModel().selectedRows()
        ]
        assert selected == [str(tmp_path / "a.txt")]
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_undo_delete_selects_restored_path_after_refresh(tmp_path):
    app, panel = _make_panel(tmp_path)
    try:
        _switch_to_details(panel)
        target = tmp_path / "a.txt"
        panel._undo_svc.record_delete(str(target))
        panel._get_file_operation_service().delete_permanent([target], library_root=panel._lib_root)
        panel._run_in_background = lambda func, *args, on_done=None: (func(), on_done and on_done())

        panel._undo()
        panel._model._wait_for_scan()
        app.processEvents()
        panel._model._wait_for_scan()

        selected = [
            panel._detail_model.data(index, Qt.ItemDataRole.UserRole)
            for index in panel._detail_view.selectionModel().selectedRows()
        ]
        assert selected == [str(target)]

        panel._redo()
        panel._model._wait_for_scan()
        app.processEvents()
        panel._model._wait_for_scan()

        selected = [
            panel._detail_model.data(index, Qt.ItemDataRole.UserRole)
            for index in panel._detail_view.selectionModel().selectedRows()
        ]
        assert selected == [str(tmp_path / "b.png")]
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_selection_drops_filtered_paths(tmp_path):
    app, panel = _make_panel(tmp_path)
    try:
        _switch_to_details(panel)
        panel._populate_details()
        target = str(tmp_path / "a.txt")
        row = next(i for i, e in enumerate(panel._detail_model._entries) if e.path == target)
        sm = panel._detail_view.selectionModel()
        idx = panel._detail_model.index(row, 0)
        sm.select(idx, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)

        panel._model.set_filter(category="images")
        panel._populate_details()

        sel_paths = [panel._detail_model.data(i, Qt.ItemDataRole.UserRole)
                     for i in panel._detail_view.selectionModel().selectedRows()]
        assert target not in sel_paths
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_selection_survives_sort_by_path(tmp_path):
    app, panel = _make_panel(tmp_path)
    try:
        _switch_to_details(panel)
        target = str(tmp_path / "b.png")
        row = next(index for index, entry in enumerate(panel._detail_model._entries) if entry.path == target)
        panel._detail_view.selectionModel().select(
            panel._detail_model.index(row, 0),
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
        )

        panel._model.set_sort("name", asc=False)
        panel._model._wait_for_scan()

        selected = [
            panel._detail_model.data(index, Qt.ItemDataRole.UserRole)
            for index in panel._detail_view.selectionModel().selectedRows()
        ]
        assert selected == [target]
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_batch_rename_selects_first_renamed_result(tmp_path, monkeypatch):
    app, panel = _make_panel(tmp_path)
    from AssetsManager.panels.file_list._batch_rename import plan_batch_rename

    class AcceptedDialog:
        DialogCode = type("DialogCode", (), {"Accepted": 1})

        def __init__(self, paths, _parent):
            self.plan = plan_batch_rename(
                paths, "{name}_renamed", occupied_paths=paths, windows_rules=True,
            )

        def exec(self):
            return self.DialogCode.Accepted

    monkeypatch.setattr("AssetsManager.panels.file_list._batch_rename_dialog.BatchRenameDialog", AcceptedDialog)
    try:
        _switch_to_details(panel)
        paths = [str(tmp_path / "a.txt"), str(tmp_path / "b.png")]
        for path in paths:
            row = next(index for index, entry in enumerate(panel._detail_model._entries) if entry.path == path)
            panel._detail_view.selectionModel().select(
                panel._detail_model.index(row, 0),
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
            )

        panel._batch_rename(paths)
        panel._model._wait_for_scan()
        app.processEvents()
        panel._model._wait_for_scan()
        app.processEvents()

        assert panel._selected_detail_paths() == [str(tmp_path / "a_renamed.txt")]
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_selection_survives_filter_when_path_remains_visible(tmp_path):
    app, panel = _make_panel(tmp_path)
    try:
        _switch_to_details(panel)
        target = str(tmp_path / "b.png")
        row = next(index for index, entry in enumerate(panel._detail_model._entries) if entry.path == target)
        panel._detail_view.selectionModel().select(
            panel._detail_model.index(row, 0),
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
        )

        panel._model.set_filter(text="b")
        panel._populate_details()

        assert panel._selected_detail_paths() == [target]
    finally:
        panel.shutdown()
        app.processEvents()


def test_switching_grid_to_details_transfers_selected_paths(tmp_path):
    app, panel = _make_panel(tmp_path)
    selected = {str(tmp_path / "a.txt"), str(tmp_path / "b.png")}
    try:
        panel._grid_widget._selection = {
            panel._model._path_index[path] for path in selected
        }

        _switch_to_details(panel)

        assert set(panel._selected_detail_paths()) == selected
        assert panel._grid_widget.selection_model_rows() == set()
    finally:
        panel.shutdown()
        app.processEvents()


def test_switching_details_to_grid_replaces_stale_grid_selection(tmp_path):
    app, panel = _make_panel(tmp_path)
    first = str(tmp_path / "a.txt")
    selected = str(tmp_path / "b.png")
    try:
        panel._grid_widget._selection = {panel._model._path_index[first]}
        _switch_to_details(panel)
        panel._detail_view.clearSelection()
        row = next(index for index, entry in enumerate(panel._detail_model._entries) if entry.path == selected)
        panel._detail_view.selectionModel().select(
            panel._detail_model.index(row, 0),
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
        )

        panel._view_combo.setCurrentIndex(panel._view_combo.findData("Grid"))

        paths = {panel._model.path_at(row) for row in panel._grid_widget.selection_model_rows()}
        assert paths == {selected}
        assert panel._detail_view.selectionModel().selectedRows() == []
    finally:
        panel.shutdown()
        app.processEvents()


def test_switching_views_with_empty_selection_clears_hidden_selection(tmp_path):
    app, panel = _make_panel(tmp_path)
    try:
        target = str(tmp_path / "b.png")
        panel._grid_widget._selection = {panel._model._path_index[target]}
        _switch_to_details(panel)
        panel._detail_view.clearSelection()

        panel._view_combo.setCurrentIndex(panel._view_combo.findData("Grid"))

        assert panel._grid_widget.selection_model_rows() == set()
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_selection_drops_when_navigating_to_another_directory(tmp_path):
    app, panel = _make_panel(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    (other / "asset.png").write_bytes(b"\x89PNG")
    try:
        _switch_to_details(panel)
        target = str(tmp_path / "b.png")
        row = next(index for index, entry in enumerate(panel._detail_model._entries) if entry.path == target)
        panel._detail_view.selectionModel().select(
            panel._detail_model.index(row, 0),
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
        )

        panel.navigate_to(str(other))
        panel._model._wait_for_scan()
        app.processEvents()

        assert panel.current_path == str(other.resolve())
        assert panel._detail_view.selectionModel().selectedRows() == []
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_rename_uses_unified_helper(tmp_path):
    app, panel = _make_panel(tmp_path)
    try:
        _switch_to_details(panel)
        panel._populate_details()
        target = str(tmp_path / "a.txt")
        row = next(i for i, e in enumerate(panel._detail_model._entries) if e.path == target)

        panel._rename_detail_row(row, "renamed.txt")

        assert os.path.exists(str(tmp_path / "renamed.txt"))
        assert not os.path.exists(target)
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_display_returns_clean_name(tmp_path):
    app, panel = _make_panel(tmp_path)
    try:
        _switch_to_details(panel)
        panel._populate_details()
        first = panel._detail_model.index(0, 0)
        display = panel._detail_model.data(first, Qt.ItemDataRole.DisplayRole)
        name = panel._detail_model._entries[0].name
        assert display == name
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_decoration_returns_icon_for_files(tmp_path):
    app, panel = _make_panel(tmp_path)
    try:
        _switch_to_details(panel)
        panel._populate_details()
        for row, entry in enumerate(panel._detail_model._entries):
            idx = panel._detail_model.index(row, 0)
            icon = panel._detail_model.data(idx, Qt.ItemDataRole.DecorationRole)
            if entry.name in ("a.txt", "b.png"):
                assert icon is not None
                assert hasattr(icon, 'isNull')
                assert not icon.isNull()
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_tree_indent_is_disabled(tmp_path):
    app, panel = _make_panel(tmp_path)
    try:
        _switch_to_details(panel)

        assert not panel._detail_view.rootIsDecorated()
        assert not panel._detail_view.itemsExpandable()
        assert panel._detail_view.indentation() == 0
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_header_uses_i18n(tmp_path):
    app, panel = _make_panel(tmp_path)
    try:
        _switch_to_details(panel)
        panel._populate_details()
        header0 = panel._detail_model.headerData(0, Qt.Orientation.Horizontal)
        assert header0 is not None
        assert isinstance(header0, str)
        assert len(header0) > 0
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_sort_by_name(tmp_path):
    app, panel = _make_panel(tmp_path)
    try:
        _switch_to_details(panel)
        panel._populate_details()
        panel._detail_model.sort(0, Qt.SortOrder.AscendingOrder)
        names = [e.name for e in panel._detail_model._entries]
        dirs_first = [n for n in names if (tmp_path / n).is_dir()]
        files_after = [n for n in names if not (tmp_path / n).is_dir()]
        assert dirs_first == sorted(dirs_first)
        assert files_after == sorted(files_after)
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_sort_does_not_change_column_width(tmp_path):
    app, panel = _make_panel(tmp_path)
    try:
        _switch_to_details(panel)
        panel._populate_details()
        panel._detail_view.setColumnWidth(0, 123)

        panel._detail_model.sort(0, Qt.SortOrder.DescendingOrder)

        assert panel._detail_view.columnWidth(0) == 123
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_sort_by_date(tmp_path):
    app, panel = _make_panel(tmp_path)
    try:
        _switch_to_details(panel)
        panel._populate_details()
        panel._detail_model.sort(3, Qt.SortOrder.DescendingOrder)
        mtimes = []
        for entry in panel._detail_model._entries:
            try:
                mtimes.append(os.path.getmtime(entry.path))
            except OSError:
                mtimes.append(0)
            for i in range(len(mtimes) - 1):
                assert mtimes[i] >= mtimes[i + 1] - 0.05
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_tags_cache_populated(tmp_path):
    app, panel = _make_panel(tmp_path)
    try:
        _switch_to_details(panel)
        if panel._lib_root:
            from AssetsManager.core.tag_store import TagStore
            conn = panel._scoped_services.session.connection_for(panel._lib_root)
            store = TagStore(panel._lib_root, db_conn=conn)
            target = str(tmp_path / "a.txt")
            store.add_tag(target, "important")
            panel._populate_details()
            assert target in panel._detail_model._tags_cache
            assert "important" in panel._detail_model._tags_cache[target]
            row = next(i for i, e in enumerate(panel._detail_model._entries) if e.path == target)
            text = panel._detail_model.data(panel._detail_model.index(row, 4), Qt.ItemDataRole.DisplayRole)
            assert text == "important"
        else:
            assert panel._detail_model._tags_cache == {}
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_file_size_is_human_readable(tmp_path):
    (tmp_path / "large.bin").write_bytes(b"x" * 1536)
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    panel.navigate_to(str(tmp_path), set_root=True)
    panel._model._wait_for_scan()
    try:
        _switch_to_details(panel)
        row = next(i for i, e in enumerate(panel._detail_model._entries) if e.name == "large.bin")

        text = panel._detail_model.data(panel._detail_model.index(row, 2), Qt.ItemDataRole.DisplayRole)

        assert text == "1.5 KB"
    finally:
        panel.shutdown()
        app.processEvents()


def test_details_dir_size_ready_updates_size_caches(tmp_path):
    app, panel = _make_panel(tmp_path)
    try:
        _switch_to_details(panel)
        target = str(tmp_path / "sub")

        panel._on_detail_dir_size_ready(target, "1.5 KB", panel._model._dir_size_gen)
        row = next(i for i, e in enumerate(panel._detail_model._entries) if e.path == target)
        text = panel._detail_model.data(panel._detail_model.index(row, 2), Qt.ItemDataRole.DisplayRole)

        assert text == "1.5 KB"
        assert panel._model._subtitle_cache[target] == "1.5 KB"
        assert panel._model._dir_size_cache[target] == "1.5 KB"
    finally:
        panel.shutdown()
        app.processEvents()
