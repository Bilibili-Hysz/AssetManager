import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget

from AssetsManager.dialogs.tag_editor_dialog import TagEditorDialog


def test_clear_current_chips_ignores_layout_item_without_widget():
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    panel = type("_Panel", (), {})()
    panel._current_chips = []
    panel._current_flow_layout = QHBoxLayout(host)
    panel._current_flow_layout.addStretch()

    TagEditorDialog._clear_current_chips(panel)

    assert panel._current_flow_layout.count() == 0
    host.deleteLater()
    app.processEvents()
