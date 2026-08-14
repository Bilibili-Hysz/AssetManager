"""CollapsiblePanel — animated expand/collapse container with title and description."""
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve, QSize
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton
from AssetsManager.core import icons, themes
from AssetsManager.core.color_utils import alpha
from AssetsManager.core.ui_scale import scaled_px, scaled_pt


class CollapsiblePanel(QWidget):
    """Section with clickable header that toggles content visibility with animation."""

    def __init__(self, title: str, description: str = "", expanded: bool = True, parent=None):
        super().__init__(parent)
        self._expanded = expanded
        self._title = title
        self._description = description
        self._anim = None

        self._header_btn = QPushButton()
        self._header_btn.setCheckable(True)
        self._header_btn.setChecked(expanded)
        self._header_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header_btn.setFixedHeight(scaled_px(32))
        self._update_header_text()
        self._apply_header_style()
        self._header_btn.toggled.connect(self._on_toggle)

        self._content = QWidget()
        self._content.setVisible(expanded)
        self._content.setStyleSheet(
            "QWidget { background: transparent; } QLabel { color: inherit; }")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(scaled_px(12), scaled_px(6), 0, scaled_px(6))
        self._content_layout.setSpacing(scaled_px(6))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header_btn)
        layout.addWidget(self._content)

    def content_layout(self) -> QVBoxLayout:
        return self._content_layout

    def refresh_theme(self):
        self._update_header_text()
        self._apply_header_style()

    def _update_header_text(self):
        arrow = "chevron_down" if self._expanded else "chevron_right"
        self._header_btn.setIcon(icons.icon(arrow, color="icon_primary", size=scaled_px(14)))
        self._header_btn.setIconSize(QSize(scaled_px(14), scaled_px(14)))
        text = self._title
        if self._description:
            text += f" — {self._description}"
        self._header_btn.setText(text)
        self._header_btn.setAccessibleName(self._title)

    def _apply_header_style(self):
        t = themes.get()
        bg = alpha(t["accent"], 0.19) if self._expanded else "transparent"
        hover_bg = alpha(t["accent"], 0.13)
        hairline = t.get("border_subtle", alpha(t["border"], 0.5))
        self._header_btn.setStyleSheet(
            f"QPushButton {{ text-align: left; font-weight: bold; font-size: {scaled_pt(12)}px; "
            f"color: {t['heading']}; background: {bg}; border: 1px solid {hairline}; "
            f"border-radius: {scaled_px(8)}px; padding: {scaled_px(6)}px {scaled_px(10)}px; }}"
            f"QPushButton:hover {{ background: {hover_bg}; }}")

    def _on_toggle(self, checked):
        self._expanded = checked
        self._update_header_text()
        self._apply_header_style()
        self._animate_content(checked)

    def _animate_content(self, show: bool):
        if self._anim and self._anim.state() == QPropertyAnimation.State.Running:
            self._anim.stop()

        if show:
            self._content.setVisible(True)
            self._content.setMaximumHeight(16777215)
            target = self._content.sizeHint().height()
        else:
            target = 0

        anim = QPropertyAnimation(self._content, b"maximumHeight")
        anim.setDuration(200)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        if show:
            anim.setStartValue(0)
            anim.setEndValue(target)
        else:
            anim.setStartValue(self._content.height())
            anim.setEndValue(0)
            anim.finished.connect(lambda: self._content.setVisible(False))
        self._anim = anim
        anim.start()
