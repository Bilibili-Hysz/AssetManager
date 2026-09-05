"""Desktop visual component unification & style governance contract tests.

This test suite guarantees that all desktop visual components adhere to the
unified Design System 2.0 architecture and eliminates fragmented "ad-hoc"
implementations:
  1. Empty states across all panels must use EmptyStateWidget.
  2. Main panels inherit StandardPanel with standardized slot contracts.
  3. Secondary dialogs inherit StandardModalDialog with unified button bars.
  4. Buttons adhere to recognized buttonVariant tokens and hit-area minimums.
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.dialogs.color_picker_dialog import ColorPickerDialog
from AssetsManager.dialogs.modal_dialog import StandardModalDialog
from AssetsManager.dialogs.share_qr_dialog import ShareQrDialog
from AssetsManager.dialogs.sidebar_settings_dialog import SidebarSettingsDialog
from AssetsManager.dialogs.tag_editor_dialog import TagEditorDialog
from AssetsManager.dialogs.tag_style_dialog import TagStyleDialog
from AssetsManager.dialogs.theme_preview_dialog import ThemePreviewDialog
from AssetsManager.panels.base import StandardPanel
from AssetsManager.panels.file_list import FileListPanel
from AssetsManager.panels.file_list._batch_rename_dialog import BatchRenameDialog
from AssetsManager.panels.info import InfoPanel
from AssetsManager.panels.sidebar import SidebarPanel
from AssetsManager.panels.tag_tree import TagTreePanel
from AssetsManager.widgets.empty_state import EmptyStateWidget


# ── 1. EmptyStateWidget Unification ──────────────────────────────────────────

def test_info_panel_uses_standard_empty_state_widget():
    """InfoPanel must use EmptyStateWidget for its unselected/empty preview state."""
    app = QApplication.instance() or QApplication([])
    panel = InfoPanel()
    try:
        assert isinstance(panel._empty_preview_state, EmptyStateWidget)
        assert panel._empty_preview_state._kind == "empty"
        # Compatibility properties for tests and legacy callers
        assert panel._empty_preview_icon is panel._empty_preview_state._icon_label
        assert panel._empty_preview_label is panel._empty_preview_state._title_label
    finally:
        panel.shutdown()
        panel.deleteLater()
        app.processEvents()


def test_file_list_panel_uses_standard_empty_state_widget(tmp_path):
    """FileListPanel must mount EmptyStateWidget for empty directory/search feedback."""
    app = QApplication.instance() or QApplication([])
    panel = FileListPanel()
    try:
        assert hasattr(panel, "_empty_state")
        assert isinstance(panel._empty_state, EmptyStateWidget)
        assert panel._empty_state._kind in ("directory", "search", "empty")
    finally:
        panel.shutdown()
        panel.deleteLater()
        app.processEvents()


# ── 2. Panel Scaffolding Unification ─────────────────────────────────────────

@pytest.mark.parametrize("panel_cls", [SidebarPanel, TagTreePanel])
def test_nav_panels_inherit_standard_panel(panel_cls):
    """Navigation panels must inherit from StandardPanel and expose slot architecture."""
    assert issubclass(panel_cls, StandardPanel)


def test_file_list_inherits_panel_content():
    """FileListPanel must inherit from PanelContent with lifecycle contracts."""
    from AssetsManager.panels.base import PanelContent
    assert issubclass(FileListPanel, PanelContent)


def test_standard_panel_slot_integrity():
    """StandardPanel slots must maintain valid hierarchy without orphans."""
    app = QApplication.instance() or QApplication([])
    panel = SidebarPanel()
    try:
        assert panel._toolbar_widget is not None
        assert panel._body_widget is not None
        assert panel._footer_widget is not None
    finally:
        panel.shutdown()
        panel.deleteLater()
        app.processEvents()


# ── 3. Modal Dialog Architecture Unification ─────────────────────────────────

@pytest.mark.parametrize(
    "dialog_cls",
    [
        ColorPickerDialog,
        TagStyleDialog,
        SidebarSettingsDialog,
        ThemePreviewDialog,
        BatchRenameDialog,
        ShareQrDialog,
        TagEditorDialog,
    ],
    ids=[
        "ColorPicker",
        "TagStyle",
        "SidebarSettings",
        "ThemePreview",
        "BatchRename",
        "ShareQr",
        "TagEditor",
    ],
)
def test_secondary_dialogs_inherit_standard_modal_dialog(dialog_cls):
    """All secondary modal popups must inherit from StandardModalDialog."""
    assert issubclass(dialog_cls, StandardModalDialog)


def test_modal_dialog_button_bar_contract(tmp_path):
    """StandardModalDialog implementations must use template button bar."""
    app = QApplication.instance() or QApplication([])
    dlg = ShareQrDialog(url="http://example.com/share")
    try:
        assert isinstance(dlg, StandardModalDialog)
        assert dlg._ok_btn.property("buttonVariant") == "primary"
        assert dlg.findChildren(QDialogButtonBox) == []
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


# ── 4. Button Variant and Metric Grid Standards ──────────────────────────────

def test_button_variant_contract():
    """Theme system button variant helper must set standard buttonVariant property."""
    from PySide6.QtWidgets import QPushButton
    app = QApplication.instance() or QApplication([])
    btn = QPushButton("Action")
    for variant in ("primary", "secondary", "ghost", "danger"):
        themes.set_button_variant(btn, variant)
        assert btn.property("buttonVariant") == variant

    btn.deleteLater()
    app.processEvents()


def test_metric_grid_tokens_exist_and_positive():
    """Metric grid tokens (icon_sm, hit_area, control_height_md) must be positive."""
    for token in ("icon_xs", "icon_sm", "icon_md", "icon_lg", "hit_area", "control_height_md"):
        val = themes.metrics(token)
        assert isinstance(val, int)
        assert val > 0
        scaled = scaled_px(val)
        assert scaled >= val
