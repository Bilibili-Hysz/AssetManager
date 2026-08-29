"""Shared sort/filter/category rules for desktop and LAN browsing."""

import logging
import os
import re
from collections.abc import Sequence
from pathlib import Path
from threading import RLock
from typing import Callable, TypeVar, overload

from AssetsManager.domain.asset import IMAGE_EXTS, category_for_extension


_log = logging.getLogger(__name__)
_category_registry_lock = RLock()
_category_registry_handlers: list[Callable[[], None]] = []


class CategoryRegistrySubscription:
    """Idempotent handle for category-registry change notifications."""

    def __init__(self, handler: Callable[[], None]):
        self._handler = handler
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with _category_registry_lock:
            if self._handler in _category_registry_handlers:
                _category_registry_handlers.remove(self._handler)


def subscribe_category_registry_changed(
    handler: Callable[[], None],
) -> CategoryRegistrySubscription:
    """Subscribe to complete category-registry publications."""
    with _category_registry_lock:
        _category_registry_handlers.append(handler)
    return CategoryRegistrySubscription(handler)


def _publish_category_registry_changed() -> None:
    with _category_registry_lock:
        handlers = tuple(_category_registry_handlers)
    for handler in handlers:
        try:
            handler()
        except Exception:
            _log.exception("Category registry change handler failed")


class CategoryLabelRegistry(list[tuple[str, str]]):
    """List-compatible labels with snapshot iteration during registry rebuilds."""

    def __iter__(self):
        with _category_registry_lock:
            return iter(tuple(super().__iter__()))

    def snapshot(self) -> tuple[tuple[str, str], ...]:
        with _category_registry_lock:
            return tuple(super().__iter__())


# ── Category extension sets ───────────────────────────────────────

_T = TypeVar("_T")

class CategoryExtensionRegistry(dict[str, frozenset[str]]):
    """Mutable category registry whose built-in entries can be restored."""

    def __init__(self, categories: dict[str, set[str] | frozenset[str]], labels):
        super().__init__({key: frozenset(extensions) for key, extensions in categories.items()})
        self._builtin_categories = {
            key: frozenset(extensions) for key, extensions in categories.items()
        }
        self._builtin_labels = list(labels)

    def __contains__(self, key):
        with _category_registry_lock:
            return super().__contains__(key)

    def __getitem__(self, key):
        with _category_registry_lock:
            return super().__getitem__(key)

    def __iter__(self):
        with _category_registry_lock:
            return iter(tuple(super().__iter__()))

    @overload
    def get(self, key: str) -> frozenset[str] | None: ...
    @overload
    def get(self, key: str, default: frozenset[str] | _T) -> frozenset[str] | _T: ...
    def get(
        self, key: str, default: frozenset[str] | _T | None = None
    ) -> frozenset[str] | _T | None:
        with _category_registry_lock:
            return super().get(key, default)

    def items(self):
        with _category_registry_lock:
            return tuple(super().items())

    def keys(self):
        with _category_registry_lock:
            return tuple(super().keys())

    def values(self):
        with _category_registry_lock:
            return tuple(super().values())

    def snapshot(self) -> dict[str, frozenset[str]]:
        with _category_registry_lock:
            return dict(super().items())

    def rebuild(self, contributions, category_map: dict[str, str], base_map=None) -> None:
        """Atomically replace plugin state while preserving public identities."""
        with _category_registry_lock:
            next_categories = dict(self._builtin_categories)
            next_category_map = dict(base_map if base_map is not None else _BUILTIN_CATEGORY_MAP)
            labels = list(self._builtin_labels)
            occupied_extensions = set(next_category_map)
            builtin_keys = set(self._builtin_categories)
            latest_by_key: dict[str, tuple[str, str, frozenset[str], str]] = {}
            for key, label, extensions, owner in contributions:
                normalized_key = str(key or "").strip()
                normalized_extensions = frozenset(
                    str(extension).strip().lower()
                    for extension in extensions
                    if str(extension).strip()
                )
                if normalized_key and normalized_key not in builtin_keys and normalized_extensions:
                    # Keep the latest contribution for a plugin-owned key. The
                    # contribution list remains the ownership stack, so removing
                    # that plugin exposes the previous entry on the next rebuild.
                    latest_by_key[normalized_key] = (
                        normalized_key, str(label), normalized_extensions, str(owner),
                    )

            used_labels = {label for _key, label in labels}
            for key, label, extensions, _owner in latest_by_key.values():
                # Built-in extensions remain authoritative. Plugin labels must
                # remain unique so legacy display-label callers cannot resolve
                # a built-in or another plugin category incorrectly.
                if label in used_labels:
                    continue
                available = extensions - occupied_extensions
                if not available:
                    continue
                next_categories[key] = frozenset(available)
                next_category_map.update({extension: key for extension in available})
                occupied_extensions.update(available)
                labels.append((key, label))
                used_labels.add(label)

            # Publish each public registry only after all next-state structures
            # are complete. LiveCategoryMap preserves its imported dict identity
            # while swapping an immutable read snapshot in one operation.
            self.clear()
            self.update(next_categories)
            publish = getattr(category_map, "publish", None)
            if callable(publish):
                publish(next_category_map)
            else:
                # Compatibility for test/application providers that expose a
                # plain dict. The application CATEGORY_MAP uses publish().
                category_map.clear()
                category_map.update(next_category_map)
            FILTER_CATEGORY_LABELS[:] = labels
            FILTER_CATEGORIES.clear()
            for key, label in labels:
                FILTER_CATEGORIES[label] = self[key]
        _publish_category_registry_changed()


_BUILTIN_CATEGORY_MAP: dict[str, str] = {}
for _key, _extensions in {
    "images": IMAGE_EXTS,
    "models": {".blend", ".fbx", ".obj", ".gltf", ".glb", ".max", ".ma", ".mb", ".3ds", ".stl"},
    "videos": {".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv"},
    "documents": {".txt", ".pdf", ".docx", ".xlsx", ".pptx", ".md", ".json", ".py", ".xml"},
    "archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"},
}.items():
    _BUILTIN_CATEGORY_MAP.update({extension: _key for extension in _extensions})

FILTER_CATEGORY_EXTS: CategoryExtensionRegistry = CategoryExtensionRegistry(
    {
        "all": set(),
        "images": IMAGE_EXTS,
        "models": {".blend", ".fbx", ".obj", ".gltf", ".glb", ".max", ".ma", ".mb", ".3ds", ".stl"},
        "videos": {".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv"},
        "documents": {".txt", ".pdf", ".docx", ".xlsx", ".pptx", ".md", ".json", ".py", ".xml"},
        "archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"},
    },
    [
        ("all", "All"),
        ("images", "Images"),
        ("models", "3D Models"),
        ("videos", "Videos"),
        ("documents", "Documents"),
        ("archives", "Archives"),
    ],
)

FILTER_CATEGORY_LABELS: CategoryLabelRegistry = CategoryLabelRegistry(
    FILTER_CATEGORY_EXTS._builtin_labels,
)
FILTER_CATEGORIES: dict[str, frozenset[str]] = {
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


def category_registry_snapshot() -> tuple[dict[str, frozenset[str]], tuple[tuple[str, str], ...]]:
    """Return categories and labels from one registry generation."""
    with _category_registry_lock:
        return FILTER_CATEGORY_EXTS.snapshot(), FILTER_CATEGORY_LABELS.snapshot()


def category_labels() -> list[tuple[str, str]]:
    """Return a consistent snapshot of current filter categories."""
    return list(category_registry_snapshot()[1])


def normalize_sort_key(key: str) -> str:
    """Normalize sort key from display name to canonical form."""
    return _SORT_KEY_MAP.get(key, key or "name")


def normalize_filter_category(category: str) -> str:
    """Normalize canonical and uniquely registered display category names."""
    value = str(category or "").strip()
    if not value:
        return "all"
    with _category_registry_lock:
        if value in FILTER_CATEGORY_EXTS:
            return value
        builtin = _CATEGORY_MAP.get(value)
        if builtin is not None:
            return builtin
        matching_keys = [key for key, label in FILTER_CATEGORY_LABELS if label == value]
    return matching_keys[0] if len(matching_keys) == 1 else value


# ── Category matching ─────────────────────────────────────────────


def extension_matches_category(ext: str, category: str) -> bool:
    """Check if a file extension belongs to the given category."""
    cat = normalize_filter_category(category)
    if cat == "all":
        return True
    exts = FILTER_CATEGORY_EXTS.get(cat, set())
    return ext.lower() in exts


# ── File helpers ─────────────────────────────────────────────────

def find_first_image(dir_path: Path, limit: int | None = None) -> Path | None:
    """Return the path of the first image file in a directory, or None.

    ``limit`` bounds the number of directory entries scanned; ``None`` scans
    the whole directory.  Scans in filesystem order (not sorted).
    """
    try:
        with os.scandir(dir_path) as entries:
            for i, entry in enumerate(entries):
                if limit is not None and i >= limit:
                    break
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


def matches_exclude(name: str, patterns: Sequence[str]) -> bool:
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


def matches_structured(
    name: str,
    is_dir: bool,
    *,
    size: int,
    mtime: float,
    size_min: int | None = None,
    size_max: int | None = None,
    mtime_after: float | None = None,
    mtime_before: float | None = None,
    extensions: Sequence[str] | None = None,
) -> bool:
    """Structured extension/size/mtime predicates (desktop advanced filter).

    Mirrors the assets-index semantics of
    ``AssetIndexRepository.search_structured``: bounds are inclusive,
    ``mtime`` is epoch seconds and ``size`` is bytes, and extension
    candidates are normalized to lowercase with a leading dot. Directories
    always pass so navigation never disappears while a structured filter is
    active (same contract as the include_types/category checks above).
    """
    if is_dir:
        return True
    if extensions:
        normalized = {
            "." + str(candidate).strip().lower().lstrip(".")
            for candidate in extensions
            if str(candidate).strip().lstrip(".")
        }
        if normalized and os.path.splitext(name)[1].lower() not in normalized:
            return False
    if size_min is not None and size < size_min:
        return False
    if size_max is not None and size > size_max:
        return False
    if mtime_after is not None and mtime < mtime_after:
        return False
    if mtime_before is not None and mtime > mtime_before:
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
