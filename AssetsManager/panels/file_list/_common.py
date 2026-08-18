"""Shared constants and helpers for the file_list package."""
from PySide6.QtGui import QColor
from AssetsManager.core import themes
from AssetsManager.core.constants import (  # noqa: F401
    IMAGE_EXTS as IMAGE_EXTS,
    VIDEO_EXTS as VIDEO_EXTS,
)
from AssetsManager.application.asset_filters import (  # noqa: F401
    FILTER_CATEGORY_EXTS,
    FILTER_CATEGORY_LABELS,
    FILTER_CATEGORIES,
    natural_key as natural_key,
)
ZOOM_PRESETS = [48, 72, 96, 128]

# Flat extension → category mapping (O(1) lookup instead of O(n) iteration)
EXT_TO_CATEGORY: dict[str, str] = {}
for _cat, _exts in FILTER_CATEGORY_EXTS.items():
    for _ext in _exts:
        EXT_TO_CATEGORY[_ext] = _cat


# ── Category badge colors ────────────────────────────────────────
# Badge colors resolve through semantic category_* theme tokens (see
# themes._EXTENDED_FALLBACKS) so themes can adapt category identity colors
# to their palette. Merged themes always carry these tokens.
_CATEGORY_TOKEN_BY_BADGE: dict[str, str] = {
    "blend_library": "category_blend",
    "model_pack": "category_model",
    "texture_pack": "category_texture",
    "archive_pack": "category_archive",
    "bundled_assets": "category_bundled",
    "video": "category_video",
    "default": "category_default",
}

# Extension → badge category mapping
_EXT_BADGE_MAP: dict[str, str] = {}
for _ext in FILTER_CATEGORY_EXTS.get("images", set()):
    _EXT_BADGE_MAP[_ext] = "texture_pack"
for _ext in FILTER_CATEGORY_EXTS.get("models", set()):
    _EXT_BADGE_MAP[_ext] = "model_pack"
for _ext in FILTER_CATEGORY_EXTS.get("videos", set()):
    _EXT_BADGE_MAP[_ext] = "video"
for _ext in FILTER_CATEGORY_EXTS.get("archives", set()):
    _EXT_BADGE_MAP[_ext] = "archive_pack"


def badge_color_for_extension(ext: str) -> QColor:
    """Return the theme-aware category badge color for a file extension."""
    cat = _EXT_BADGE_MAP.get(ext.lower(), "default")
    token = _CATEGORY_TOKEN_BY_BADGE[cat]
    return QColor(themes.color(token))


def badge_label_for_extension(ext: str) -> str:
    """Return a short category label for a file extension."""
    cat = _EXT_BADGE_MAP.get(ext.lower(), "default")
    labels = {
        "blend_library": "BLEND",
        "model_pack": "3D",
        "texture_pack": "TEX",
        "archive_pack": "ZIP",
        "bundled_assets": "ASSET",
        "video": "VID",
        "default": "FILE",
    }
    return labels.get(cat, "FILE")
