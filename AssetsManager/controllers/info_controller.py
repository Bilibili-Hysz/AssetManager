"""InfoController — data access and business logic for the InfoPanel.

Centralizes all data fetching (metadata, tags, plugin fields, preview)
so that InfoPanel remains a pure UI renderer with no direct database
or singleton access.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from AssetsManager.application.metadata_service import MetadataService
from AssetsManager.application.tag_service import TagService
from AssetsManager.core.plugins.manager import PluginManagerService
from AssetsManager.repositories.plugin_metadata_repository import PluginMetadataRepository

_log = logging.getLogger(__name__)


class _DirectoryClassifyCache(Protocol):
    """Minimal cache contract used by directory classification."""

    def __contains__(self, key: str) -> bool: ...

    def __getitem__(self, key: str) -> str: ...

    def __setitem__(self, key: str, value: str) -> None: ...


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
        db_conn,
        *,
        metadata_svc: MetadataService | None = None,
        tag_svc: TagService | None = None,
    ):
        self._library_root = library_root
        self._db_conn = db_conn
        self._metadata_svc = metadata_svc or MetadataService(connection_provider=lambda _root: db_conn)
        self._tag_svc = tag_svc or TagService(connection_provider=lambda _root: db_conn)
        self._plugin_mgr = PluginManagerService.get()
        self._plugin_repo = PluginMetadataRepository(db_conn)

    @property
    def library_root(self) -> str:
        return self._library_root

    # ── Main data fetch ─────────────────────────────────────────

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
                except Exception:
                    pass

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
        self._tag_svc.add_tag(self._library_root, file_path, tag)
        return self._tag_svc.get_tags(self._library_root, file_path)

    def remove_tag(self, file_path: str, tag: str) -> list[str]:
        self._tag_svc.remove_tag(self._library_root, file_path, tag)
        return self._tag_svc.get_tags(self._library_root, file_path)

    def get_tags(self, file_path: str) -> list[str]:
        return self._tag_svc.get_tags(self._library_root, file_path)

    # ── Notes ───────────────────────────────────────────────────

    def save_notes(self, file_path: str, notes: str) -> None:
        self._metadata_svc.set_notes(self._library_root, file_path, notes)

    # ── URLs ────────────────────────────────────────────────────

    def add_url(self, file_path: str, url: str) -> None:
        self._metadata_svc.add_url(self._library_root, file_path, url)

    def remove_url(self, file_path: str, url: str) -> None:
        self._metadata_svc.remove_url(self._library_root, file_path, url)

    def get_urls(self, file_path: str) -> list[str]:
        return self._metadata_svc.get_urls(self._library_root, file_path)

    def get_notes(self, file_path: str) -> str:
        """Return notes for a file."""
        return self._metadata_svc.get_notes(self._library_root, file_path)

    # ── Plugin fields ───────────────────────────────────────────

    def get_plugin_fields(self, file_path: str) -> tuple[list[PluginField], list[str]]:
        """Return plugin-renderable fields and plugin-discovered URLs."""
        return self._get_plugin_fields(file_path)

    def _get_plugin_fields(self, file_path: str) -> tuple[list[PluginField], list[str]]:
        """Return (plugin_fields, plugin_urls) for a file or directory."""
        fields: list[PluginField] = []
        urls: list[str] = []

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
                                    self._plugin_repo.upsert_batch(file_path, pid, clean)
                                    if pid not in parsed:
                                        parsed[pid] = {}
                                    parsed[pid].update(clean)
                except OSError:
                    pass
        else:
            result = self._plugin_mgr.parse_file(file_path)
            for pid, fields in result.items():
                clean = {k: v for k, v in fields.items() if v}
                if clean:
                    self._plugin_repo.upsert_batch(file_path, pid, clean)
                    parsed[pid] = clean

        return parsed

    # ── URL discovery ───────────────────────────────────────────

    def discover_urls_in_dir(self, dir_path: str) -> list[str]:
        """Scan directory and subdirectories (2 levels) for .url/.html files."""
        import re as _re
        urls: list[str] = []

        def _scan(path: str, depth: int = 0) -> None:
            try:
                for entry in os.scandir(path):
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
                                _log.debug("URL parse failed: %s", entry.path)
                        elif name.endswith('.html') or name.endswith('.htm'):
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
                pass

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
                            pass
                    elif name.endswith('.html') or name.endswith('.htm'):
                        try:
                            with open(entry.path, 'r', encoding='utf-8', errors='ignore') as f:
                                content = f.read()
                            for m in _re.finditer(
                                r'href=["\']?(https?://[^\s"\'<>]+)', content, _re.IGNORECASE
                            ):
                                urls.append(m.group(1))
                        except OSError:
                            pass
        except OSError:
            pass
        seen: set[str] = set()
        result: list[str] = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                result.append(u)
        return result

    # ── Directory classification ─────────────────────────────────

    @staticmethod
    def classify_dir(
        dir_path: str, *, classify_cache: _DirectoryClassifyCache | None = None,
    ) -> str:
        """Return a human-readable summary of file types in a directory.

        Uses an emoji-based breakdown (e.g. "🖼 5  📄 3") for display in
        the InfoPanel.  The optional *classify_cache* avoids re-scanning
        directories on repeated selections.
        """
        cache = classify_cache if classify_cache is not None else {}
        if dir_path in cache:
            return cache[dir_path]
        from AssetsManager.panels.file_list._common import FILTER_CATEGORIES
        emoji_map = {
            "Images": "🖼", "3D Models": "🔷", "Videos": "🎬",
            "Documents": "📄", "Archives": "🗜",
        }
        try:
            counts: dict[str, int] = {}
            for entry in os.scandir(dir_path):
                if not entry.is_file():
                    continue
                ext = Path(entry.name).suffix.lower()
                for cat, exts in FILTER_CATEGORIES.items():
                    if ext in exts:
                        emoji = emoji_map.get(cat, "📄")
                        counts[emoji] = counts.get(emoji, 0) + 1
                        break
                if ext == ".blend":
                    counts["🧊"] = counts.get("🧊", 0) + 1
            if counts:
                result = "  ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda x: -x[1]))
                cache[dir_path] = result
                return result
        except OSError:
            pass
        cache[dir_path] = ""
        return ""

    @staticmethod
    def is_deepest_folder(path: str, library_root: str, sidebar_depth: int,
                          branch_depths: dict[str, int] | None = None) -> bool:
        """Check whether this path reaches or exceeds the configured sidebar depth."""
        if not library_root or sidebar_depth < 1:
            return False
        try:
            rel = os.path.relpath(path, library_root)
        except ValueError:
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
