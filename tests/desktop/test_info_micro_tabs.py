"""Tests for InfoPanel MicroTabBar integration (tab switching & section filtering)."""
import pytest
from PySide6.QtWidgets import QApplication

from AssetsManager.panels.info import InfoPanel


@pytest.fixture(autouse=True)
def _pin_language_and_layout():
    """免疫同 worker 前序测试的两类进程级残留（2026-09-06 审查定性）。

    - 语言：``tr()`` 读 ``i18n._current_lang`` 模块全局，而
      ``_refresh_language`` 的实参被忽略（签名 ``_code``），且本机
      settings.json 持久化的 language 为 zh——任何"按 settings 值还原
      语言"的前序测试（test_info_interactions 同款 finally）都会把 zh
      留在进程里，使 ``assert _tabs[0] == "All"`` 在共享 worker 上必红。
      按 test_visual_baseline_a._pin_language 同款模式直接钉内存值。
    - info_panel_layout：InfoPanel.shutdown() 会把当前 micro-tab 的分区
      可见性持久化到共享 settings（restore_state 在下一个 InfoPanel 构造
      时回放），同 worker 后续的 InfoPanel 可见性用例（test_info_ai_tag
      可见性门）会被隐藏的分区拖红。用例前后清内存值即可双向免疫。
    """
    from AssetsManager import i18n
    from AssetsManager.core.settings import AppSettings

    settings = AppSettings.instance()
    saved_lang = i18n._current_lang
    saved_layout = settings.get("info_panel_layout")
    i18n._current_lang = "en"
    settings.set("info_panel_layout", None)
    yield
    i18n._current_lang = saved_lang
    settings.set("info_panel_layout", saved_layout)


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
