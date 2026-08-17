"""InfoController — data access and business logic for the InfoPanel.

Centralizes all data fetching (metadata, tags, plugin fields, preview)
so that InfoPanel remains a pure UI renderer with no direct database
or singleton access.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from AssetsManager.application.context import LibrarySession, session_operation
from AssetsManager.application.metadata_service import MetadataService
from AssetsManager.application.tag_service import TagService
from AssetsManager.core.database import DatabaseManager, db_write_lock
from AssetsManager.core.plugins.manager import PluginManagerService
from AssetsManager.repositories.plugin_metadata_repository import PluginMetadataRepository

_log = logging.getLogger(__name__)


class _DirectoryClassifyCache(Protocol):
    """Minimal cache contract used by directory classification."""

    def __contains__(self, key: str) -> bool: ...

    def __getitem__(self, key: str) -> str: ...

    def __setitem__(self, key: str, value: str) -> None: ...


def _read_url_file_text(path: str) -> str:
    """Read a .url file, falling back to UTF-16 for legacy Windows files.

    .url shortcuts exported from Windows can be UTF-16 (with or without a
    BOM). UTF-8 (or UTF-8 with BOM) is tried first; UTF-16 is used when the
    bytes are not valid UTF-8 or decode to embedded NUL characters.
    """
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return ""
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "\x00" not in text:
            return text
    # Last resort: lossy UTF-8, matching the previous read behavior.
    return raw.decode("utf-8", errors="ignore")


@dataclass(frozen=True)
class PluginField:
    """A single plugin-contributed metadata field."""
    key: str
    value: str
    plugin_id: str


@dataclass(frozen=True)
class FileInfo:
    """Complete information about a file or directory for display in InfoPanel."""
    path: str
    name: str
    is_dir: bool
    file_type: str
    size_display: str
    modified_display: str
    parent_path: str
    tags: tuple[str, ...]
    notes: str
    urls: tuple[str, ...]
    plugin_fields: tuple[PluginField, ...]
    dir_summary: str | None
    preview_path: str | None
    is_project: bool


class InfoController:
    """Provides file metadata, tags, plugin data, and preview info.

    All data access goes through application services and repositories.
    InfoPanel uses this controller instead of accessing singletons directly.
    """

    def __init__(
        self,
        library_root: str,
        db_conn=None,
        *,
        metadata_svc: MetadataService | None = None,
        tag_svc: TagService | None = None,
        session: LibrarySession | None = None,
    ):
        self._library_root = str(Path(library_root).resolve())
        self._session = session
        if session is not None:
            if Path(session.root).resolve() != Path(library_root).resolve():
                raise ValueError("library_root does not match the bound LibrarySession")
            if db_conn is None:
                # Session-derived connection: the presentation layer passes the
                # LibrarySession, not a raw connection_for(...) result.
                db_conn = session.connection_for(session.root)
            elif db_conn is not session.connection_for(session.root):
                raise ValueError("connection does not belong to the bound LibrarySession")
        if (
            session is not None
            and metadata_svc is not None
            and getattr(metadata_svc, "_session", None) is not session
        ):
            raise ValueError(
                "metadata_svc is not bound to the controller LibrarySession"
            )
        if (
            session is not None
            and isinstance(tag_svc, TagService)
            and getattr(tag_svc, "_session", None) is not session
        ):
            raise ValueError(
                "tag_svc is not bound to the controller LibrarySession"
            )
        self._db_conn = (
            # Legacy controller construction preserves caller-owned raw connections.
            DatabaseManager.validate_connection_owner(
                Path(library_root).resolve(), db_conn, allow_unmanaged=True
            )
            if db_conn is not None else None
        )
        if self._db_conn is None:
            # Keep filesystem-only construction valid; DB-backed operations still
            # fail through the services' existing explicit-provider error.
            self._metadata_svc = metadata_svc or MetadataService()
            self._tag_svc = tag_svc or (
                TagService.for_session(session) if session is not None else TagService()
            )
        else:
            conn = self._db_conn
            if metadata_svc is not None:
                self._metadata_svc = metadata_svc
            elif session is not None:
                self._metadata_svc = MetadataService.for_session(session)
            else:
                self._metadata_svc = MetadataService(
                    connection_provider=lambda _root: conn
                )
            self._tag_svc = tag_svc or (
                TagService.for_session(session)
                if session is not None
                else TagService(connection_provider=lambda _root: conn)
            )
        self._plugin_mgr = PluginManagerService.get()
        if self._db_conn is None:
            self._plugin_repo = None
        elif session is not None:
            # Canonical session path: derive the repository from the session
            # instead of hand-rolling a raw connection repository.
            self._plugin_repo = PluginMetadataRepository.for_session(session)
        else:
            self._plugin_repo = PluginMetadataRepository(
                self._db_conn, library_root=self._library_root
            )
        self._classify_cache: dict[str, str] = {}
        self._classify_cache_max = 5000
        # mtime recorded when a directory summary was cached; a mismatch on
        # hit means the directory changed and the cache entry is stale.
        self._classify_mtimes: dict[str, float] = {}

    @property
    def library_root(self) -> str:
        return self._library_root

    def _resolve_under_root(self, path: str | Path) -> str:
        """Resolve a controller path and reject paths outside its library."""
        root = Path(self._library_root).resolve()
        target = Path(path).resolve()
        if not target.is_relative_to(root):
            raise ValueError(
                f"path must be under library_root: {target} (root {root})"
            )
        return str(target)

    # ── Main data fetch ─────────────────────────────────────────

    @session_operation
    def get_file_info(
        self,
        file_path: str,
        *,
        is_dir: bool,
        file_type: str,
        size_display: str,
        modified_display: str,
        parent_path: str,
        dir_summary: str | None = None,
        preview_path: str | None = None,
        is_project: bool = False,
    ) -> FileInfo:
        """Build a FileInfo for the given path.

        The caller provides filesystem-derived display strings (type, size,
        date) so the controller stays free of Qt/QFileInfo dependencies.
        """
        file_path = self._resolve_under_root(file_path)
        metadata = self._metadata_svc.get_metadata(self._library_root, file_path)
        tags = tuple(metadata.tags)
        notes = metadata.notes
        urls = list(metadata.urls)

        # Plugin fields (from DB first, then parse if empty)
        plugin_fields, plugin_urls = self._get_plugin_fields(file_path)

        # Merge plugin URLs
        for purl in plugin_urls:
            if purl not in urls:
                try:
                    self._metadata_svc.add_url(self._library_root, file_path, purl)
                    urls.append(purl)
                except sqlite3.ProgrammingError:
                    # A closed connection is a lifecycle failure, not a failed optional persistence attempt.
                    raise
                except (OSError, sqlite3.Error):
                    _log.warning("failed to persist plugin URL: %s", purl, exc_info=True)

        return FileInfo(
            path=file_path,
            name=Path(file_path).name or file_path,
            is_dir=is_dir,
            file_type=file_type,
            size_display=size_display,
            modified_display=modified_display,
            parent_path=parent_path,
            tags=tags,
            notes=notes,
            urls=tuple(urls),
            plugin_fields=tuple(plugin_fields),
            dir_summary=dir_summary,
            preview_path=preview_path,
            is_project=is_project,
        )

    # ── Tag operations ──────────────────────────────────────────

    def add_tag(self, file_path: str, tag: str) -> list[str]:
        file_path = self._resolve_under_root(file_path)
        self._tag_svc.add_tag(self._library_root, file_path, tag)
        return self._tag_svc.get_tags(self._library_root, file_path)

    def remove_tag(self, file_path: str, tag: str) -> list[str]:
        file_path = self._resolve_under_root(file_path)
        self._tag_svc.remove_tag(self._library_root, file_path, tag)
        return self._tag_svc.get_tags(self._library_root, file_path)

    def get_tags(self, file_path: str) -> list[str]:
        return self._tag_svc.get_tags(
            self._library_root, self._resolve_under_root(file_path)
        )

    # ── Notes ───────────────────────────────────────────────────

    def save_notes(self, file_path: str, notes: str) -> None:
        self._metadata_svc.set_notes(
            self._library_root, self._resolve_under_root(file_path), notes
        )

    # ── URLs ────────────────────────────────────────────────────

    def add_url(self, file_path: str, url: str) -> None:
        self._metadata_svc.add_url(
            self._library_root, self._resolve_under_root(file_path), url
        )

    def remove_url(self, file_path: str, url: str) -> None:
        self._metadata_svc.remove_url(
            self._library_root, self._resolve_under_root(file_path), url
        )

    def get_urls(self, file_path: str) -> list[str]:
        return self._metadata_svc.get_urls(
            self._library_root, self._resolve_under_root(file_path)
        )

    def get_notes(self, file_path: str) -> str:
        """Return notes for a file."""
        return self._metadata_svc.get_notes(
            self._library_root, self._resolve_under_root(file_path)
        )

    # ── Plugin fields ───────────────────────────────────────────

    @session_operation
    def get_plugin_fields(self, file_path: str) -> tuple[list[PluginField], list[str]]:
        """Return plugin-renderable fields and plugin-discovered URLs."""
        file_path = self._resolve_under_root(file_path)
        return self._get_plugin_fields(file_path)

    def _get_plugin_fields(self, file_path: str) -> tuple[list[PluginField], list[str]]:
        """Return (plugin_fields, plugin_urls) for a file or directory."""
        file_path = self._resolve_under_root(file_path)
        fields: list[PluginField] = []
        urls: list[str] = []

        # Filesystem-only controllers have no plugin metadata persistence.
        if self._plugin_repo is None:
            return fields, urls

        # The connection is shared between the GUI thread and background
        # workers (link-directory parsing). Serialize reads against the
        # repository's writes so both never touch the same SQLite connection
        # concurrently. db_write_lock is reentrant, so the nested
        # upsert_batch() lock inside _parse_and_store cannot deadlock.
        with db_write_lock(self._db_conn):
            # 1. Read from DB
            stored = self._plugin_repo.get_fields(file_path)

            # 2. If DB empty, parse with plugin and persist
            if not stored:
                stored = self._parse_and_store(file_path)

        for plugin_id, kv in stored.items():
            for key, value in kv.items():
                if not value:
                    continue
                if key == "url" and value.startswith(("http://", "https://")):
                    urls.append(value)
                elif key != "url":
                    fields.append(PluginField(key=key, value=value, plugin_id=plugin_id))

        return fields, urls

    def _parse_and_store(self, file_path: str) -> dict[str, dict[str, str]]:
        """Parse files with plugins and persist to DB."""
        if not self._plugin_mgr._records:
            return {}
        repo = self._plugin_repo
        if repo is None:
            return {}

        parsed: dict[str, dict[str, str]] = {}

        if os.path.isdir(file_path):
            link_dir = os.path.join(file_path, "_link")
            if os.path.isdir(link_dir):
                try:
                    for entry in os.scandir(link_dir):
                        if entry.is_file() and entry.name.lower().endswith(".txt"):
                            result = self._plugin_mgr.parse_file(entry.path)
                            for pid, fields in result.items():
                                clean = {k: v for k, v in fields.items() if v}
                                if clean:
                                    repo.upsert_batch(file_path, pid, clean)
                                    if pid not in parsed:
                                        parsed[pid] = {}
                                    parsed[pid].update(clean)
                except OSError:
                    _log.warning("plugin link directory scan failed: %s", link_dir, exc_info=True)
        else:
            result = self._plugin_mgr.parse_file(file_path)
            for pid, fields in result.items():
                clean = {k: v for k, v in fields.items() if v}
                if clean:
                    repo.upsert_batch(file_path, pid, clean)
                    parsed[pid] = clean

        return parsed

    # ── URL discovery ───────────────────────────────────────────

    def discover_urls_in_dir(self, dir_path: str) -> list[str]:
        """Scan directory and subdirectories (2 levels) for .url/.html files."""
        dir_path = self._resolve_under_root(dir_path)
        import re as _re
        urls: list[str] = []

        def _scan(path: str, depth: int = 0) -> None:
            try:
                for entry in os.scandir(path):
                    if entry.is_file():
                        name = entry.name.lower()
                        if name.endswith('.url'):
                            try:
                                text = _read_url_file_text(entry.path)
                                for line in text.splitlines():
                                    if line.lower().startswith('url='):
                                        candidate = line[4:].strip()
                                        if candidate.startswith('http'):
                                            urls.append(candidate)
                                        break
                            except OSError:
                                _log.debug("URL parse failed: %s", entry.path)
                        elif name.endswith(('.html', '.htm')):
                            try:
                                with open(entry.path, 'r', encoding='utf-8', errors='ignore') as f:
                                    content = f.read()
                                for m in _re.finditer(
                                    r'href=["\']?(https?://[^\s"\'<>]+)', content, _re.IGNORECASE
                                ):
                                    urls.append(m.group(1))
                            except OSError:
                                _log.debug("HTML parse failed: %s", entry.path)
                    elif entry.is_dir() and depth < 2:
                        _scan(entry.path, depth + 1)
            except OSError:
                _log.warning("URL discovery scan failed: %s", path, exc_info=True)

        _scan(dir_path)
        seen: set[str] = set()
        result: list[str] = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                result.append(u)
                if len(result) >= 10:
                    break
        return result

    @staticmethod
    def _discover_urls_flat(dir_path: str) -> list[str]:
        """Flat scan (no recursion) for .url/.html files in a single directory."""
        import re as _re
        urls: list[str] = []
        try:
            for entry in os.scandir(dir_path):
                if entry.is_file():
                    name = entry.name.lower()
                    if name.endswith('.url'):
                        try:
                            with open(entry.path, 'r', encoding='utf-8', errors='ignore') as f:
                                for line in f:
                                    if line.lower().startswith('url='):
                                        candidate = line[4:].strip()
                                        if candidate.startswith('http'):
                                            urls.append(candidate)
                                        break
                        except OSError:
                            _log.warning("URL file read failed: %s", entry.path, exc_info=True)
                    elif name.endswith(('.html', '.htm')):
                        try:
                            with open(entry.path, 'r', encoding='utf-8', errors='ignore') as f:
                                content = f.read()
                            for m in _re.finditer(
                                r'href=["\']?(https?://[^\s"\'<>]+)', content, _re.IGNORECASE
                            ):
                                urls.append(m.group(1))
                        except OSError:
                            _log.warning("HTML file read failed: %s", entry.path, exc_info=True)
        except OSError:
            _log.warning("directory classification failed: %s", dir_path, exc_info=True)
        seen: set[str] = set()
        result: list[str] = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                result.append(u)
        return result

    # ── Directory classification ─────────────────────────────────

    def classify_dir(
        self, dir_path: str, *, classify_cache: _DirectoryClassifyCache | None = None,
    ) -> str:
        """Return a human-readable summary of file types in a directory.

        Uses a compact semantic breakdown (for example ``Images 5  Documents 3``)
        for display in the InfoPanel. The optional *classify_cache* avoids
        re-scanning directories on repeated selections; when it is omitted the
        controller's instance cache is used so repeated calls stay cached.
        Scans are budgeted to the first 501 entries so huge directories cannot
        stall the UI.
        """
        if classify_cache is not None:
            cache = classify_cache
        else:
            if len(self._classify_cache) >= self._classify_cache_max:
                self._classify_cache.clear()
                self._classify_mtimes.clear()
            cache = self._classify_cache
        if dir_path in cache:
            # Invalidate entries whose directory mtime changed since the
            # summary was computed; stale summaries would otherwise persist
            # for the lifetime of the process.
            cached_mtime = self._classify_mtimes.get(dir_path)
            try:
                current_mtime = os.path.getmtime(dir_path)
            except OSError:
                current_mtime = None
            if cached_mtime is None or cached_mtime == current_mtime:
                return cache[dir_path]
            # Fall through and rescan the changed directory.
        if len(self._classify_mtimes) >= self._classify_cache_max * 2:
            self._classify_mtimes.clear()
        from AssetsManager.application.asset_filters import FILTER_CATEGORIES
        result = ""
        try:
            counts: dict[str, int] = {}
            with os.scandir(dir_path) as scanner:
                for i, entry in enumerate(scanner):
                    if i > 500:
                        break
                    if not entry.is_file():
                        continue
                    ext = Path(entry.name).suffix.lower()
                    for cat, exts in FILTER_CATEGORIES.items():
                        if ext in exts:
                            counts[cat] = counts.get(cat, 0) + 1
                            break
            if counts:
                result = "  ".join(
                    f"{category} {count}"
                    for category, count in sorted(counts.items(), key=lambda x: -x[1])
                )
        except OSError:
            _log.warning("directory classification failed: %s", dir_path, exc_info=True)
        cache[dir_path] = result
        try:
            self._classify_mtimes[dir_path] = os.path.getmtime(dir_path)
        except OSError:
            self._classify_mtimes.pop(dir_path, None)
        return result

    @staticmethod
    def is_deepest_folder(path: str, library_root: str, sidebar_depth: int,
                          branch_depths: dict[str, int] | None = None) -> bool:
        """Check whether this path reaches or exceeds the configured sidebar depth."""
        if not library_root or sidebar_depth < 1:
            return False
        try:
            root = Path(library_root).resolve()
            target = Path(path).resolve()
            if not target.is_relative_to(root):
                return False
            rel = os.path.relpath(target, root)
        except (OSError, ValueError):
            return False
        if rel in (".", ""):
            return False
        parts = rel.replace(os.sep, "/").rstrip("/").split("/")
        if not parts or parts == [""]:
            return False
        level = len(parts)
        branch = parts[0]
        depths = branch_depths or {}
        effective = depths.get(branch, sidebar_depth)
        return level >= effective
