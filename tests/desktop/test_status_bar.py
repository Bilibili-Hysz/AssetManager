"""Tests for the main-window status bar widget."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from AssetsManager.core import themes
from AssetsManager.core.settings import AppSettings
from AssetsManager.widgets.status_bar import StatusBarWidget


@pytest.fixture
def status_bar():
    app = QApplication.instance() or QApplication([])
    widget = StatusBarWidget()
    widget.resize(900, widget.height())
    widget.show()
    app.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_status_bar_renders_all_sections(status_bar):
    assert status_bar.isVisible()
    assert status_bar.height() == status_bar._sk.px(26)
    assert all(isinstance(label, QLabel) for label in (
        status_bar.file_count_label,
        status_bar.selection_label,
        status_bar.path_label,
        status_bar.message_label,
    ))
    assert len(status_bar._separators) == 2


def test_update_file_and_selection_counts(status_bar):
    status_bar.update_file_count(128)
    status_bar.update_selection(7)

    assert "128" in status_bar.file_count_label.text()
    assert "7" in status_bar.selection_label.text()


def test_update_path_and_message(status_bar):
    path = r"C:\Assets\Current Library"
    status_bar.update_path(path)
    status_bar.update_message("Index is up to date")

    assert status_bar.path_label.text() == path
    assert status_bar.path_label.toolTip() == path
    assert status_bar.message_label.text() == "Index is up to date"


def test_long_path_is_compact_and_keeps_full_tooltip(status_bar):
    path = "C:/" + "/".join(["very-long-library-directory"] * 6)
    status_bar.update_path(path)

    compact = status_bar.path_label.text()
    assert "..." in compact
    assert len(compact) <= status_bar._MAX_PATH_LENGTH
    assert compact.startswith("C:/")
    assert compact.endswith("very-long-library-directory")
    assert status_bar.path_label.toolTip() == path


def test_refresh_theme_reapplies_current_tokens(status_bar, monkeypatch):
    updated = dict(themes.get(), header="#102030", border="#405060", muted="#708090")
    monkeypatch.setattr(themes, "get", lambda: updated)

    status_bar.refresh_theme()

    assert updated["header"] in status_bar.styleSheet()
    assert updated["border"] in status_bar.styleSheet()
    for label in status_bar.findChildren(QLabel):
        assert updated["muted"] in label.styleSheet()


def test_reduced_motion_needs_no_animation(status_bar):
    settings = AppSettings.instance()
    original = settings.get("reduce_motion", False)
    settings.set("reduce_motion", True)
    try:
        status_bar.update_message("Ready")
        status_bar.refresh_theme()

        assert status_bar.message_label.text() == "Ready"
        assert status_bar.graphicsEffect() is None
        assert status_bar.message_label.graphicsEffect() is None
    finally:
        settings.set("reduce_motion", original)


def test_all_labels_use_scaled_muted_style(status_bar):
    expected = status_bar._sk.muted_css(11)
    for label in status_bar.findChildren(QLabel):
        assert label.styleSheet() == expected
