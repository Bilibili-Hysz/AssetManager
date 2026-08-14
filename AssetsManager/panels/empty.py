"""Empty placeholder panel with visible border, background, and status hint."""
from PySide6.QtWidgets import QLabel, QVBoxLayout
from PySide6.QtCore import QSize, Qt
from AssetsManager.panels.base import PanelContent
from AssetsManager.core import icons, themes
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.widgets.stylekit import StyleKit
from AssetsManager import i18n

tr = i18n.tr


class EmptyPanel(PanelContent):
    def __init__(self, parent=None, subtitle: str = ""):
        super().__init__(parent)
        self.setMinimumHeight(scaled_px(100))

        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)

        # ── Semantic icon (muted, above the title) ────────────
        self._icon_label = QLabel()
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setStyleSheet("background: transparent;")
        self._set_icon("folder", "icon_muted")

        # ── Main label (heading color, larger) ────────────────
        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(sk.label_css("heading", size=18, bold=True))
        label.setText(tr("panel.empty", default="Empty"))

        # ── Subtitle label (muted, smaller) ───────────────────
        sub = QLabel()
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet(sk.muted_css(12))
        sub.setText(subtitle or tr(
            "panel.empty.hint",
            default="Drop files here or use the toolbar to get started"))

        # ── Layout ────────────────────────────────────────────
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(sk.px(8))
        col.addStretch()
        col.addWidget(self._icon_label)
        col.addWidget(label)
        col.addWidget(sub)
        col.addStretch()
        self.content_layout.addLayout(col)

    def _set_icon(self, name: str, color: str):
        """Render a semantic SVG icon into the placeholder label."""
        size = scaled_px(40)
        self._icon_label.setPixmap(
            icons.icon(name, color=color, size=size).pixmap(QSize(size, size)))

    # ── Factory helpers ──────────────────────────────────────

    @classmethod
    def for_loading(cls, parent=None, subtitle: str = ""):
        """Return an EmptyPanel styled as a loading state."""
        p = cls(parent=parent, subtitle=subtitle or tr(
            "panel.loading", default="Loading…"))
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        p._set_icon("clock", "icon_accent")
        labels = p.findChildren(QLabel)
        for lb in labels:
            if lb.text() in ("Empty", tr("panel.empty", default="Empty")):
                lb.setText(tr("panel.loading", default="Loading…"))
                lb.setStyleSheet(sk.label_css("accent", size=18, bold=True))
        return p

    @classmethod
    def for_error(cls, parent=None, message: str = "", subtitle: str = ""):
        """Return an EmptyPanel styled as an error state."""
        p = cls(parent=parent, subtitle=subtitle or tr(
            "panel.error.hint", default="Something went wrong"))
        sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
        p._set_icon("close", "danger")
        labels = p.findChildren(QLabel)
        for lb in labels:
            if lb.text() in ("Empty", tr("panel.empty", default="Empty")):
                lb.setText(message or tr("panel.error", default="Error"))
                lb.setStyleSheet(sk.label_css("danger", size=18, bold=True))
        return p
