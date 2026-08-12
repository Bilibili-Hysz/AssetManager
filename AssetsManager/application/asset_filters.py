"""Shared sort/filter/category rules for desktop and LAN browsing."""

import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Callable

from AssetsManager.domain.asset import IMAGE_EXTS, category_for_extension

# ── Category extension sets ───────────────────────────────────────

FILTER_CATEGORY_EXTS: dict[str, set[str] | frozenset[str]] = {
    "all":         set(),
    "images":      IMAGE_EXTS,
    "models":      {".blend", ".fbx", ".obj", ".gltf", ".glb", ".max", ".ma", ".mb", ".3ds", ".stl"},
    "videos":      {".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv"},
    "documents":   {".txt", ".pdf", ".docx", ".xlsx", ".pptx", ".md", ".json", ".py", ".xml"},
    "archives":    {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"},
}

FILTER_CATEGORY_LABELS: list[tuple[str, str]] = [
    ("all", "All"),
    ("images", "Images"),
    ("models", "3D Models"),
    ("videos", "Videos"),
    ("documents", "Documents"),
    ("archives", "Archives"),
]

FILTER_CATEGORIES: dict[str, set[str] | frozenset[str]] = {
    label: FILTER_CATEGORY_EXTS[key] for key, label in FILTER_CATEGORY_LABELS
}

# ── Natural sort ──────────────────────────────────────────────────

_natural_split = re.compile(r'(\d+)')


def natural_key(s: str) -> list:
    """Natural sort key: 'file2' < 'file10'."""
    return [(int(x) if x.isdigit() else x.lower()) for x in _natural_split.split(s)]


# ── Normalization ─────────────────────────────────────────────────

_SORT_KEY_MAP: dict[str, str] = {
    "Name": "name",
    "Date": "date",
    "Size": "size",
    "Type": "type",
}

_CATEGORY_MAP: dict[str, str] = {
    "All": "all",
    "Images": "images",
    "3D Models": "models",
    "Videos": "videos",
    "Documents": "documents",
    "Archives": "archives",
}


def normalize_sort_key(key: str) -> str:
    """Normalize sort key from display name to canonical form."""
    return _SORT_KEY_MAP.get(key, key or "name")


def normalize_filter_category(category: str) -> str:
    """Normalize filter category from display name to canonical form."""
    return _CATEGORY_MAP.get(category, category or "all")


# ── Category matching ─────────────────────────────────────────────


def extension_matches_category(ext: str, category: str) -> bool:
    """Check if a file extension belongs to the given category."""
    cat = normalize_filter_category(category)
    if cat == "all":
        return True
    exts = FILTER_CATEGORY_EXTS.get(cat, set())
    return ext in exts


# ── File helpers ─────────────────────────────────────────────────

def find_first_image(dir_path: Path) -> Path | None:
    """Return the path of the first image file in a directory, or None."""
    try:
        with os.scandir(dir_path) as entries:
            for entry in entries:
                if entry.is_file() and Path(entry.name).suffix.lower() in IMAGE_EXTS:
                    return Path(entry.path)
        return None
    except OSError:
        return None


# ── Hidden files ─────────────────────────────────────────────────

def is_hidden(name: str) -> bool:
    """Check if a name represents a hidden file/directory."""
    return name.startswith(".")


def matches_search(name: str, search: str) -> bool:
    """Check if a name matches a search query (case-insensitive substring).

    The function handles case folding itself, so callers may pass the
    raw query — the desktop file list passes typed text directly, while
    the LAN service keeps its defensive pre-lowercase as a no-op.
    """
    if not search:
        return True
    return search.lower() in name.lower()


def matches_exclude(name: str, patterns: list[str]) -> bool:
    """True when the entry name matches any exclude pattern.

    Shared by the LAN AssetService and the desktop file list so both
    surfaces honour the same exclusion semantics (fnmatch, with a
    leading-dot-insensitive second pass).
    """
    import fnmatch

    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
        if fnmatch.fnmatch(name.lstrip("."), pattern.lstrip(".")):
            return True
    return False


# ── Entry acceptance (shared filtering pipeline) ──────────────────

def filters_accept(
    name: str,
    is_dir: bool,
    *,
    show_hidden: bool = True,
    exclude_patterns: Sequence[str] = (),
    search: str = "",
    filter_category: str = "all",
    include_types: Sequence[str] | None = None,
    max_depth: int = 0,
    current_depth: int = 0,
) -> bool:
    """Single accept-predicate for the desktop file list and LAN browsing.

    Both surfaces run exactly the same pipeline: hidden → exclude →
    include_types → max_depth → search → category. Directories always pass
    the include_types and category checks so navigation never disappears
    while filtering by file type.
    """
    if not show_hidden and is_hidden(name):
        return False
    if exclude_patterns and matches_exclude(name, exclude_patterns):
        return False
    ext = os.path.splitext(name)[1].lower()
    if include_types and not is_dir and category_for_extension(ext) not in include_types:
        return False
    if max_depth > 0 and is_dir and current_depth + 1 > max_depth:
        return False
    if not matches_search(name, search):
        return False
    if filter_category != "all" and not is_dir and not extension_matches_category(ext, filter_category):
        return False
    return True


# ── Sort helpers ──────────────────────────────────────────────────

def sort_key_for_entry(
    name: str,
    is_dir: bool,
    modified: float,
    size: int,
    ext: str,
    sort_by: str,
    natural_sort: Callable[[str], list] | None = None,
) -> tuple:
    """Build a sort key tuple for a file/directory entry.

    Always sorts directories first, then by the chosen key, then by name.
    """
    if natural_sort is None:
        natural_sort = natural_key
    k = normalize_sort_key(sort_by)
    return (
        not is_dir,
        (natural_sort(name) if k == "name" else
         -modified if k == "date" else
         -size if k == "size" else
         ext if ext else ""),
        natural_sort(name),
    )
