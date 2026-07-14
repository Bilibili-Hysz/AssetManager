"""CollapsiblePanel — animated expand/collapse container with title and description."""
from PySide6.QtCore import Qt, QPropertyAnimation, QEasingCurve
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton
from AssetsManager.core import themes
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
        self._apply_header_style()

    def _update_header_text(self):
        arrow = "\u25BE" if self._expanded else "\u25B8"
        text = f"  {arrow} {self._title}"
        if self._description:
            text += f"  \u2014  {self._description}"
        self._header_btn.setText(text)

    def _apply_header_style(self):
        t = themes.get()
        bg = _alpha(t["accent"], 0.19) if self._expanded else "transparent"
        hover_bg = _alpha(t["accent"], 0.13)
        self._header_btn.setStyleSheet(
            f"QPushButton {{ text-align: left; font-weight: bold; font-size: {scaled_pt(12)}px; "
            f"color: {t['heading']}; background: {bg}; border: 1px solid {t['border']}40; "
            f"border-radius: {scaled_px(4)}px; padding: 4px 8px; }}"
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


def _alpha(hex_color: str, alpha: float) -> str:
    a = int(alpha * 255)
    return f"{hex_color}{a:02x}"
