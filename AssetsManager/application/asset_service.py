"""Asset browsing application service."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from AssetsManager.application.asset_filters import (
    IMAGE_EXTS,
    extension_matches_category,
    is_hidden,
    matches_search,
    sort_key_for_entry,
)
from AssetsManager.domain.asset import category_for_extension
from AssetsManager.core.format_utils import format_size


@dataclass(frozen=True)
class DirectoryListOptions:
    sort_by: str = "name"
    order: str = "asc"
    filter_category: str = "all"
    search: str = ""
    show_hidden: bool = False
    include_types: tuple[str, ...] | None = None
    exclude_patterns: tuple[str, ...] = ()
    max_depth: int = 0
    current_depth: int = 0


@dataclass(frozen=True)
class AssetListItem:
    name: str
    path: str
    type: str
    size: int
    size_fmt: str
    modified: float
    extension: str
    category: str
    absolute_path: Path
    preview_path: Path | None = None
    item_count: int | None = None

    @property
    def is_dir(self) -> bool:
        return self.type == "dir"


@dataclass(frozen=True)
class DirectoryListing:
    current_path: str
    parent_path: str
    items: tuple[AssetListItem, ...]
    total_count: int
    total_size: int
    total_size_fmt: str


class AssetService:
    """Pure file-system browsing operations shared by desktop and LAN."""

    def list_directory(self, library_root: Path, target: Path,
                       options: DirectoryListOptions | None = None) -> DirectoryListing:
        options = options or DirectoryListOptions()
        root = Path(library_root).resolve()
        target = Path(target).resolve()
        rel_path = "" if target == root else os.path.relpath(target, root).replace("\\", "/")

        try:
            entries = list(os.scandir(target))
        except PermissionError:
            raise
        except OSError:
            raise

        search = options.search.lower()
        items: list[AssetListItem] = []
        for entry in entries:
            item = self._entry_to_item(root, entry, options)
            if item is None:
                continue
            if not matches_search(item.name, search):
                continue
            if options.filter_category != "all" and not extension_matches_category(item.extension, options.filter_category):
                continue
            items.append(item)

        items = self._sort(items, options.sort_by, options.order)
        parent = os.path.dirname(rel_path.strip("/")) if rel_path else ""
        total_size = sum(item.size for item in items)
        return DirectoryListing(
            current_path=rel_path.strip("/"),
            parent_path=parent,
            items=tuple(items),
            total_count=len(items),
            total_size=total_size,
            total_size_fmt=format_size(total_size),
        )

    def _entry_to_item(self, root: Path, entry: os.DirEntry,
                       options: DirectoryListOptions) -> AssetListItem | None:
        name = entry.name
        if not options.show_hidden and is_hidden(name):
            return None
        if options.exclude_patterns and matches_exclude(name, options.exclude_patterns):
            return None

        ext = os.path.splitext(name)[1].lower()
        is_dir = entry.is_dir()
        category = "folder" if is_dir else category_for_extension(ext)
        if options.include_types and category != "folder" and category not in options.include_types:
            return None
        if options.max_depth > 0 and is_dir and options.current_depth + 1 > options.max_depth:
            return None

        rel = os.path.relpath(entry.path, root).replace("\\", "/")
        try:
            stat = entry.stat(follow_symlinks=False)
        except OSError:
            modified = 0.0
            size = 0
        else:
            modified = stat.st_mtime
            size = 0 if is_dir else stat.st_size

        preview = None
        item_count = None
        if is_dir:
            # TODO: _scan_dir_summary causes N+1 filesystem scans when listing
            # directories with many subdirectories. Consider lazy evaluation or
            # limiting to visible items only.
            preview, item_count = _scan_dir_summary(Path(entry.path))
        size_fmt = f"{item_count} items" if is_dir and item_count is not None else format_size(size)
        return AssetListItem(
            name=name,
            path=rel,
            type="dir" if is_dir else "file",
            size=size,
            size_fmt=size_fmt,
            modified=modified,
            extension=ext,
            category=category,
            absolute_path=Path(entry.path),
            preview_path=preview,
            item_count=item_count,
        )

    @staticmethod
    def _sort(items: list[AssetListItem], sort_by: str, order: str) -> list[AssetListItem]:
        reverse = order == "desc"
        items.sort(key=lambda x: sort_key_for_entry(
            name=x.name,
            is_dir=x.is_dir,
            modified=x.modified,
            size=x.size,
            ext=x.extension,
            sort_by=sort_by,
        ), reverse=reverse)
        return items


def _scan_dir_summary(dir_path: Path) -> tuple[Path | None, int]:
    """Scan a directory once to get both the first image and item count.

    Returns (preview_path, item_count). This avoids scanning the directory
    twice (once for preview, once for count).
    """
    preview: Path | None = None
    count = 0
    try:
        for entry in os.scandir(dir_path):
            if entry.name.startswith("."):
                continue
            count += 1
            if preview is None and entry.is_file():
                ext = Path(entry.name).suffix.lower()
                if ext in IMAGE_EXTS:
                    preview = Path(entry.path)
    except OSError:
        pass
    return preview, count


def matches_exclude(name: str, patterns: tuple[str, ...]) -> bool:
    import fnmatch
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
        if fnmatch.fnmatch(name.lstrip("."), pattern.lstrip(".")):
            return True
    return False
