"""Dominant color palette strip widget for desktop InfoPanel and Detail views."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QCursor, QGuiApplication
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton, QToolTip

from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.i18n import tr


def _is_light(hex_str: str) -> bool:
    c = QColor(hex_str)
    if not c.isValid():
        return False
    # Relative luminance
    lum = 0.2126 * (c.red() / 255.0) + 0.7152 * (c.green() / 255.0) + 0.0722 * (c.blue() / 255.0)
    return lum > 0.52


class DominantPaletteStrip(QWidget):
    """Horizontal capsule strip displaying extracted dominant color swatches."""

    color_clicked = Signal(str)

    def __init__(self, colors: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("dominantPaletteStrip")
        self._colors: list[str] = []
        self._pill_buttons: list[QPushButton] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            scaled_px(8), scaled_px(4), scaled_px(8), scaled_px(4)
        )
        layout.setSpacing(scaled_px(6))

        self._label = QLabel(tr("info.palette", fallback="Palette"))
        self._label.setObjectName("dominantPaletteLabel")
        layout.addWidget(self._label)

        self._pills_layout = QHBoxLayout()
        self._pills_layout.setContentsMargins(0, 0, 0, 0)
        self._pills_layout.setSpacing(scaled_px(4))
        layout.addLayout(self._pills_layout, 1)

        self._apply_style()
        if colors:
            self.set_colors(colors)
        else:
            self.hide()

    def set_colors(self, colors: list[str]) -> None:
        """Update displayed colors (capped at 5 swatches)."""
        while self._pills_layout.count():
            item = self._pills_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._pill_buttons.clear()

        valid_colors = [c for c in colors if QColor(c).isValid()][:5]
        self._colors = valid_colors
        if not valid_colors:
            self.hide()
            return

        self.show()
        r_sm = scaled_px(int(themes.prop("border_radius", "sm")))
        h = scaled_px(20)

        for hex_code in valid_colors:
            btn = QPushButton()
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(h)
            btn.setToolTip(f"{hex_code.upper()} (点击复制)")
            btn.setAccessibleName(f"Color {hex_code}")

            border_subtle = (
                "rgba(255, 255, 255, 0.25)"
                if not _is_light(hex_code)
                else "rgba(0, 0, 0, 0.15)"
            )
            btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: {hex_code}; "
                f"  border: {scaled_px(1)}px solid {border_subtle}; "
                f"  border-radius: {r_sm}px; "
                f"}}"
                f"QPushButton:hover {{"
                f"  border: {scaled_px(2)}px solid {themes.color('accent')}; "
                f"}}"
            )
            btn.clicked.connect(lambda checked=False, hx=hex_code: self._on_pill_clicked(hx))
            self._pills_layout.addWidget(btn, 1)
            self._pill_buttons.append(btn)

    def _on_pill_clicked(self, hex_code: str) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(hex_code.upper())
        self.color_clicked.emit(hex_code)
        QToolTip.showText(QCursor.pos(), f"Copied {hex_code.upper()}!")

    def _apply_style(self) -> None:
        t = themes.get()
        r_md = scaled_px(int(themes.prop("border_radius", "md")))
        font_sm = scaled_pt(int(themes.prop("font_size", "sm")))
        self.setStyleSheet(
            f"#dominantPaletteStrip {{"
            f"  background: {themes.alpha(t['panel'], 0.5)}; "
            f"  border: {scaled_px(1)}px solid {t['border_subtle']}; "
            f"  border-radius: {r_md}px; "
            f"}}"
            f"#dominantPaletteLabel {{"
            f"  color: {t['muted']}; "
            f"  font-size: {font_sm}px; "
            f"  font-weight: bold; "
            f"  background: transparent; "
            f"  border: none; "
            f"}}"
        )
