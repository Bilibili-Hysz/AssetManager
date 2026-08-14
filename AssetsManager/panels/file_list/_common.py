"""Shared constants and helpers for the file_list package."""
from PySide6.QtGui import QColor
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
# These are intentionally distinct from theme tokens — they identify
# file categories, not UI chrome. Do NOT replace with theme colors.

CATEGORY_BADGE_COLORS: dict[str, QColor] = {
    "blend_library":  QColor("#2f7aa3"),
    "model_pack":     QColor("#3f8c69"),
    "texture_pack":   QColor("#8a6d3b"),
    "archive_pack":   QColor("#6f5a92"),
    "bundled_assets": QColor("#7c6a39"),
    "default":        QColor("#49555d"),
}

# Extension → badge category mapping
_EXT_BADGE_MAP: dict[str, str] = {}
for _ext in FILTER_CATEGORY_EXTS.get("images", set()):
    _EXT_BADGE_MAP[_ext] = "texture_pack"
for _ext in FILTER_CATEGORY_EXTS.get("models", set()):
    _EXT_BADGE_MAP[_ext] = "model_pack"
for _ext in FILTER_CATEGORY_EXTS.get("archives", set()):
    _EXT_BADGE_MAP[_ext] = "archive_pack"


def badge_color_for_extension(ext: str) -> QColor:
    """Return the category badge color for a file extension."""
    cat = _EXT_BADGE_MAP.get(ext.lower(), "default")
    return CATEGORY_BADGE_COLORS.get(cat, CATEGORY_BADGE_COLORS["default"])


def badge_label_for_extension(ext: str) -> str:
    """Return a short category label for a file extension."""
    cat = _EXT_BADGE_MAP.get(ext.lower(), "default")
    labels = {
        "blend_library": "BLEND",
        "model_pack": "3D",
        "texture_pack": "TEX",
        "archive_pack": "ZIP",
        "bundled_assets": "ASSET",
        "default": "FILE",
    }
    return labels.get(cat, "FILE")
