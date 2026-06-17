import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelectionModel
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


def test_set_root_prefers_scoped_library_runtime_when_bootstrap_present(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    app = QApplication.instance() or QApplication([])
    bootstrap = ApplicationBootstrap()
    app.setProperty("bootstrap", bootstrap)
    panel = QWidgetFileListPanel()
    try:
        session = bootstrap.library_service.open_session(tmp_path)

        panel.navigate_to(str(tmp_path), set_root=True)

        assert panel._model._metadata_service is not None
        assert panel._model._metadata_service._connection(tmp_path) is session.db_conn
        assert panel._loader._db_conn is session.db_conn
        assert panel._loader._cache_dir == session.thumb_dir_str
    finally:
        panel.shutdown()
        app.setProperty("bootstrap", None)
        app.processEvents()
