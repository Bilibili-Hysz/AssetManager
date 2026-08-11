"""Shared tag chip widget creation."""
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, QSize
from AssetsManager.core import icons, themes
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager.core.tag_library import get_library
from AssetsManager.widgets.stylekit import StyleKit

# The synonym tooltip text is identical for every chip of the same tag and
# only changes when the tag library is edited, so it is computed once per
# tag and cached. Bounded: when the cache exceeds the limit it is cleared
# (simple, predictable eviction for a long-lived app session).
_synonyms_cache: dict[str, str] = {}
_SYNONYMS_CACHE_LIMIT = 500


def _synonyms_text_for(tag: str) -> str:
    """Return cached synonym text for a tag, computing it on first use."""
    cached = _synonyms_cache.get(tag)
    if cached is not None:
        return cached
    syn_text = get_library().all_synonyms_text(tag)
    if len(_synonyms_cache) >= _SYNONYMS_CACHE_LIMIT:
        _synonyms_cache.clear()
    _synonyms_cache[tag] = syn_text
    return syn_text


def create_tag_chip(tag: str, on_remove=None, parent=None) -> QWidget:
    """Create a styled tag chip widget.

    Args:
        tag: The tag name to display.
        on_remove: Callback when the X button is clicked (receives tag name).
        parent: Parent widget.

    Returns:
        A QWidget containing the tag chip.
    """
    sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
    accent = sk.token("accent")
    on_accent = sk.token("on_accent")
    chip = QWidget(parent)
    chip.setObjectName("TagChip")
    chip.setAccessibleName(f"Tag: {tag}")
    chip.setStyleSheet(
        f"QWidget#TagChip {{ background: {accent}; "
        f"border: 1px solid transparent; border-radius: {sk.px(6)}px; }}"
        f"QWidget#TagChip:hover {{ border-color: {on_accent}; }}")
    layout = QHBoxLayout(chip)
    layout.setContentsMargins(scaled_px(6), scaled_px(2), scaled_px(4), scaled_px(2))
    layout.setSpacing(scaled_px(2))

    name = QLabel(tag)
    name.setObjectName("TagChipLabel")
    name.setStyleSheet(
        f"color: {on_accent}; font-size: {scaled_pt(11)}px; "
        "background: transparent;")
    layout.addWidget(name)

    if on_remove:
        close_btn = QPushButton()
        close_btn.setObjectName("TagChipClose")
        close_btn.setIcon(
            icons.icon("close", color="icon_on_accent", size=scaled_px(12)))
        close_btn.setIconSize(QSize(scaled_px(12), scaled_px(12)))
        close_btn.setAccessibleName(f"Remove tag: {tag}")
        close_btn.setAccessibleDescription(
            f"Removes the {tag} tag from this item")
        close_btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        close_btn.setFixedSize(scaled_px(18), scaled_px(18))
        close_btn.setFlat(True)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            f"QPushButton#TagChipClose {{ color: {on_accent}; padding: 0; "
            f"background: transparent; border: 1px solid transparent; "
            f"border-radius: {scaled_px(3)}px; }}"
            f"QPushButton#TagChipClose:hover {{ border-color: {on_accent}; }}"
            f"QPushButton#TagChipClose:focus {{ border: 1px solid {on_accent}; "
            f"background: {accent}; }}")
        close_btn.setToolTip(f"Remove tag: {tag}")
        close_btn.clicked.connect(lambda checked, tg=tag: on_remove(tg))
        layout.addWidget(close_btn)

    syn_text = _synonyms_text_for(tag)
    tooltip = f"Tag: {tag}" + (f"\n\nSynonyms:\n{syn_text}" if syn_text else "")
    chip.setToolTip(tooltip)
    chip.setAccessibleDescription(
        f"Synonyms: {syn_text}" if syn_text else "Tag chip")

    return chip
