import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from AssetsManager.widgets.tab_container import TabContainer


def test_tab_title_updates_current_index_after_close(tmp_path):
    app = QApplication.instance() or QApplication([])
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    container = TabContainer()
    try:
        first_panel = container.current_file_list()
        assert first_panel is not None
        first_panel.navigate_to(str(first), set_root=True)

        container._add_tab(str(second))
        second_panel = container.current_file_list()
        assert second_panel is not None

        container._close_tab(0)
        second_panel.folder_entered.emit(str(second))

        assert container._tabs.tabText(0) == "second"
    finally:
        container.close()
        app.processEvents()
