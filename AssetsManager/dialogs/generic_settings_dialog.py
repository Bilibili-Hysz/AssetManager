"""Generic settings dialog — shown when a panel has no specific settings yet."""
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt
from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.widgets.stylekit import StyleKit
from AssetsManager import i18n
tr = i18n.tr


def generic_settings_dialog(parent=None) -> QDialog:
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("panel.settings"))
    dlg.setMinimumSize(scaled_px(300), scaled_px(180))
    themes.apply_to(dlg)

    sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)

    layout = QVBoxLayout(dlg)

    msg = QLabel(tr("panel.no_settings"))
    msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
    msg.setStyleSheet(sk.label_css("body", size=int(sk.prop("font_size", "lg", 14))))
    layout.addWidget(msg)

    close_btn = QPushButton(tr("dialog.close"))
    close_btn.clicked.connect(dlg.accept)
    layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignCenter)

    dlg.exec()
    return dlg
