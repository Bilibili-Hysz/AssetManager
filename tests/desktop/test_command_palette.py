import os
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from AssetsManager.widgets.command_palette import CommandPalette, _ROLE_RESULT


@pytest.fixture
def palette():
    QApplication.instance() or QApplication([])
    widget = CommandPalette()
    yield widget
    widget.close()


def _result_items(palette):
    return [
        palette._results_list.item(index)
        for index in range(palette._results_list.count())
        if palette._results_list.item(index).data(_ROLE_RESULT) is not None
    ]


def test_creation_configures_frameless_scaled_dialog(palette):
    assert palette.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert palette.isModal()
    assert palette._search_input.placeholderText() == "Type a command or search\u2026"
    assert palette.size().width() > 0
    assert palette.size().height() > 0


def test_register_command_adds_grouped_result(palette):
    callback = Mock()
    palette.register_command("View", "Show details", callback, "Ctrl+D", "eye")

    items = _result_items(palette)
    assert len(items) == 1
    assert items[0].text() == "Show details"
    assert items[0].data(_ROLE_RESULT)["callback"] is callback
    assert palette._results_list.itemWidget(palette._results_list.item(0)).text() == "Commands"


def test_register_file_and_tag_creates_separate_groups(palette):
    palette.register_file("C:/assets/logo.svg", "logo.svg")
    palette.register_tag("Brand")

    assert [item.text() for item in _result_items(palette)] == ["logo.svg", "Brand"]
    headings = [
        palette._results_list.itemWidget(palette._results_list.item(index)).text()
        for index in range(palette._results_list.count())
        if palette._results_list.item(index).data(_ROLE_RESULT) is None
    ]
    assert headings == ["Files", "Tags"]


def test_filter_results_matches_name_category_and_path(palette):
    palette.register_command("Edit", "Rename asset", Mock())
    palette.register_command("View", "Toggle grid", Mock())
    palette.register_file("C:/photos/sunset.jpg", "sunset.jpg")

    palette._filter_results("edit")
    assert [item.text() for item in _result_items(palette)] == ["Rename asset"]

    palette._filter_results("photos")
    assert [item.text() for item in _result_items(palette)] == ["sunset.jpg"]


def test_down_up_and_enter_navigate_and_execute(palette):
    first = Mock()
    second = Mock()
    selected = Mock()
    palette.command_selected.connect(selected)
    palette.register_command("Edit", "First", first)
    palette.register_command("Edit", "Second", second)
    palette.show()
    palette._search_input.setFocus()

    assert palette._results_list.currentItem().text() == "First"
    QTest.keyClick(palette._search_input, Qt.Key.Key_Down)
    assert palette._results_list.currentItem().text() == "Second"
    QTest.keyClick(palette._search_input, Qt.Key.Key_Up)
    assert palette._results_list.currentItem().text() == "First"
    QTest.keyClick(palette._search_input, Qt.Key.Key_Return)

    first.assert_called_once_with()
    second.assert_not_called()
    selected.assert_called_once_with("First")


def test_escape_closes_palette(palette):
    palette.show()
    palette._search_input.setFocus()
    QTest.keyClick(palette._search_input, Qt.Key.Key_Escape)
    assert not palette.isVisible()


def test_ctrl_k_shortcut_opens_palette():
    QApplication.instance() or QApplication([])
    parent = QWidget()
    palette = CommandPalette(parent)
    try:
        parent.show()
        assert palette._open_shortcut.key().toString() == "Ctrl+K"
        palette._open_shortcut.activated.emit()
        assert palette.isVisible()
    finally:
        palette.close()
        parent.close()


def test_refresh_theme_rebuilds_style_and_preserves_results(palette):
    palette.register_tag("Important")
    previous = palette._sk

    palette.refresh_theme()

    assert palette._sk is not previous
    assert "QDialog" in palette.styleSheet()
    assert [item.text() for item in _result_items(palette)] == ["Important"]
