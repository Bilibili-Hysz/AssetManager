"""Bounded, root-confined source traversal for LAN ZIP downloads.

The scanner is deliberately shared by ZIP estimation and ZIP creation.  It
does not build a list of directory entries: each ``scandir`` iterator stays
open only for the part of the depth-first traversal that needs it and is
closed in a ``finally`` block when iteration finishes or is interrupted.
"""
from __future__ import annotations

import logging
import os
import posixpath
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Generator

from AssetsManager.lan.path_guard import PathGuardError, assert_under_root

_log = logging.getLogger(__name__)

MAX_ZIP_MEMBERS = 10_000
MAX_ZIP_SCAN_ENTRIES = 100_000
MAX_ZIP_DIRECTORY_DEPTH = 64
MAX_ZIP_SOURCE_BYTES = 500 * 1024 * 1024

# Windows' FILE_ATTRIBUTE_REPARSE_POINT. Reading this attribute from
# ``stat_result`` is harmless on other platforms,
# where the attribute is absent.
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


class ZipLimitExceeded(ValueError):
    """A ZIP source or output resource budget was exceeded."""


@dataclass
class _ScanState:
    scan_entries: int = 0
    members: int = 0
    source_bytes: int = 0

    def account_entry(self) -> None:
        self.scan_entries += 1
        if self.scan_entries > MAX_ZIP_SCAN_ENTRIES:
            raise ZipLimitExceeded(
                f"ZIP scan exceeds {MAX_ZIP_SCAN_ENTRIES} entries"
            )

    def account_member(self, size: int, source_limit: int) -> None:
        self.members += 1
        if self.members > MAX_ZIP_MEMBERS:
            raise ZipLimitExceeded(
                f"ZIP contains more than {MAX_ZIP_MEMBERS} members"
            )
        if size < 0:
            raise OSError("negative ZIP source size")
        self.source_bytes += size
        if self.source_bytes > source_limit:
            raise ZipLimitExceeded(
                f"ZIP source exceeds {source_limit} bytes"
            )


def _stat_is_reparse(info: os.stat_result) -> bool:
    return bool(
        stat.S_ISLNK(info.st_mode)
        or getattr(info, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT
    )


def _entry_info(entry: os.DirEntry[str]) -> os.stat_result:
    """Return no-follow metadata and surface scan errors to the caller."""
    return entry.stat(follow_symlinks=False)


def _entry_is_hidden(entry: os.DirEntry[str]) -> bool:
    # Preserve the established dot-name contract. Native Windows hidden
    # attributes do not change which otherwise eligible assets are exported.
    return entry.name.startswith(".")


def _entry_is_link(entry: os.DirEntry[str], info: os.stat_result) -> bool:
    """Detect symlinks, junctions, and other Windows reparse points.

    Python versions that expose ``DirEntry.is_junction`` get an explicit
    check.  The stat attribute check covers junctions on versions where that
    method is unavailable, and avoids ever descending into a reparse point.
    """
    if _stat_is_reparse(info):
        return True
    is_junction = getattr(entry, "is_junction", None)
    if callable(is_junction):
        try:
            if is_junction():
                return True
        except OSError:
            raise
    try:
        return bool(entry.is_symlink())
    except OSError:
        raise


def _archive_join(prefix: str, relative: str | Path) -> str:
    """Build a ZIP-internal path with portable forward separators."""
    base = str(prefix).replace("\\", "/")
    child = str(relative).replace("\\", "/")
    return posixpath.join(base, child)


def _assert_in_root(root: Path, path: Path) -> bool:
    """Return false for a raced link or an entry outside the archive root."""
    try:
        assert_under_root(root, path)
    except (PathGuardError, ValueError, OSError):
        return False
    return True


def _close_scandir(iterator: object) -> None:
    close = getattr(iterator, "close", None)
    if close is not None:
        close()


def _scan_directory(
    root: Path,
    directory: Path,
    archive_prefix: str,
    depth: int,
    state: _ScanState,
    source_limit: int,
    check_cancelled: Callable[[], None] | None,
) -> Generator[tuple[Path, Path, str], None, None]:
    """Yield regular files beneath one directory using a streaming DFS."""
    info = os.lstat(directory)
    if _stat_is_reparse(info) or not stat.S_ISDIR(info.st_mode):
        raise OSError(f"ZIP directory changed while scanning: {directory}")
    entries = os.scandir(directory)
    try:
        for entry in entries:
            if check_cancelled is not None:
                check_cancelled()
            state.account_entry()
            info = _entry_info(entry)

            # Every entry is accounted for before filtering.  This keeps
            # hidden and linked entries from becoming a cheap way around the
            # scan budget, while the link check happens before any descent.
            if _entry_is_hidden(entry) or _entry_is_link(entry, info):
                continue

            child = Path(entry.path)
            if stat.S_ISDIR(info.st_mode):
                child_depth = depth + 1
                if child_depth > MAX_ZIP_DIRECTORY_DEPTH:
                    raise ZipLimitExceeded(
                        f"ZIP directory depth exceeds {MAX_ZIP_DIRECTORY_DEPTH}"
                    )
                if not _assert_in_root(root, child):
                    _log.warning("Skipping ZIP entry outside archive root: %s", child)
                    continue
                yield from _scan_directory(
                    root,
                    child,
                    _archive_join(archive_prefix, entry.name),
                    child_depth,
                    state,
                    source_limit,
                    check_cancelled,
                )
                continue

            if not stat.S_ISREG(info.st_mode):
                continue
            if not _assert_in_root(root, child):
                _log.warning("Skipping ZIP entry outside archive root: %s", child)
                continue

            size = info.st_size
            state.account_member(size, source_limit)
            relative = entry.name
            yield root, child, _archive_join(archive_prefix, relative)
    finally:
        # ``scandir`` keeps an OS handle open.  Closing in finally is needed
        # both for normal completion and for generator.close() on cancellation.
        _close_scandir(entries)


def _target_stat(target: Path) -> os.stat_result:
    try:
        return os.lstat(target)
    except OSError:
        raise


def _target_is_link(info: os.stat_result) -> bool:
    return _stat_is_reparse(info)


def scan_zip_sources(
    targets: list[tuple[Path, str | None]],
    *,
    source_limit: int | None = None,
    check_cancelled: Callable[[], None] | None = None,
) -> Generator[tuple[Path, Path, str], None, None]:
    """Yield ``(root, path, archive_name)`` for bounded ZIP source members.

    Directory entries are streamed from ``os.scandir`` and budgets are
    cumulative across all targets.  Hidden entries and links consume scan
    entries but are skipped; path escapes are likewise skipped after a
    containment check.  Filesystem errors propagate so callers cannot turn a
    partial traversal into a successful archive.

    ``source_limit`` is an internal compatibility hook used by the builder so
    a monkeypatched LAN read budget applies to its scan as well.  The public
    default remains :data:`MAX_ZIP_SOURCE_BYTES`.
    """
    if source_limit is None:
        source_limit = MAX_ZIP_SOURCE_BYTES
    if source_limit < 0:
        raise ValueError("source_limit must be non-negative")

    state = _ScanState()
    for target, archive_name in targets:
        if check_cancelled is not None:
            check_cancelled()
        state.account_entry()
        target = Path(target)
        info = _target_stat(target)
        if _target_is_link(info):
            raise OSError(f"ZIP source is a link or reparse point: {target}")

        if stat.S_ISREG(info.st_mode):
            root = target.parent.resolve()
            if not _assert_in_root(root, target):
                raise OSError(f"ZIP source escapes its root: {target}")
            size = info.st_size
            state.account_member(size, source_limit)
            yield root, target, archive_name if archive_name is not None else target.name
            continue

        if stat.S_ISDIR(info.st_mode):
            root = target.resolve()
            if not _assert_in_root(root, target):
                raise OSError(f"ZIP source escapes its root: {target}")
            prefix = archive_name if archive_name is not None else target.name
            yield from _scan_directory(
                root, target, str(prefix), 0, state, source_limit, check_cancelled
            )
            continue

        raise OSError(f"ZIP source unavailable: {target}")


def estimate_zip_source_bytes(targets: list[tuple[Path, str | None]]) -> int:
    """Estimate total regular-file bytes using the exact ZIP traversal rules."""
    total = 0
    sources = scan_zip_sources(targets)
    try:
        for _root, path, _archive_name in sources:
            try:
                info = os.stat(path, follow_symlinks=False)
            except OSError:
                raise
            if _stat_is_reparse(info) or not stat.S_ISREG(info.st_mode):
                raise OSError(f"ZIP source changed while estimating: {path}")
            total += info.st_size
            # The scanner already accounts for the admission-time sizes; the
            # second check covers growth between traversal and this estimate.
            if total > MAX_ZIP_SOURCE_BYTES:
                raise ZipLimitExceeded(
                    f"ZIP source exceeds {MAX_ZIP_SOURCE_BYTES} bytes"
                )
    finally:
        sources.close()
    return total


__all__ = [
    "MAX_ZIP_DIRECTORY_DEPTH",
    "MAX_ZIP_MEMBERS",
    "MAX_ZIP_SCAN_ENTRIES",
    "MAX_ZIP_SOURCE_BYTES",
    "ZipLimitExceeded",
    "estimate_zip_source_bytes",
    "scan_zip_sources",
]
