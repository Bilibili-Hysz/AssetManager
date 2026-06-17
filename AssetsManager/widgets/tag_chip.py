"""Shared tag chip widget creation."""
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt
from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_px
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
    chip.setStyleSheet(f"background: {t['accent']}; border-radius: 6px;")
    layout = QHBoxLayout(chip)
    layout.setContentsMargins(6, 2, 4, 2)
    layout.setSpacing(2)

    name = QLabel(tag)
    name.setStyleSheet(f"color: {t['heading']}; font-size: 11px; background: transparent;")
    layout.addWidget(name)

    if on_remove:
        close_btn = QPushButton("×")
        close_btn.setFixedSize(scaled_px(14), scaled_px(14))
        close_btn.setFlat(True)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            f"color: {t['heading']}; font-size: 11px; padding: 0; "
            f"background: transparent; border-radius: 3px;")
        close_btn.setToolTip(f"Remove tag: {tag}")
        close_btn.clicked.connect(lambda checked, tg=tag: on_remove(tg))
        layout.addWidget(close_btn)

    lib = get_library()
    syn_text = lib.all_synonyms_text(tag)
    tooltip = f"Tag: {tag}" + (f"\n\nSynonyms:\n{syn_text}" if syn_text else "")
    chip.setToolTip(tooltip)

    return chip
