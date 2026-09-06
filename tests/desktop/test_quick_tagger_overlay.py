"""Tests for QuickTaggerOverlay and T key tagging flow."""
from __future__ import annotations

import warnings
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from AssetsManager.widgets.quick_tagger_overlay import QuickTaggerOverlay
from AssetsManager.panels.file_list import _shortcuts


class _FakeTagService:
    def __init__(self):
        self.tags = {"tag1", "tag2", "illustration"}
        self.file_tags = {"/path/to/a.png": ["tag1"]}

    def get_all_tags(self, root: str):
        return sorted(self.tags)

    def get_tags_for_files(self, root: str, paths):
        # 真实契约（V15）：TagService 批量 API 返回按解析路径键控的 dict。
        return {p: self.file_tags.get(p, []) for p in paths}

    def add_tag_to_files(self, root: str, paths: list[str], tag: str):
        self.tags.add(tag)
        for p in paths:
            if p not in self.file_tags:
                self.file_tags[p] = []
            if tag not in self.file_tags[p]:
                self.file_tags[p].append(tag)

    def remove_tag_from_files(self, root: str, paths: list[str], tag: str):
        for p in paths:
            if p in self.file_tags and tag in self.file_tags[p]:
                self.file_tags[p].remove(tag)


def test_quick_tagger_overlay_lifecycle():
    app = QApplication.instance() or QApplication([])
    svc = _FakeTagService()
    dlg = QuickTaggerOverlay(["/path/to/a.png"], "/root", tag_service=svc)
    dlg.show()
    app.processEvents()
    try:
        assert dlg._current_tags == ["tag1"]
        assert "tag2" in dlg._all_library_tags

        # Add tag via input
        dlg._input.setText("concept_art")
        dlg._add_current_tag()
        app.processEvents()

        assert "concept_art" in dlg._current_tags
        assert "concept_art" in svc.file_tags["/path/to/a.png"]

        # Remove tag
        dlg._remove_tag("tag1")
        app.processEvents()
        assert "tag1" not in dlg._current_tags
        assert "tag1" not in svc.file_tags["/path/to/a.png"]

        # Test Esc key dismisses
        esc_event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        dlg.keyPressEvent(esc_event)
        app.processEvents()
    finally:
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            try:
                dlg.close()
                dlg.deleteLater()
            except RuntimeError:
                pass
            app.processEvents()


def test_quick_tagger_close_button_matches_token_hit_area():
    """V06: the close button uses the shared hit_area/icon_sm tokens — the
    same 24×24 hot zone as QuickLookOverlay's close button (was 22×22/12)."""
    from AssetsManager.core import themes
    from AssetsManager.core.ui_scale import scaled_px

    app = QApplication.instance() or QApplication([])
    svc = _FakeTagService()
    dlg = QuickTaggerOverlay(["/path/to/a.png"], "/root", tag_service=svc)
    try:
        expected = scaled_px(themes.metrics("hit_area"))
        assert (dlg._close_btn.width(), dlg._close_btn.height()) == (expected, expected)
        assert dlg._close_btn.iconSize().width() == scaled_px(themes.metrics("icon_sm"))
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_shortcuts_dispatches_t_key():
    class _MockPanel:
        def __init__(self):
            self._view_mode = "Grid"
            self.tagger_opened = False

        def _selected_paths(self):
            return ["/path/to/file.png"]

        def _open_quick_tagger(self):
            self.tagger_opened = True

    panel = _MockPanel()
    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_T, Qt.KeyboardModifier.NoModifier)
    handled = _shortcuts.handle_key(panel, event)
    assert handled is True
    assert panel.tagger_opened is True
