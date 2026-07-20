"""Asset browsing application service."""
from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from AssetsManager.application.asset_filters import (
    IMAGE_EXTS,
    extension_matches_category,
    is_hidden,
    matches_search,
    sort_key_for_entry,
)
from AssetsManager.core.directory_cache import DirCacheEntry, DirectoryCache
from AssetsManager.core.performance import PerformanceRecorder
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
    scan_summaries: bool = True


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

    def __init__(
        self,
        directory_cache: DirectoryCache | None = None,
        performance_recorder: PerformanceRecorder | None = None,
        session_token: str | None = None,
    ):
        self._directory_cache = directory_cache
        self._performance_recorder = (
            performance_recorder if performance_recorder is not None and performance_recorder.enabled else None
        )
        self._session_token = session_token

    def list_directory(self, library_root: Path, target: Path,
                       options: DirectoryListOptions | None = None) -> DirectoryListing:
        options = options or DirectoryListOptions()
        started = perf_counter() if self._performance_recorder is not None else None
        try:
            root = Path(library_root).resolve()
            target = Path(target).resolve()
            if not target.is_relative_to(root):
                raise ValueError('target must be under library_root')
            rel_path = "" if target == root else os.path.relpath(target, root).replace("\\", "/")
            entries = list(os.scandir(target))
            search = options.search.lower()
            items: list[AssetListItem] = []
            summary_cache_writes: list[tuple[str, int, str | None, float]] = []
            summary_cache_entries = self._summary_cache_entries(entries, options)
            cache_lookup_complete = self._directory_cache is not None and options.scan_summaries
            for entry in entries:
                item = self._entry_to_item(
                    root, entry, options, summary_cache_writes, summary_cache_entries, cache_lookup_complete,
                )
                if item is None:
                    continue
                if not matches_search(item.name, search):
                    continue
                if options.filter_category != "all" and not extension_matches_category(item.extension, options.filter_category):
                    continue
                items.append(item)

            if summary_cache_writes and self._directory_cache is not None:
                self._directory_cache.set_batch(summary_cache_writes)

            items = self._sort(items, options.sort_by, options.order)
            parent = os.path.dirname(rel_path.strip("/")) if rel_path else ""
            total_size = sum(item.size for item in items)
            listing = DirectoryListing(
                current_path=rel_path.strip("/"),
                parent_path=parent,
                items=tuple(items),
                total_count=len(items),
                total_size=total_size,
                total_size_fmt=format_size(total_size),
            )
        except Exception:
            self._record_listing_performance(Path(target), options, started, None)
            raise
        self._record_listing_performance(target, options, started, listing)
        return listing

    def summarize_directories(self, directories: list[Path]) -> dict[str, tuple[Path | None, int]]:
        """Return cached-or-fresh summaries for a bounded, validated directory set."""
        paths = [str(directory) for directory in directories]
        cached_entries = self._directory_cache.get_batch(paths) if self._directory_cache else {}
        cache_writes: list[tuple[str, int, str | None, float]] = []
        summaries = {
            str(directory): _scan_dir_summary(
                directory,
                cache=self._directory_cache,
                performance_recorder=self._performance_recorder,
                session_token=self._session_token,
                cache_writes=cache_writes,
                cached_entry=cached_entries.get(str(directory)),
                cache_lookup_complete=self._directory_cache is not None,
            )
            for directory in directories
        }
        if cache_writes and self._directory_cache is not None:
            self._directory_cache.set_batch(cache_writes)
        return summaries

    def _entry_to_item(self, root: Path, entry: os.DirEntry,
                       options: DirectoryListOptions,
                       summary_cache_writes: list[tuple[str, int, str | None, float]] | None = None,
                       summary_cache_entries: dict[str, DirCacheEntry] | None = None,
                       cache_lookup_complete: bool = False,
                       ) -> AssetListItem | None:
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
        if is_dir and options.scan_summaries:
            preview, item_count = _scan_dir_summary(
                Path(entry.path),
                cache=self._directory_cache,
                performance_recorder=self._performance_recorder,
                session_token=self._session_token,
                cache_writes=summary_cache_writes,
                cached_entry=summary_cache_entries.get(entry.path) if summary_cache_entries else None,
                cache_lookup_complete=cache_lookup_complete,
            )
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

    def _summary_cache_entries(
        self, entries: list[os.DirEntry], options: DirectoryListOptions,
    ) -> dict[str, DirCacheEntry]:
        if self._directory_cache is None or not options.scan_summaries:
            return {}
        return self._directory_cache.get_batch([entry.path for entry in entries if entry.is_dir()])

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

    def _record_listing_performance(
        self,
        target: Path,
        options: DirectoryListOptions,
        started: float | None,
        listing: DirectoryListing | None,
    ) -> None:
        if self._performance_recorder is None or started is None:
            return
        try:
            self._performance_recorder.record(
                "directory.list",
                (perf_counter() - started) * 1000,
                session_token=self._session_token,
                path=str(target),
                attributes={
                    "outcome": "success" if listing is not None else "error",
                    "item_count": listing.total_count if listing is not None else -1,
                    "scan_summaries": options.scan_summaries,
                },
            )
        except Exception:
            # Observability must not change a completed listing result.
            pass


def _scan_dir_summary(
    dir_path: Path,
    cache: DirectoryCache | None = None,
    performance_recorder: PerformanceRecorder | None = None,
    session_token: str | None = None,
    cache_writes: list[tuple[str, int, str | None, float]] | None = None,
    cached_entry: DirCacheEntry | None = None,
    cache_lookup_complete: bool = False,
) -> tuple[Path | None, int]:
    """Scan a directory once to get both the first image and item count.

    Returns (preview_path, item_count). This avoids scanning the directory
    twice (once for preview, once for count).
    """
    started = perf_counter() if performance_recorder and performance_recorder.enabled else None
    cache_hit = False
    if cache is not None:
        try:
            mtime = dir_path.stat().st_mtime
        except OSError:
            mtime = None
        if mtime is not None:
            entry = cached_entry
            if entry is None and not cache_lookup_complete:
                entry = cache.get(str(dir_path), mtime=mtime)
            if entry is not None and entry.mtime != mtime:
                entry = None
            if entry is not None:
                cache_hit = True
                result = Path(entry.preview_path) if entry.preview_path else None, entry.item_count
                _record_summary_performance(performance_recorder, dir_path, started, cache_hit, session_token)
                return result
    else:
        mtime = None

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

    if cache is not None and mtime is not None:
        cache_entry = (str(dir_path), count, str(preview) if preview else None, mtime)
        if cache_writes is None:
            cache.set(*cache_entry)
        else:
            cache_writes.append(cache_entry)

    _record_summary_performance(performance_recorder, dir_path, started, cache_hit, session_token)
    return preview, count


def _record_summary_performance(
    recorder: PerformanceRecorder | None,
    dir_path: Path,
    started: float | None,
    cache_hit: bool,
    session_token: str | None,
) -> None:
    if recorder is not None and started is not None:
        try:
            recorder.record(
                "directory.summary",
                (perf_counter() - started) * 1000,
                session_token=session_token,
                path=str(dir_path),
                attributes={"cache_hit": cache_hit},
            )
        except Exception:
            # Observability must not change the result of a completed scan.
            pass


def matches_exclude(name: str, patterns: Sequence[str]) -> bool:
    import fnmatch
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
        if fnmatch.fnmatch(name.lstrip("."), pattern.lstrip(".")):
            return True
    return False
