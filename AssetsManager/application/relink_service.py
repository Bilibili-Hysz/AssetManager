"""H2-b broken-link governance: reattach metadata orphaned by external moves.

When a file is moved/renamed outside the app (Explorer, another editor), the
in-app rename fallback (``core.database._migrate_path_metadata_impl``) never
runs and the tags/notes/rating stay behind on the dead path as *metadata
orphans*, while the file reappears on disk as a *newcomer* the index has no
row for. This module closes that gap in three parts:

- :func:`scan` — one read-only directory walk plus read-only SQL that
  reports metadata-bearing lost index rows, unindexed newcomer files, and
  how many plain index rows went missing (diagnostic only). The walk reuses
  the asset-index enumeration semantics (skip dotfiles via
  :func:`AssetsManager.application.asset_filters.is_hidden`, skip
  symlinks/junctions/reparse points via the asset-index service helper) and
  is budgeted like the watcher's ``MAX_DIRECTORIES`` pattern so a huge
  library cannot pin a worker thread indefinitely.
- :func:`suggest_pairs` — the pure pairing pass. Priority 1: same size and
  same mtime (same-volume moves preserve the inode identity the thumbnail
  v2 key already relies on) → high confidence. Priority 2: same name and
  same size (cross-drive/editor-rename scenario, no identity signal) → low
  confidence that must be confirmed row by row. Ambiguous candidates pair
  with nothing.
- :func:`relink` — apply one confirmed pairing: migrate the metadata through
  the same core primitive the in-app move uses and repoint the asset-index
  row, inside one transaction that rolls back the whole pair on failure.

The service never moves, copies, or deletes user files: relinking only
rewrites AssetsManager's own projections (file_tags/file_meta/
library_favorites/asset_derivatives/asset_collection_members/thumbnail_cache
via ``migrate_path_metadata``, plus the ``assets`` index row).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from time import monotonic_ns

from AssetsManager.application.asset_filters import is_hidden
from AssetsManager.application.asset_index_service import _is_link_or_reparse
from AssetsManager.core.database import db_write_lock, migrate_path_metadata
from AssetsManager.repositories.asset_index_repository import AssetIndexRepository

_log = logging.getLogger(__name__)

# Single-scan directory budget, mirroring the watcher's MAX_DIRECTORIES
# pattern: when the walk hits the cap it stops early and flags the report as
# truncated instead of pinning a worker thread on a pathological tree. 50k
# directories is the same bound the resident watcher already accepts per
# round, and a full library rescan walks the whole tree anyway.
MAX_SCAN_DIRECTORIES = 50_000

# The index stores mtime as float epoch seconds, so ns round-trips through
# SQLite REAL lose sub-µs precision. A 1 ms tolerance keeps the same-file
# signal intact while still rejecting any copy (which lands on a different
# timestamp far beyond a millisecond).
_MTIME_MATCH_TOLERANCE_NS = 1_000_000

CONFIDENCE_HIGH = "high"
CONFIDENCE_LOW = "low"


class RelinkTargetMissingError(ValueError):
    """Raised when a relink's new path is not an existing regular file."""


@dataclass(frozen=True)
class LostEntry:
    """One indexed path that vanished from disk.

    ``has_metadata`` mirrors the product rule "only rows carrying user
    metadata count as orphans": a ``file_tags`` row, or a ``file_meta`` row
    with non-empty notes/urls or a non-NULL rating. Rows whose file_meta
    holds only derived size/mtime caches (and pure index rows) are counted
    in :attr:`RelinkReport.missing_index_rows` but are not reported.
    """

    file_path: str
    name: str
    kind: str
    size: int
    mtime: float
    has_tags: bool
    has_meta: bool

    @property
    def has_metadata(self) -> bool:
        return self.has_tags or self.has_meta

    @property
    def mtime_ns(self) -> int:
        return int(round(self.mtime * 1e9))


@dataclass(frozen=True)
class NewcomerEntry:
    """One on-disk regular file the asset index has no row for."""

    file_path: str
    name: str
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class RelinkSuggestion:
    """One pairing of a lost metadata row with a newcomer file."""

    lost: LostEntry
    newcomer: NewcomerEntry
    confidence: str  # CONFIDENCE_HIGH | CONFIDENCE_LOW


@dataclass(frozen=True)
class RelinkReport:
    """Outcome of one broken-link scan.

    ``lost`` contains only metadata-bearing orphans (the actionable set);
    ``missing_index_rows`` counts every vanished row for diagnostics.
    ``truncated`` marks a walk that exhausted its directory budget — the
    newcomer list is then incomplete, while lost-path detection stays exact
    (each candidate is confirmed with an ``os.path.exists`` probe).
    """

    lost: tuple[LostEntry, ...]
    newcomers: tuple[NewcomerEntry, ...]
    suggestions: tuple[RelinkSuggestion, ...]
    missing_index_rows: int
    truncated: bool = False

    @property
    def unpaired_lost(self) -> tuple[LostEntry, ...]:
        """Metadata orphans no suggestion was found for ("无建议" rows)."""
        paired = {suggestion.lost.file_path for suggestion in self.suggestions}
        return tuple(entry for entry in self.lost if entry.file_path not in paired)


def suggest_pairs(
    lost: list[LostEntry] | tuple[LostEntry, ...],
    newcomers: list[NewcomerEntry] | tuple[NewcomerEntry, ...],
    *,
    mtime_tolerance_ns: int = _MTIME_MATCH_TOLERANCE_NS,
) -> list[RelinkSuggestion]:
    """Pair lost metadata rows with newcomer files (pure function).

    Priority 1 pairs on equal size and mtime within *mtime_tolerance_ns*
    (high confidence — the same-volume move identity the thumbnail v2 key
    uses). Priority 2 pairs the remaining rows on equal name and size (low
    confidence). A candidate match is only taken when it is unique against
    the remaining newcomers; ambiguous groups pair with nothing so a wrong
    relink can never be suggested, and each newcomer is claimed at most
    once. Input order only breaks ties — pass sorted iterables for a
    deterministic result.
    """
    by_size: dict[int, list[NewcomerEntry]] = {}
    for newcomer in newcomers:
        by_size.setdefault(newcomer.size, []).append(newcomer)

    def unique(candidates: list[NewcomerEntry]) -> NewcomerEntry | None:
        return candidates[0] if len(candidates) == 1 else None

    used_newcomers: set[str] = set()
    suggestions: list[RelinkSuggestion] = []
    # Pass 1: size + mtime identity (same-volume move / rename).
    for entry in lost:
        candidates = [
            newcomer for newcomer in by_size.get(entry.size, ())
            if newcomer.file_path not in used_newcomers
            and abs(newcomer.mtime_ns - entry.mtime_ns) <= mtime_tolerance_ns
        ]
        match = unique(candidates)
        if match is not None:
            suggestions.append(RelinkSuggestion(entry, match, CONFIDENCE_HIGH))
            used_newcomers.add(match.file_path)
    paired_lost = {suggestion.lost.file_path for suggestion in suggestions}
    # Pass 2: same name + same size (cross-drive move / editor rename).
    for entry in lost:
        if entry.file_path in paired_lost:
            continue
        candidates = [
            newcomer for newcomer in by_size.get(entry.size, ())
            if newcomer.file_path not in used_newcomers
            and newcomer.name == entry.name
        ]
        match = unique(candidates)
        if match is not None:
            suggestions.append(RelinkSuggestion(entry, match, CONFIDENCE_LOW))
            used_newcomers.add(match.file_path)
    return suggestions


def scan(
    conn,
    library_root: str | Path,
    *,
    max_dirs: int = MAX_SCAN_DIRECTORIES,
) -> RelinkReport:
    """Scan one library for broken links (I/O shell around pure passes).

    Walks the library tree with the same enumeration semantics the asset
    index publishes under (dotfiles, symlinks, junctions and reparse points
    are skipped) and reads the index plus metadata-presence flags in one
    read-only statement under the shared connection write lock. Reads run on
    a worker thread; the scan never writes.
    """
    root = str(Path(library_root).resolve())
    disk_files: dict[str, tuple[str, int, int]] = {}
    disk_dirs: set[str] = set()
    truncated = False
    visited = 0

    def onerror(error: OSError) -> None:
        # A partially unreadable tree still yields the entries gathered so
        # far; lost-path detection stays exact via the exists() probe.
        _log.warning("Relink scan could not read %s: %s", error.filename, error)

    for current, dirnames, filenames in os.walk(root, followlinks=False, onerror=onerror):
        visited += 1
        if visited > max_dirs:
            truncated = True
            break
        disk_dirs.add(str(Path(current).resolve()))
        dirnames[:] = [
            name for name in dirnames
            if not is_hidden(name)
            and not _is_link_or_reparse(Path(current) / name)
        ]
        for name in filenames:
            if is_hidden(name):
                continue
            entry_path = Path(current) / name
            if _is_link_or_reparse(entry_path):
                continue
            try:
                stat = entry_path.stat()
            except OSError:
                # No usable size/mtime means no safe pairing signal; leave
                # the file unreported instead of pairing on zeros.
                continue
            disk_files[str(entry_path.resolve())] = (
                name, stat.st_size, stat.st_mtime_ns,
            )

    with db_write_lock(conn):
        rows = conn.execute(
            "SELECT a.file_path, a.name, a.kind, a.size, a.mtime, "
            "EXISTS(SELECT 1 FROM file_tags t WHERE t.file_path=a.file_path), "
            "EXISTS(SELECT 1 FROM file_meta m WHERE m.file_path=a.file_path "
            "AND (m.notes!='' OR m.urls!='[]' OR m.rating IS NOT NULL)) "
            "FROM assets a WHERE a.library_root=? ORDER BY a.file_path",
            (root,),
        ).fetchall()

    indexed_paths = set()
    lost: list[LostEntry] = []
    missing_index_rows = 0
    for file_path, name, kind, size, mtime, has_tags, has_meta in rows:
        indexed_paths.add(file_path)
        if file_path in disk_files or file_path in disk_dirs:
            continue
        if os.path.exists(file_path):
            # Walk-budget safety net: a path the truncated walk never
            # visited is not lost just because the walk missed it.
            continue
        missing_index_rows += 1
        entry = LostEntry(
            file_path=file_path, name=name, kind=kind, size=int(size or 0),
            mtime=float(mtime or 0.0), has_tags=bool(has_tags), has_meta=bool(has_meta),
        )
        if entry.has_metadata:
            lost.append(entry)

    newcomers = tuple(sorted((
        NewcomerEntry(file_path=path, name=name_size[0], size=name_size[1],
                      mtime_ns=name_size[2])
        for path, name_size in disk_files.items()
        if path not in indexed_paths
    ), key=lambda entry: entry.file_path))
    suggestions = suggest_pairs(lost, newcomers)
    return RelinkReport(
        lost=tuple(lost),
        newcomers=newcomers,
        suggestions=tuple(suggestions),
        missing_index_rows=missing_index_rows,
        truncated=truncated,
    )


def relink(
    conn,
    *,
    library_root: str | Path,
    thumb_dir: str | Path,
    old_path: str | Path,
    new_path: str | Path,
) -> bool:
    """Apply one confirmed pairing (metadata remap + index repoint).

    Both projections commit or roll back together: the outer savepoint keeps
    ``migrate_path_metadata`` inside the caller-owned transaction (it detects
    ``conn.in_transaction`` and skips its own commit), and the index repoint
    joins the same scope. ``new_path`` must exist on disk — relinking never
    re-creates a deleted file nor touches user files. Returns ``False`` when
    old and new path are identical.
    """
    old = str(Path(old_path).resolve())
    new = str(Path(new_path).resolve())
    if old == new:
        return False
    if not Path(new).is_file():
        raise RelinkTargetMissingError(
            f"relink target is not an existing file: {new}"
        )
    repository = AssetIndexRepository(conn, library_root=library_root)
    savepoint = f"relink_{monotonic_ns():x}"
    with repository.transaction_scope(commit=True, savepoint=savepoint):
        migrate_path_metadata(conn, Path(thumb_dir), old, new)
        repository.repoint_file(old, new, commit=False)
    return True
