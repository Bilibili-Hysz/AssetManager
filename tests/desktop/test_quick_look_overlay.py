"""Automated unit tests for QuickLookOverlay desktop preview system."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent
from PySide6.QtWidgets import QApplication

from AssetsManager.panels.file_list._shortcuts import handle_key
from AssetsManager.widgets.quick_look_overlay import QuickLookOverlay


@pytest.fixture
def qapp():
    """Ensure QApplication is available for desktop UI tests."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _create_sample_image(path, width: int = 100, height: int = 80, color: str = "#336699") -> str:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    image.save(str(path))
    return str(path)


def test_quick_look_overlay_construction(tmp_path, qapp):
    img_path = _create_sample_image(tmp_path / "photo_01.png", 200, 150)
    txt_path = tmp_path / "notes.txt"
    txt_path.write_text("hello world", encoding="utf-8")

    paths = [img_path, str(txt_path)]
    overlay = QuickLookOverlay(paths, current_index=0)

    try:
        assert overlay.current_index == 0
        assert overlay.total_count == 2
        assert overlay.current_path == img_path

        # Window flags and attributes
        flags = overlay.windowFlags()
        assert bool(flags & Qt.WindowType.FramelessWindowHint)
        assert bool(flags & Qt.WindowType.Dialog)
        assert overlay.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Header title and index
        assert overlay._title_label.text() == "photo_01.png"
        assert overlay._index_label.text() == "1 / 2"
        assert "200×150" in overlay._spec_pill.text()
        assert "PNG" in overlay._spec_pill.text()

        # Close button ghost variant
        assert overlay._close_btn.property("buttonVariant") == "ghost"

        overlay.show()
        qapp.processEvents()

        # Both nav buttons visible for multiple files
        assert overlay._prev_btn.isVisible()
        assert overlay._next_btn.isVisible()
    finally:
        overlay.close()
        overlay.deleteLater()
        qapp.processEvents()


def test_quick_look_overlay_navigation(tmp_path, qapp):
    p1 = _create_sample_image(tmp_path / "img1.png", 120, 90)
    p2 = _create_sample_image(tmp_path / "img2.jpg", 160, 120)
    p3 = tmp_path / "archive.zip"
    p3.write_bytes(b"PK\x03\x04" + b"\x00" * 20)

    paths = [p1, p2, str(p3)]
    overlay = QuickLookOverlay(paths, current_index=0)

    try:
        # Initial state
        assert overlay.current_index == 0
        assert overlay._title_label.text() == "img1.png"

        # Next
        overlay.next_item()
        assert overlay.current_index == 1
        assert overlay._title_label.text() == "img2.jpg"
        assert overlay._index_label.text() == "2 / 3"

        # Next -> generic file
        overlay.next_item()
        assert overlay.current_index == 2
        assert overlay._title_label.text() == "archive.zip"
        assert overlay._index_label.text() == "3 / 3"
        assert overlay._stack.currentWidget() == overlay._generic_canvas

        # Next -> wrap-around to 0
        overlay.next_item()
        assert overlay.current_index == 0
        assert overlay._title_label.text() == "img1.png"
        assert overlay._stack.currentWidget() == overlay._image_canvas

        # Prev -> wrap-around to 2
        overlay.prev_item()
        assert overlay.current_index == 2
        assert overlay._title_label.text() == "archive.zip"

        # Prev -> 1
        overlay.prev_item()
        assert overlay.current_index == 1
        assert overlay._title_label.text() == "img2.jpg"
    finally:
        overlay.close()
        overlay.deleteLater()
        qapp.processEvents()


def test_quick_look_overlay_keyboard_shortcuts(tmp_path, qapp):
    p1 = _create_sample_image(tmp_path / "k1.png")
    p2 = _create_sample_image(tmp_path / "k2.png")
    overlay = QuickLookOverlay([p1, p2], current_index=0)
    overlay.show()
    qapp.processEvents()

    try:
        # Arrow Right advances
        event_right = QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier
        )
        overlay.keyPressEvent(event_right)
        assert overlay.current_index == 1

        # Arrow Left returns
        event_left = QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier
        )
        overlay.keyPressEvent(event_left)
        assert overlay.current_index == 0

        # Space dismisses
        event_space = QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier
        )
        overlay.keyPressEvent(event_space)
        qapp.processEvents()
        assert not overlay.isVisible()

        # Re-show and test Escape
        overlay.show()
        qapp.processEvents()
        assert overlay.isVisible()

        event_esc = QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
        )
        overlay.keyPressEvent(event_esc)
        qapp.processEvents()
        assert not overlay.isVisible()
    finally:
        overlay.close()
        overlay.deleteLater()
        qapp.processEvents()


def test_quick_look_overlay_open_default_app(tmp_path, qapp, monkeypatch):
    p1 = _create_sample_image(tmp_path / "open_target.png")
    overlay = QuickLookOverlay([p1], current_index=0)

    opened_urls = []
    monkeypatch.setattr(
        "PySide6.QtGui.QDesktopServices.openUrl",
        lambda url: opened_urls.append(url) or True,
    )

    try:
        event_enter = QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier
        )
        overlay.keyPressEvent(event_enter)
        assert len(opened_urls) == 1
        import os
        assert os.path.normpath(opened_urls[0].toLocalFile()) == os.path.normpath(p1)
    finally:
        overlay.close()
        overlay.deleteLater()
        qapp.processEvents()


def test_quick_look_single_file_hides_nav(tmp_path, qapp):
    p1 = _create_sample_image(tmp_path / "single.png")
    overlay = QuickLookOverlay([p1], current_index=0)

    try:
        assert overlay.total_count == 1
        assert not overlay._prev_btn.isVisible()
        assert not overlay._next_btn.isVisible()
    finally:
        overlay.close()
        overlay.deleteLater()
        qapp.processEvents()


def test_quick_look_click_backdrop_dismisses(tmp_path, qapp):
    p1 = _create_sample_image(tmp_path / "click_test.png")
    overlay = QuickLookOverlay([p1], current_index=0)
    overlay.resize(800, 600)
    overlay.show()
    qapp.processEvents()

    try:
        assert overlay.isVisible()
        # Mock a mouse press outside card bounds (e.g. at (5, 5))
        mock_event = MagicMock()
        mock_event.pos.return_value = QPoint(5, 5)
        overlay.mousePressEvent(mock_event)
        qapp.processEvents()
        assert not overlay.isVisible()
    finally:
        overlay.close()
        overlay.deleteLater()
        qapp.processEvents()


def test_file_list_shortcut_space(qapp):
    class DummySearch:
        def __init__(self, focused: bool):
            self._focused = focused

        def hasFocus(self):
            return self._focused

    class DummyPanel:
        def __init__(self, search_focused: bool, selected: list[str]):
            self._view_mode = "Grid"
            self._search = DummySearch(search_focused)
            self._selected = selected
            self.quick_look_called = False

        def _selected_paths(self):
            return self._selected

        def _open_quick_look(self):
            self.quick_look_called = True

    event_space = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier
    )

    # 1. Search has focus -> space should NOT trigger quick look
    panel_search = DummyPanel(search_focused=True, selected=["/path/to/img.png"])
    assert not handle_key(panel_search, event_space)
    assert not panel_search.quick_look_called

    # 2. Search has no focus, but no selection -> space should NOT trigger
    panel_no_sel = DummyPanel(search_focused=False, selected=[])
    assert not handle_key(panel_no_sel, event_space)
    assert not panel_no_sel.quick_look_called

    # 3. Search has no focus, and has selection -> space TRIGGERS quick look
    panel_sel = DummyPanel(search_focused=False, selected=["/path/to/img.png"])
    assert handle_key(panel_sel, event_space)
    assert panel_sel.quick_look_called


def test_panel_open_quick_look_method(tmp_path, qapp, monkeypatch):
    from AssetsManager.panels.file_list import FileListPanel
    from AssetsManager.widgets.quick_look_overlay import QuickLookOverlay

    img_path = _create_sample_image(tmp_path / "panel_img.png")

    panel = FileListPanel()
    monkeypatch.setattr(panel, "_selected_paths", lambda: [img_path])

    executed = []
    monkeypatch.setattr(
        QuickLookOverlay, "exec", lambda self: executed.append(self.current_path) or 0
    )

    try:
        panel._open_quick_look()
        assert len(executed) == 1
        assert executed[0] == img_path
    finally:
        panel.shutdown()
        panel.deleteLater()
        qapp.processEvents()

