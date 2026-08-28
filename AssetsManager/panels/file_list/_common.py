"""Shared constants and helpers for the file_list package."""
from typing import cast

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

class ExtensionCategoryLookup(dict[str, str]):
    """Live extension lookup backed by the current filter category registry."""

    def _current(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for category, extensions in FILTER_CATEGORY_EXTS.items():
            for extension in extensions:
                mapping[extension.lower()] = category
        return mapping

    def get(self, extension, default=None):
        return self._current().get(str(extension or "").lower(), default)

    def __getitem__(self, extension):
        return self._current()[str(extension).lower()]

    def __contains__(self, extension):
        return str(extension or "").lower() in self._current()

    def __iter__(self):
        return iter(self._current())

    def __len__(self):
        return len(self._current())

    def keys(self):
        return self._current().keys()

    def items(self):
        return self._current().items()

    def values(self):
        return self._current().values()

    def copy(self):
        return self._current().copy()

    def __repr__(self):
        return repr(self._current())


EXT_TO_CATEGORY: dict[str, str] = ExtensionCategoryLookup()


def refresh_extension_categories() -> None:
    """Compatibility hook retained for callers that expect an explicit refresh."""
    return None


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
# Registry.get is typed Optional (its declared default is None); the explicit
# set() default guarantees an iterable at runtime, so cast for the checker.
for _ext in cast("frozenset[str]", FILTER_CATEGORY_EXTS.get("images", set())):
    _EXT_BADGE_MAP[_ext] = "texture_pack"
for _ext in cast("frozenset[str]", FILTER_CATEGORY_EXTS.get("models", set())):
    _EXT_BADGE_MAP[_ext] = "model_pack"
for _ext in cast("frozenset[str]", FILTER_CATEGORY_EXTS.get("videos", set())):
    _EXT_BADGE_MAP[_ext] = "video"
for _ext in cast("frozenset[str]", FILTER_CATEGORY_EXTS.get("archives", set())):
    _EXT_BADGE_MAP[_ext] = "archive_pack"


def _badge_category(ext: str) -> str:
    normalized = str(ext or "").lower()
    category = EXT_TO_CATEGORY.get(normalized)
    if category == "images":
        return "texture_pack"
    if category == "models" or category == "3d":
        return "model_pack"
    if category == "videos":
        return "video"
    if category == "archives":
        return "archive_pack"
    return _EXT_BADGE_MAP.get(normalized, "default")


def badge_color_for_extension(ext: str) -> QColor:
    """Return the theme-aware category badge color for a file extension."""
    cat = _badge_category(ext)
    token = _CATEGORY_TOKEN_BY_BADGE[cat]
    return QColor(themes.color(token))


def badge_label_for_extension(ext: str) -> str:
    """Return a short category label for a file extension."""
    cat = _badge_category(ext)
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
