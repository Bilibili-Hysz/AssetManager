"""Tests for InfoPanel MicroTabBar integration (tab switching & section filtering)."""
import pytest
from PySide6.QtWidgets import QApplication

from AssetsManager.panels.info import InfoPanel


@pytest.fixture
def qapp():
    """Ensure QApplication instance exists for offscreen desktop tests."""
    app = QApplication.instance() or QApplication([])
    yield app


def test_info_panel_micro_tab_bar_initialization(qapp: QApplication):
    panel = InfoPanel()
    try:
        assert hasattr(panel, "_tab_bar")
        assert len(panel._tab_bar._tabs) == 4
        assert panel._tab_bar.current_index() == 0

        # By default (tab 0: All), all sections are unhidden
        assert not panel._meta_grp.isHidden()
        assert not panel._tags_grp.isHidden()
        assert not panel._notes_grp.isHidden()
    finally:
        panel.deleteLater()


def test_info_panel_micro_tab_switching(qapp: QApplication):
    panel = InfoPanel()
    try:
        # Tab 1: Metadata only
        panel._tab_bar.set_current_index(1, animate=False)
        assert not panel._meta_grp.isHidden()
        assert panel._tags_grp.isHidden()
        assert panel._notes_grp.isHidden()

        # Tab 2: Tags only
        panel._tab_bar.set_current_index(2, animate=False)
        assert panel._meta_grp.isHidden()
        assert not panel._tags_grp.isHidden()
        assert panel._notes_grp.isHidden()

        # Tab 3: Notes only
        panel._tab_bar.set_current_index(3, animate=False)
        assert panel._meta_grp.isHidden()
        assert panel._tags_grp.isHidden()
        assert not panel._notes_grp.isHidden()

        # Tab 0: All restored
        panel._tab_bar.set_current_index(0, animate=False)
        assert not panel._meta_grp.isHidden()
        assert not panel._tags_grp.isHidden()
        assert not panel._notes_grp.isHidden()
    finally:
        panel.deleteLater()


def test_info_panel_language_refresh_updates_tabs(qapp: QApplication):
    panel = InfoPanel()
    try:
        panel._refresh_language("en")
        assert len(panel._tab_bar._tabs) == 4
        assert panel._tab_bar._tabs[0] == "All"
    finally:
        panel.deleteLater()


def test_info_panel_tab_switch_resets_vertical_scroll_and_whitespace(qapp: QApplication):
    panel = InfoPanel()
    try:
        panel.resize(300, 500)
        panel.show()
        qapp.processEvents()

        # Simulate user scrolling down in All view
        panel._details_scroll.verticalScrollBar().setValue(150)
        assert panel._details_scroll.verticalScrollBar().value() == 150

        # Switch to Tags tab (tab 2)
        panel._tab_bar.set_current_index(2, animate=False)
        qapp.processEvents()
        assert panel._meta_grp.isHidden()
        assert not panel._tags_grp.isHidden()
        assert panel._details_scroll.verticalScrollBar().value() == 0

        # Switch back and scroll again
        panel._tab_bar.set_current_index(0, animate=False)
        qapp.processEvents()
        panel._details_scroll.verticalScrollBar().setValue(120)

        # Switch to Notes tab (tab 3)
        panel._tab_bar.set_current_index(3, animate=False)
        qapp.processEvents()
        assert panel._meta_grp.isHidden()
        assert panel._tags_grp.isHidden()
        assert not panel._notes_grp.isHidden()
        assert panel._details_scroll.verticalScrollBar().value() == 0
    finally:
        panel.shutdown()
        panel.deleteLater()
