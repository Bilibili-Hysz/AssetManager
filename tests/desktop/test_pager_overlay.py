import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from AssetsManager.widgets.pager_overlay import PagerOverlay


@pytest.fixture
def pager():
    QApplication.instance() or QApplication([])
    widget = PagerOverlay()
    yield widget
    widget.close()


def test_creation_configures_modal_frameless_overlay(pager):
    assert pager.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert pager.windowModality() == Qt.WindowModality.ApplicationModal
    assert pager._text_edit.isReadOnly()
    assert pager._search_input.isHidden()
    assert "QWidget#pagerOverlay" in pager.styleSheet()


def test_show_text_sets_title_content_and_status(pager):
    pager.show_text("Build log", "first\nsecond\nthird")

    assert pager.isVisible()
    assert pager._title_label.text() == "Build log"
    assert pager._text_edit.toPlainText() == "first\nsecond\nthird"
    assert "3 lines" in pager._status_label.text()


def test_show_file_reads_utf8_content(pager, tmp_path):
    path = tmp_path / "output.log"
    path.write_text("alpha\nbeta", encoding="utf-8")

    pager.show_file(str(path))

    assert pager._title_label.text() == "output.log"
    assert pager._text_edit.toPlainText() == "alpha\nbeta"


def test_vim_keyboard_navigation_moves_scrollbar(pager):
    pager.show_text("Long", "\n".join(f"line {index}" for index in range(300)))
    scrollbar = pager._text_edit.verticalScrollBar()
    QApplication.processEvents()

    QTest.keyClick(pager._text_edit, Qt.Key.Key_J)
    assert scrollbar.value() > scrollbar.minimum()

    QTest.keyClick(pager._text_edit, Qt.Key.Key_G, Qt.KeyboardModifier.ShiftModifier)
    assert scrollbar.value() == scrollbar.maximum()

    QTest.keyClick(pager._text_edit, Qt.Key.Key_G)
    QTest.keyClick(pager._text_edit, Qt.Key.Key_G)
    assert scrollbar.value() == scrollbar.minimum()

    QTest.keyClick(pager._text_edit, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    assert scrollbar.value() > scrollbar.minimum()
    QTest.keyClick(pager._text_edit, Qt.Key.Key_U, Qt.KeyboardModifier.ControlModifier)
    assert scrollbar.value() == scrollbar.minimum()


def test_slash_search_highlights_matches_and_escape_hides_bar(pager):
    pager.show_text("Search", "Error one\nok\nerror two")

    QTest.keyClick(pager._text_edit, Qt.Key.Key_Slash)
    assert pager._search_input.isVisible()
    QTest.keyClicks(pager._search_input, "error")

    assert len(pager._search_matches) == 2
    assert "1/2 matches" in pager._status_label.text()
    assert len(pager._text_edit.extraSelections()) == 2

    QTest.keyClick(pager._search_input, Qt.Key.Key_Return)
    assert "2/2 matches" in pager._status_label.text()
    QTest.keyClick(pager._search_input, Qt.Key.Key_Escape)
    assert pager._search_input.isHidden()
    assert pager.isVisible()


def test_refresh_theme_rebuilds_style_and_preserves_text(pager):
    pager.show_text("Details", "unchanged")
    previous = pager._sk

    pager.refresh_theme()

    assert pager._sk is not previous
    assert "QPlainTextEdit#pagerText" in pager.styleSheet()
    assert pager._text_edit.toPlainText() == "unchanged"
