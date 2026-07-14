"""Empty placeholder panel with visible border and background."""
from PySide6.QtWidgets import QLabel
from PySide6.QtCore import Qt
from AssetsManager.panels.base import PanelContent
from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager import i18n

tr = i18n.tr


class EmptyPanel(PanelContent):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(scaled_px(100))
        t = themes.get()
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(
            f"color: {t['muted']}; font-size: {scaled_pt(18)}px; background: transparent;"
        )
        label.setText(tr("panel.empty", default="Empty"))
        self.content_layout.addWidget(label)
        self.content_layout.addStretch()
