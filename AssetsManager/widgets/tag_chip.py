"""Shared tag chip widget creation."""
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, QSize
from AssetsManager.core import icons, themes
from AssetsManager.core.color_utils import contrast_on, darken, lighten
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


def _contrast_text(color: str) -> str:
    """Return black or white text for readability on a tag-color background."""
    return contrast_on(color)


def tag_color_from(store, tag: str) -> str | None:
    """Best-effort per-tag color lookup for a store that may lack metadata.

    Legacy/fake stores implement the core tag methods only; this returns
    ``None`` when ``get_tag_metadata`` is absent, raises, or yields a
    non-dict, so chip callers never crash on a metadata-less store.
    """
    getter = getattr(store, "get_tag_metadata", None)
    if not callable(getter):
        return None
    try:
        meta = getter(tag)
    except Exception:
        return None
    if not isinstance(meta, dict):
        return None
    color = meta.get("color")
    return color if isinstance(color, str) and color else None


def create_tag_chip(tag: str, on_remove=None, parent=None, color: str | None = None) -> QWidget:
    """Create a styled tag chip widget.

    Args:
        tag: The tag name to display.
        on_remove: Callback when the X button is clicked (receives tag name).
        parent: Parent widget.
        color: Optional per-tag color (hex); falls back to the theme accent
            when empty so tags with a stored color are visually distinct.

    Returns:
        A QWidget containing the tag chip.
    """
    sk = StyleKit.from_theme(themes, px=scaled_px, pt=scaled_pt)
    background = color or sk.token("accent")
    if color:
        label_color = _contrast_text(color)
        close_tint = label_color
    else:
        label_color = sk.token("on_accent")
        close_tint = "icon_on_accent"
    chip = QWidget(parent)
    chip.setObjectName("TagChip")
    chip.setAccessibleName(f"Tag: {tag}")
    chip.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    hover_background = (
        lighten(background, 1.08) if themes.is_dark() else darken(background, 0.92)
    )
    chip.setStyleSheet(
        f"QWidget#TagChip {{ background: {background}; "
        f"border: 1px solid transparent; border-radius: {sk.px(6)}px; }}"
        f"QWidget#TagChip:hover {{ border-color: {label_color}; background: {hover_background}; }}"
        f"QWidget#TagChip:focus {{ border: 1px solid {label_color}; }}")
    layout = QHBoxLayout(chip)
    layout.setContentsMargins(scaled_px(6), scaled_px(2), scaled_px(4), scaled_px(2))
    layout.setSpacing(scaled_px(2))

    name = QLabel(tag)
    name.setObjectName("TagChipLabel")
    name.setStyleSheet(
        f"color: {label_color}; font-size: {scaled_pt(11)}px; "
        "background: transparent;")
    layout.addWidget(name)

    if on_remove:
        close_btn = QPushButton()
        close_btn.setObjectName("TagChipClose")
        close_btn.setIcon(
            icons.icon("close", color=close_tint, size=scaled_px(14)))
        close_btn.setIconSize(QSize(scaled_px(14), scaled_px(14)))
        close_btn.setAccessibleName(f"Remove tag: {tag}")
        close_btn.setAccessibleDescription(
            f"Removes the {tag} tag from this item")
        close_btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        close_btn.setFixedSize(scaled_px(20), scaled_px(20))
        close_btn.setFlat(True)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            f"QPushButton#TagChipClose {{ color: {label_color}; padding: 0; "
            f"background: transparent; border: 1px solid transparent; "
            f"border-radius: {scaled_px(3)}px; }}"
            f"QPushButton#TagChipClose:hover {{ border-color: {label_color}; }}"
            f"QPushButton#TagChipClose:focus {{ border: 1px solid {label_color}; "
            f"background: {background}; }}")
        close_btn.setToolTip(f"Remove tag: {tag}")
        close_btn.clicked.connect(lambda checked, tg=tag: on_remove(tg))
        layout.addWidget(close_btn)

    syn_text = _synonyms_text_for(tag)
    tooltip = f"Tag: {tag}" + (f"\n\nSynonyms:\n{syn_text}" if syn_text else "")
    chip.setToolTip(tooltip)
    chip.setAccessibleDescription(
        f"Synonyms: {syn_text}" if syn_text else "Tag chip")

    return chip
