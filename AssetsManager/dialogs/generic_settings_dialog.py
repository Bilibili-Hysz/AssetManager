"""Generic settings dialog — shown when a panel has no specific settings yet."""
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt
from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.widgets.stylekit import StyleKit
from AssetsManager.dialogs.modal_dialog import StandardModalDialog
from AssetsManager import i18n
tr = i18n.tr


class _NoSettingsDialog(StandardModalDialog):
    """Single-action notice popup: one primary Close, no Cancel."""

    # Always built by StandardModalDialog.__init__ (show_cancel defaults on);
    # declared because the base assigns it in two branches (button | None).
    _cancel_btn: QPushButton

    def __init__(self, parent=None):
        super().__init__(
            parent,
            title=tr("panel.settings"),
            min_size=(scaled_px(300), scaled_px(180)),
            ok_text=tr("dialog.close"),
        )
        # A no-settings notice has exactly one action; the template-hosted
        # ghost Cancel would be a meaningless second exit.
        self._cancel_btn.hide()

    def setup_content(self, layout: QVBoxLayout) -> None:
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        msg = QLabel(tr("panel.no_settings"))
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Existing sanctioned site relocated from the former hand-built dialog.
        msg.setStyleSheet(sk.label_css("body", size=int(sk.prop("font_size", "lg", 14))))
        layout.addWidget(msg, 1)


def generic_settings_dialog(parent=None) -> QDialog:
    dlg = _NoSettingsDialog(parent)
    dlg.exec()
    return dlg
