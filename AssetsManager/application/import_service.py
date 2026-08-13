"""Explicit import service for bringing external assets into a library.

Importing is deliberately distinct from the in-library ``copy_to_directory``
operation: import walks directory trees from outside (or inside) the library
and reports a single ``FileSystemChanged(kind='import')`` event for the whole
batch, so a large directory import does not flood the event bus with one
``copied`` event per file.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from AssetsManager.application.file_operation_service import unique_destination
from AssetsManager.application.context import LibrarySession
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import FileSystemChanged
from AssetsManager.lan.path_guard import assert_under_root

ProgressCallback = Callable[[int, int], None]


@dataclass
class ImportResult:
    """Outcome of one import_sources() call."""

    copied: int
    skipped: int
    failed: list[str] = field(default_factory=list)


class ImportService:
    """Import files/folders into a destination inside an open library session.

    The service owns the batch boundary: it validates sources/destination,
    expands directory sources into (source, relative-path) pairs preserving
    the directory structure (skipping dot-prefixed entries), copies each file
    with name-conflict renaming, and emits exactly one
    ``FileSystemChanged(kind='import')`` event on completion.
    """

    def __init__(self, session: LibrarySession, file_operations) -> None:
        self.session = session
        self.file_operations = file_operations

    # ── helpers ────────────────────────────────────────────────

    @classmethod
    def _collect_files(
        cls, sources: list[str | Path]
    ) -> list[tuple[Path, Path]]:
        """Expand sources into (source, relative-path) pairs, skipping dot entries.

        Directory sources are walked recursively with ``os.scandir``; each
        file keeps its path relative to the directory source so the imported
        tree structure is preserved.  File sources get an empty relative path.
        """
        collected: list[tuple[Path, Path]] = []

        def walk_dir(directory: Path, base: Path) -> None:
            with os.scandir(directory) as it:
                for entry in it:
                    if entry.name.startswith("."):
                        continue
                    path = Path(entry.path)
                    if entry.is_dir(follow_symlinks=False):
                        walk_dir(path, base)
                    elif entry.is_file(follow_symlinks=False):
                        collected.append((path, path.relative_to(base)))

        for source in sources:
            src = Path(source)
            if src.is_dir():
                walk_dir(src, src)
            else:
                collected.append((src, Path()))
        return collected

    @staticmethod
    def _under_root(path: str | Path, root: str | Path) -> bool:
        try:
            assert_under_root(root, path)
            return True
        except ValueError:
            return False

    def _copy_one(self, src: Path, rel: Path, destination_dir: Path) -> None:
        """Copy one file, preserving its relative path inside destination_dir."""
        target_dir = destination_dir / rel.parent
        target_dir.mkdir(parents=True, exist_ok=True)
        target = unique_destination(target_dir / src.name)
        try:
            shutil.copy2(str(src), str(target))
        except OSError:
            # unique_destination may have reserved (then deleted) the target;
            # remove any partial result before re-raising.
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    # ── public API ─────────────────────────────────────────────

    def import_sources(
        self,
        sources: list[str | Path],
        destination_dir: str | Path,
        *,
        progress: ProgressCallback | None = None,
    ) -> ImportResult:
        """Import *sources* into *destination_dir*.

        Raises ValueError when the destination is outside ``session.root``.
        Raises RuntimeError when the session is already closed.  An empty
        *sources* list is a no-op returning ``ImportResult(0, 0, [])``.
        """
        if self.session.is_closed:
            raise RuntimeError("Cannot use a closed LibrarySession")
        if not sources:
            return ImportResult(copied=0, skipped=0, failed=[])

        root = self.session.root
        # Reject an out-of-library destination up front.
        assert_under_root(root, destination_dir)
        destination = Path(destination_dir).resolve()

        # Expand and categorize sources before touching the filesystem, so the
        # progress denominator is stable and in-library sources are skipped
        # (never self-copied).
        in_library: list[str | Path] = []
        external: list[str | Path] = []
        for source in sources:
            if self._under_root(source, root):
                in_library.append(source)
            else:
                external.append(source)

        files = self._collect_files(external)
        skipped = len(in_library)
        total = len(files)

        copied = 0
        failed: list[str] = []
        done = 0

        if progress is not None:
            progress(done, total)

        for src, rel in files:
            try:
                self._copy_one(src, rel, destination)
                copied += 1
            except OSError as exc:
                failed.append(f"{src}: {exc}")
            done += 1
            if progress is not None:
                progress(done, total)

        # Refresh the index projection for the populated destination and emit
        # a single batch event, reusing the file-operation service's own
        # projection refresh (the copy loop itself is minimal shutil.copy2 so
        # a large import does not publish one event per file).
        self.file_operations._refresh_directory_tree(destination)
        self.file_operations._refresh_parents(destination.parent)
        get_event_bus().publish(FileSystemChanged(
            library_root=self.session.root_str,
            session_token=self.session.event_token,
            kind="import",
            paths=(str(destination),),
        ))

        return ImportResult(copied=copied, skipped=skipped, failed=failed)
