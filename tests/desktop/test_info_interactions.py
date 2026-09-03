"""Tests for InfoPanel interaction optimizations (button states & splitter persistence)."""
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from PySide6.QtWidgets import QApplication

from AssetsManager import i18n
from AssetsManager.core.settings import AppSettings
from AssetsManager.panels.info import InfoPanel
from AssetsManager.panels._info_parts import _AsyncRequest


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def test_info_panel_buttons_disabled_on_empty_selection(qapp: QApplication):
    panel = InfoPanel()
    try:
        # Initially empty selection
        assert not panel._open_btn.isEnabled()
        assert not panel._copy_btn.isEnabled()
        assert panel._open_btn.toolTip() == i18n.tr("info.select_file_first")
        assert panel._copy_btn.toolTip() == i18n.tr("info.select_file_first")

        # Test in Chinese locale
        orig_lang = AppSettings.instance().get("language") or "en"
        try:
            i18n.set_language("zh")
            panel._refresh_language("zh")
            assert panel._open_btn.toolTip() == "请先选择文件"
            assert panel._copy_btn.toolTip() == "请先选择文件"
        finally:
            i18n.set_language(orig_lang)
            panel._refresh_language(orig_lang)
    finally:
        panel.shutdown()
        panel.deleteLater()


def test_info_panel_buttons_enabled_on_file_render_and_disabled_on_clear(qapp: QApplication, tmp_path: Path):
    test_file = tmp_path / "sample.txt"
    test_file.write_text("hello", encoding="utf-8")

    panel = InfoPanel()
    try:
        # Create dummy FileInfo
        file_info = MagicMock()
        file_info.name = "sample.txt"
        file_info.file_type = "Text"
        file_info.size_display = "5 B"
        file_info.modified_display = "2026-09-03"
        file_info.parent_path = str(tmp_path)
        file_info.is_dir = False
        file_info.dir_summary = None
        file_info.palette = None
        file_info.plugin_fields = ()
        file_info.urls = ()
        file_info.tags = ()
        file_info.notes = ""
        file_info.rating = 0

        request = _AsyncRequest(
            generation=1,
            session=MagicMock(),
            path=str(test_file),
        )
        panel._current_path = str(test_file)
        panel._render_file_info(request, file_info)

        # Buttons should now be enabled with standard tooltips
        assert panel._open_btn.isEnabled()
        assert panel._copy_btn.isEnabled()
        assert panel._open_btn.toolTip() == i18n.tr("info.open_tooltip")
        assert panel._copy_btn.toolTip() == i18n.tr("info.copy_tooltip")

        # Clear back to empty state
        panel._show_empty_state()
        assert not panel._open_btn.isEnabled()
        assert not panel._copy_btn.isEnabled()
        assert panel._open_btn.toolTip() == i18n.tr("info.select_file_first")
        assert panel._copy_btn.toolTip() == i18n.tr("info.select_file_first")
    finally:
        panel.shutdown()
        panel.deleteLater()


def test_info_panel_splitter_height_persistence(qapp: QApplication, monkeypatch):
    persisted: dict = {}
    monkeypatch.setattr(AppSettings.instance(), "get", lambda key, default=None: persisted.get(key, default))
    monkeypatch.setattr(AppSettings.instance(), "set", lambda key, val: persisted.__setitem__(key, val))
    monkeypatch.setattr(AppSettings.instance(), "save", lambda: None)

    panel = InfoPanel()
    try:
        panel.resize(300, 600)
        panel.show()
        qapp.processEvents()

        # Restore custom sizes
        panel.restore_state({"splitter": [180, 320]})
        assert panel._saved_splitter_sizes == [180, 320]

        # Moving splitter updates saved sizes
        panel._splitter.setSizes([200, 300])
        panel._on_splitter_moved()
        saved = panel._saved_splitter_sizes
        assert len(saved) == 2
        # Ratio 200:300 is preserved
        assert abs(saved[0] / sum(saved) - 200 / 500) < 0.05
        assert panel._layout_save_timer.isActive()

        # Shutdown flushes pending timer and persists
        panel.shutdown()
        assert not panel._layout_save_timer.isActive()
        assert "info_panel_layout" in persisted
        saved_splitter = persisted["info_panel_layout"]["splitter"]
        assert len(saved_splitter) == 2
        assert abs(saved_splitter[0] / sum(saved_splitter) - 200 / 500) < 0.05
    finally:
        panel.deleteLater()
