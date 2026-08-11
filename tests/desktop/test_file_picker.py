import os
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from AssetsManager.widgets.file_picker import FilePickerDialog, _ROLE_FILE


FILES = [
    {"path": "C:/assets/brand/logo.svg", "name": "logo.svg", "tag": "Brand"},
    {"path": "C:/photos/sunset.jpg", "name": "sunset.jpg", "tag": "Photo"},
    {"path": "C:/docs/notes.txt", "name": "notes.txt", "tag": "Reference"},
]


@pytest.fixture
def picker():
    QApplication.instance() or QApplication([])
    widget = FilePickerDialog()
    yield widget
    widget.close()


def test_creation_configures_dialog_and_ctrl_p(picker):
    assert picker.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert picker.isModal()
    assert picker._search_input.placeholderText() == "Search files\u2026"
    assert picker._open_shortcut.key().toString() == "Ctrl+P"
    assert picker.size().width() > picker.size().height()


def test_set_file_list_populates_rows_and_data(picker):
    picker.set_file_list(FILES)

    assert picker._file_list.count() == 3
    assert picker._file_list.item(0).text() == "logo.svg"
    assert picker._file_list.item(0).data(_ROLE_FILE) == FILES[0]
    assert picker._file_list.itemWidget(picker._file_list.item(0)) is not None


def test_filter_matches_name_path_and_tag(picker):
    picker.set_file_list(FILES)

    picker._filter_files("sunset")
    assert [picker._file_list.item(i).text() for i in range(picker._file_list.count())] == [
        "sunset.jpg"
    ]

    picker._filter_files("docs")
    assert picker._file_list.item(0).text() == "notes.txt"

    picker._filter_files("brand")
    assert picker._file_list.item(0).text() == "logo.svg"


def test_keyboard_navigation_wraps_between_files(picker):
    picker.set_file_list(FILES)
    picker.show()
    picker._search_input.setFocus()

    assert picker._file_list.currentRow() == 0
    QTest.keyClick(picker._search_input, Qt.Key.Key_Down)
    assert picker._file_list.currentRow() == 1
    QTest.keyClick(picker._search_input, Qt.Key.Key_Up)
    assert picker._file_list.currentRow() == 0
    QTest.keyClick(picker._search_input, Qt.Key.Key_Up)
    assert picker._file_list.currentRow() == 2


def test_enter_emits_selected_file_path(picker):
    selected = Mock()
    picker.file_selected.connect(selected)
    picker.set_file_list(FILES)
    picker.show()
    picker._search_input.setFocus()

    QTest.keyClick(picker._search_input, Qt.Key.Key_Down)
    QTest.keyClick(picker._search_input, Qt.Key.Key_Return)

    selected.assert_called_once_with("C:/photos/sunset.jpg")
    assert not picker.isVisible()


def test_escape_closes_picker(picker):
    picker.show()
    picker._search_input.setFocus()

    QTest.keyClick(picker._search_input, Qt.Key.Key_Escape)

    assert not picker.isVisible()


def test_theme_refresh_rebuilds_style_and_preserves_filter(picker):
    picker.set_file_list(FILES)
    picker._search_input.setText("photo")
    previous = picker._sk

    picker.refresh_theme()

    assert picker._sk is not previous
    assert "QDialog" in picker.styleSheet()
    assert picker._file_list.count() == 1
    assert picker._file_list.item(0).text() == "sunset.jpg"
