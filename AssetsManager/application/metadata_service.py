"""Metadata application service."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection

from AssetsManager.application.context import ConnectionProvider
from AssetsManager.core.project_data import ProjectData
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import NotesChanged, UrlsChanged
from AssetsManager.repositories.metadata_repository import MetadataRepository
from AssetsManager.repositories.tag_repository import TagRepository

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AssetMetadata:
    path: Path
    tags: tuple[str, ...]
    notes: str
    urls: tuple[str, ...]


class MetadataService:
    """Read and write per-asset metadata.

    Uses MetadataRepository for file_meta operations and
    TagRepository for tag reads.
    """

    def __init__(self, connection_provider: ConnectionProvider | None = None):
        self._connection_provider = connection_provider

    def _connection(self, library_root: str | Path) -> Connection:
        root = str(Path(library_root).resolve())
        if self._connection_provider is not None:
            return self._connection_provider(root)
        raise RuntimeError(
            "MetadataService requires a ConnectionProvider. "
            "Use ApplicationBootstrap.for_library() or pass connection_provider explicitly."
        )

    def _repo(self, library_root: str | Path) -> MetadataRepository:
        """Return a MetadataRepository for the given library root."""
        return MetadataRepository(self._connection(library_root))

    def get_metadata(self, library_root: str | Path, path: str | Path) -> AssetMetadata:
        root = str(Path(library_root).resolve())
        target = Path(path).resolve()
        conn = self._connection(root)
        meta_repo = MetadataRepository(conn)
        tag_repo = TagRepository(conn)
        return AssetMetadata(
            path=target,
            tags=tuple(tag_repo.get_tags(str(target))),
            notes=meta_repo.get_notes(str(target)),
            urls=tuple(meta_repo.get_urls(str(target))),
        )

    def get_notes(self, library_root: str | Path, path: str | Path) -> str:
        return self._repo(str(Path(library_root).resolve())).get_notes(str(Path(path).resolve()))

    def set_notes(self, library_root: str | Path, path: str | Path, text: str) -> None:
        key = str(Path(path).resolve())
        self._repo(str(Path(library_root).resolve())).set_notes(key, text)
        get_event_bus().publish(NotesChanged(file_path=key))

    def get_urls(self, library_root: str | Path, path: str | Path) -> list[str]:
        return self._repo(str(Path(library_root).resolve())).get_urls(str(Path(path).resolve()))

    def add_url(self, library_root: str | Path, path: str | Path, url: str) -> None:
        root = str(Path(library_root).resolve())
        key = str(Path(path).resolve())
        repo = self._repo(root)
        urls = repo.add_url(key, url)
        if urls is not None:
            get_event_bus().publish(UrlsChanged(file_path=key, new_urls=tuple(urls)))

    def remove_url(self, library_root: str | Path, path: str | Path, url: str) -> None:
        root = str(Path(library_root).resolve())
        key = str(Path(path).resolve())
        repo = self._repo(root)
        urls = repo.remove_url(key, url)
        if urls is not None:
            get_event_bus().publish(UrlsChanged(file_path=key, new_urls=tuple(urls)))

    def get_dir_size(self, library_root: str | Path, dir_path: str | Path,
                     force: bool = False) -> tuple[int, bool]:
        root = str(Path(library_root).resolve())
        target = str(Path(dir_path).resolve())
        conn = self._connection(root)
        repo = MetadataRepository(conn)
        if not force and target == root:
            total = repo.get_library_total_size(root)
            if total > 0:
                return (total, True)
        if not os.path.isdir(target):
            return (0, False)
        if not force:
            cached = repo.get_cached_size(target)
            if cached is not None:
                try:
                    current_mtime = os.path.getmtime(target)
                except OSError:
                    return (0, False)
                if cached[1] >= current_mtime:
                    return (cached[0], True)
        size = ProjectData.compute_dir_size(target)
        try:
            mtime = os.path.getmtime(target)
        except OSError:
            mtime = 0.0
        repo.set_cached_size(target, size, mtime)
        return (size, False)

    def set_dir_size(self, library_root: str | Path, dir_path: str | Path, size: int) -> None:
        root = str(Path(library_root).resolve())
        target = str(Path(dir_path).resolve())
        mtime = os.path.getmtime(target) if os.path.exists(target) else 0.0
        self._repo(root).set_cached_size(target, size, mtime)

    def get_cached_stats(
        self, library_root: str | Path, file_paths: list[str]
    ) -> dict[str, tuple[int, float]]:
        """Return {path: (cached_size, cached_mtime)} for given paths from file_meta."""
        if not file_paths:
            return {}
        return self._repo(str(Path(library_root).resolve())).get_cached_stats(file_paths)

    def get_cached_file_count(self, library_root: str | Path, dir_path: str | Path) -> int | None:
        """Return cached file count for a directory, or None if not cached."""
        return self._repo(str(Path(library_root).resolve())).get_cached_file_count(str(Path(dir_path).resolve()))

    def get_library_total_size(self, library_root: str | Path) -> int:
        """Return total size from library_stats, or 0 if not available."""
        return self._repo(str(Path(library_root).resolve())).get_library_total_size(str(Path(library_root).resolve()))

    def batch_get_cached_file_counts(self, library_root: str, dir_paths: list[str]) -> dict[str, int]:
        """Return {path: count} for directories that have cached file counts."""
        if not dir_paths:
            return {}
        return self._repo(str(Path(library_root).resolve())).batch_get_cached_file_counts(dir_paths)

    def batch_set_cached_file_counts(self, library_root: str, entries: dict[str, int]) -> None:
        """Cache file counts for multiple directories in a single transaction."""
        if not entries:
            return
        self._repo(str(Path(library_root).resolve())).batch_set_cached_file_counts(entries)
