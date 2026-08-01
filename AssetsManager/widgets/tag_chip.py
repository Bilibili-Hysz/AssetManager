"""Shared tag chip widget creation."""
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, QSize
from AssetsManager.core import icons, themes
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.core.tag_library import get_library


def create_tag_chip(tag: str, on_remove=None, parent=None) -> QWidget:
    """Create a styled tag chip widget.

    Args:
        tag: The tag name to display.
        on_remove: Callback when the X button is clicked (receives tag name).
        parent: Parent widget.

    Returns:
        A QWidget containing the tag chip.
    """
    t = themes.get()
    chip = QWidget(parent)
    chip.setStyleSheet(f"background: {t['accent']}; border-radius: {scaled_px(6)}px;")
    layout = QHBoxLayout(chip)
    layout.setContentsMargins(scaled_px(6), scaled_px(2), scaled_px(4), scaled_px(2))
    layout.setSpacing(scaled_px(2))

    name = QLabel(tag)
    name.setStyleSheet(f"color: {t['heading']}; font-size: {scaled_pt(11)}px; background: transparent;")
    layout.addWidget(name)

    if on_remove:
        close_btn = QPushButton()
        close_btn.setIcon(icons.icon("close", color=t["heading"], size=scaled_px(12)))
        close_btn.setIconSize(QSize(scaled_px(12), scaled_px(12)))
        close_btn.setAccessibleName(f"Remove tag: {tag}")
        close_btn.setFixedSize(scaled_px(14), scaled_px(14))
        close_btn.setFlat(True)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            f"color: {t['heading']}; font-size: {scaled_pt(11)}px; padding: 0; "
            f"background: transparent; border-radius: {scaled_px(3)}px;")
        close_btn.setToolTip(f"Remove tag: {tag}")
        close_btn.clicked.connect(lambda checked, tg=tag: on_remove(tg))
        layout.addWidget(close_btn)

    lib = get_library()
    syn_text = lib.all_synonyms_text(tag)
    tooltip = f"Tag: {tag}" + (f"\n\nSynonyms:\n{syn_text}" if syn_text else "")
    chip.setToolTip(tooltip)

    return chip
