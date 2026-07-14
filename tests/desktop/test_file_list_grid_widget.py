import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from AssetsManager.panels.file_list._base import FileListPanel
from AssetsManager.panels.file_list import QWidgetFileListPanel
from AssetsManager.panels.file_list._grid_widget import FileListGridWidget
from AssetsManager.panels.file_list._model import FileSystemModel


def test_grid_item_texture_uses_widget_device_pixel_ratio(tmp_path):
    (tmp_path / "folder").mkdir()
    app = QApplication.instance() or QApplication([])
    model = FileSystemModel()
    model.set_directory(str(tmp_path))
    model._wait_for_scan()

    widget = FileListGridWidget()
    widget.set_model(model)
    widget.devicePixelRatioF = lambda: 2.0

    texture = widget._render_item(0, QRect(0, 0, widget._item_w, widget._item_h))

    assert texture is not None
    assert texture.devicePixelRatio() == 2.0

    app.processEvents()


def test_grid_thumb_batch_marks_only_loaded_rows_dirty():
    widget = FileListGridWidget()
    widget._dirty.clear()

    widget.on_thumb_batch([1, 9])

    assert widget._dirty == {1, 9}


def test_view_mode_uses_stable_id_when_display_text_is_localized():
    app = QApplication.instance() or QApplication([])
    panel = FileListPanel()
    panel._view_combo.setItemText(0, "网格")
    panel._view_combo.setCurrentIndex(0)

    assert panel._view_combo.itemData(0) == "Grid"
    assert panel._view_mode == "Grid"

    details_index = panel._view_combo.findData("Details")
    panel._view_combo.setCurrentIndex(details_index)
    assert panel._view_mode == "Details"

    panel.deleteLater()
    app.processEvents()


def test_restore_view_mode_uses_saved_stable_id():
    app = QApplication.instance() or QApplication([])
    panel = FileListPanel()
    panel._view_combo.setItemText(1, "详情")
    panel._view_memory["library/subfolder"] = "Details"

    panel._restore_view_mode("library/subfolder")

    assert panel._view_mode == "Details"

    panel.deleteLater()
    app.processEvents()


def test_populated_model_reset_repopulates_details_view(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    panel = QWidgetFileListPanel()
    panel._view_combo.setCurrentIndex(panel._view_combo.findData("Details"))
    (tmp_path / "asset.txt").write_text("asset")
    panel._model._raw_entries = list(__import__("os").scandir(tmp_path))
    panel._model._apply_sort()
    populated = []
    monkeypatch.setattr(panel, "_populate_details", lambda: populated.append(True))

    panel._on_grid_model_reset()

    assert populated == [True]

    panel.deleteLater()
    app.processEvents()
