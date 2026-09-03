"""Unit tests for StandardModalDialog template."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from AssetsManager import i18n
from AssetsManager.core.ui_scale import scaled_px
from AssetsManager.dialogs.color_picker_dialog import ColorPickerDialog
from AssetsManager.dialogs.modal_dialog import StandardModalDialog
from AssetsManager.dialogs.sidebar_settings_dialog import SidebarSettingsDialog
from AssetsManager.dialogs.tag_style_dialog import TagStyleDialog
from AssetsManager.dialogs.theme_preview_dialog import ThemePreviewDialog
from AssetsManager.panels.file_list._batch_rename_dialog import BatchRenameDialog
from AssetsManager.plugin_api.types import CommandOperator


class SampleDialog(StandardModalDialog):
    def setup_content(self, layout: QVBoxLayout) -> None:
        self.content_label = QLabel("Dialog Main Content")
        layout.addWidget(self.content_label)


def test_standard_modal_dialog_init():
    app = QApplication.instance() or QApplication([])
    dlg = SampleDialog(title="Settings Dialog", ok_text="Save", cancel_text="Dismiss")
    dlg.set_header("General Options", subtitle="Configure application options", icon_name="settings")
    dlg.show()
    app.processEvents()
    try:
        assert dlg._ok_btn.text() == "Save"
        assert dlg._cancel_btn.text() == "Dismiss"
        assert dlg.property("buttonVariant") is None  # dialog itself
        assert dlg._ok_btn.property("buttonVariant") == "primary"
        assert dlg._cancel_btn.property("buttonVariant") == "ghost"
        assert dlg.content_label.text() == "Dialog Main Content"
        assert dlg._modal_title_label.text() == "General Options"
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


# ── Track B migration contract: native QDialogs → StandardModalDialog ──

def _make_color_picker(tmp_path):
    return ColorPickerDialog(QColor("#123456"))


def _make_tag_style(tmp_path):
    return TagStyleDialog("hero")


def _make_sidebar_settings(tmp_path):
    return SidebarSettingsDialog()


def _make_theme_preview(tmp_path):
    return ThemePreviewDialog()


def _make_batch_rename(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    return BatchRenameDialog([str(tmp_path / "a.txt")])


def _make_share_qr(tmp_path):
    from AssetsManager.dialogs.share_qr_dialog import ShareQrDialog
    return ShareQrDialog(url="http://test.share/1")


def _make_tag_editor(tmp_path):
    from unittest.mock import Mock
    from AssetsManager.dialogs.tag_editor_dialog import TagEditorDialog
    store = Mock(get_tags=lambda p: [], get_all_tags=list)
    return TagEditorDialog(store, "test.png")


@pytest.mark.parametrize(
    "factory",
    [_make_color_picker, _make_tag_style, _make_sidebar_settings,
     _make_theme_preview, _make_batch_rename, _make_share_qr, _make_tag_editor],
    ids=["color_picker", "tag_style", "sidebar_settings", "theme_preview",
         "batch_rename", "share_qr", "tag_editor"],
)
def test_migrated_dialogs_use_standard_modal_template(factory, tmp_path):
    """Track B: every migrated popup inherits the modal template, hosts its
    OK/Cancel buttons through the template bar, and keeps no hand-built
    QDialogButtonBox around."""
    app = QApplication.instance() or QApplication([])
    dlg = factory(tmp_path)
    try:
        assert isinstance(dlg, StandardModalDialog)
        assert dlg._ok_btn.property("buttonVariant") == "primary"
        if dlg._cancel_btn is not None:
            assert dlg._cancel_btn.property("buttonVariant") == "ghost"
        assert dlg.findChildren(QDialogButtonBox) == []
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_color_picker_ok_emits_signal_and_accepts():
    app = QApplication.instance() or QApplication([])
    dlg = ColorPickerDialog(QColor("#123456"))
    emitted = []
    dlg.color_selected.connect(emitted.append)
    try:
        dlg._on_ok_clicked()
        assert emitted == [QColor("#123456")]
        assert dlg.result() == QDialog.DialogCode.Accepted
    finally:
        dlg.deleteLater()
        app.processEvents()


def test_color_picker_uses_scaled_min_size_no_hard_resize():
    app = QApplication.instance() or QApplication([])
    dlg = ColorPickerDialog(QColor("#123456"))
    try:
        assert dlg.minimumSize() == QSize(scaled_px(400), scaled_px(350))
    finally:
        dlg.deleteLater()
        app.processEvents()


def test_batch_rename_dialog_apply_button_tracks_plan_validity(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    app = QApplication.instance() or QApplication([])
    dlg = BatchRenameDialog([str(tmp_path / "a.txt"), str(tmp_path / "b.txt")])
    try:
        assert dlg._apply is dlg._ok_btn
        assert dlg._apply.isEnabled()

        dlg._pattern.setText("same")  # collides with the source name
        assert dlg.plan is not None and not dlg.plan.is_valid
        assert not dlg._apply.isEnabled()

        # Guarded accept: an invalid plan must not mark the dialog accepted.
        dlg.accept()
        assert dlg.result() != QDialog.DialogCode.Accepted
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_theme_preview_dialog_buttons_use_apply_and_close_texts():
    app = QApplication.instance() or QApplication([])
    dlg = ThemePreviewDialog()
    try:
        assert dlg._ok_btn.text() == i18n.tr("settings.apply_theme")
        assert dlg._cancel_btn.text() == i18n.tr("dialog.close")
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


class _SampleOperator(CommandOperator):
    id = "sample.op"
    title = "Sample Operator"
    params = {
        "name": {"type": "str", "label": "Name", "default": "x"},
        "count": {"type": "int", "label": "Count", "default": 3, "min": 0, "max": 10},
        "enabled": {"type": "bool", "label": "Enabled", "default": True},
    }


def test_operator_params_dialog_is_standard_modal(monkeypatch):
    from AssetsManager.dialogs import plugin_operator_dialog as pod

    app = QApplication.instance() or QApplication([])
    dlg = pod._OperatorParamsDialog(_SampleOperator, {"name": "keep"})
    try:
        assert isinstance(dlg, StandardModalDialog)
        values = dlg.collect_values()
        assert values["name"] == "keep"
        assert values["count"] == 3
        assert values["enabled"] is True
    finally:
        dlg.close()
        dlg.deleteLater()
        app.processEvents()


def test_prompt_operator_params_round_trip(monkeypatch):
    from AssetsManager.dialogs import plugin_operator_dialog as pod

    # Empty schema short-circuits without any dialog.
    assert pod.prompt_operator_params(_BareOperator, {"k": 1}) == {"k": 1}

    # Rejected exec yields None.
    monkeypatch.setattr(pod._OperatorParamsDialog, "exec", lambda self: 0)
    assert pod.prompt_operator_params(_SampleOperator, {"name": "keep"}) is None

    # Accepted exec collects the edited editor values.
    def fake_exec(self):
        self._editors["name"].setText("edited")
        return self.DialogCode.Accepted

    monkeypatch.setattr(pod._OperatorParamsDialog, "exec", fake_exec)
    result = pod.prompt_operator_params(_SampleOperator, {"name": "keep"})
    assert result is not None
    assert result["name"] == "edited"
    assert result["count"] == 3
    assert result["enabled"] is True


class _BareOperator(CommandOperator):
    id = "bare.op"
    params: dict = {}
