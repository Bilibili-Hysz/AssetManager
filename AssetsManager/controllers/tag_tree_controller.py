"""TagTreeController — data access for the tag tree panel.

Wraps TagStore and TagLibrary operations so that TagTreePanel
remains a pure UI renderer with no direct store access.
"""
from __future__ import annotations

import logging
from typing import Any, cast

from AssetsManager.application.tag_service import TagService
from AssetsManager.core.tag_library import get_library

_log = logging.getLogger(__name__)


class TagTreeController:
    """Data access for tag browsing, filtering, and mutation."""

    def __init__(self, library_root: str, tag_svc: TagService | None = None):
        self._library_root = library_root
        self._tag_svc = tag_svc or TagService()

    @property
    def library_root(self) -> str:
        return self._library_root

    def get_all_tags(self) -> list[str]:
        """Return all tags in the library."""
        return self._tag_svc.get_all_tags(self._library_root)

    def get_files_by_tag(self, tag: str) -> list[str]:
        """Return all file paths that have the given tag."""
        return sorted(self._tag_svc.get_files_by_tag(self._library_root, tag))

    def get_tag_with_files(self) -> list[dict]:
        """Return all tags with their file lists for tree rendering.

        Uses a single batch query (repository ``list_file_tags``) instead of
        one SQL statement per tag, avoiding N+1 queries on large libraries.
        Each entry also carries the tag's visual metadata (icon/color/
        category) so the tree can render it without a second lookup.
        """
        tags = self.get_all_tags()
        metadata_by_tag = {
            meta.get("name"): meta
            for meta in self._tag_svc.get_tags_with_metadata(self._library_root)
        }
        files_by_tag = self._files_by_tag_batch(tags)
        return [
            {
                "tag": tag,
                "count": len(files_by_tag.get(tag, [])),
                "files": sorted(files_by_tag.get(tag, [])),
                "icon": str((metadata_by_tag.get(tag) or {}).get("icon") or ""),
                "color": str((metadata_by_tag.get(tag) or {}).get("color") or ""),
                "category": str((metadata_by_tag.get(tag) or {}).get("category") or ""),
            }
            for tag in tags
        ]

    def get_tag_metadata(self, tag: str) -> dict[str, str] | None:
        """Return a tag's visual metadata (color/icon/category), or None."""
        return self._tag_svc.get_tag_metadata(self._library_root, tag)

    def set_tag_metadata(
        self, tag: str, color: str = "", icon: str = "", category: str = ""
    ) -> None:
        """Persist a tag's visual metadata and invalidate the tag catalog."""
        self._tag_svc.set_tag_metadata(
            self._library_root, tag, color=color, icon=icon, category=category
        )

    def _files_by_tag_batch(self, tags: list[str]) -> dict[str, list[str]]:
        """Return {tag: [file paths]} from one batch query when possible.

        Prefers the service's repository ``list_file_tags()`` (a single SQL
        statement covering every file/tag pair, grouped in memory). Falls
        back to one query per tag for services that cannot resolve a
        repository (e.g. fakes in tests or legacy adapters).
        """
        resolver = getattr(self._tag_svc, "_repo", None)
        if callable(resolver):
            try:
                repo = resolver(None, self._library_root)
            except Exception:
                repo = None
            list_file_tags = getattr(repo, "list_file_tags", None)
            if callable(list_file_tags):
                grouped: dict[str, list[str]] = {}
                for path, tag in cast(Any, list_file_tags)():
                    grouped.setdefault(tag, []).append(path)
                return grouped
        # Legacy fallback: one query per tag.
        return {tag: list(self.get_files_by_tag(tag)) for tag in tags}

    def add_tag(self, tag: str) -> None:
        """Register a tag in the canonical library.

        Delegates to ``TagLibrary.register_tag()`` so the tag becomes a real
        canonical entry (canonical() alone only performs a lookup and never
        registers). Re-adding an already-registered tag is a no-op, so the
        library is only written to disk when a genuinely new tag is added.
        """
        library = get_library()
        tag = tag.strip()
        if not tag:
            return
        if tag not in library.all_canonicals():
            library.register_tag(tag)

    def rename_tag(self, old_tag: str, new_tag: str) -> None:
        """Rename a tag across all files and keep TagLibrary in sync.

        The DB rename alone would leave the old canonical name in the tag
        library (with its synonyms), so the renamed canonical is registered
        and the old one removed after a successful rename.
        """
        self._tag_svc.rename_tag(self._library_root, old_tag, new_tag)
        library = get_library()
        old_canonical = library.canonical(old_tag)
        new_canonical = library.canonical(new_tag)
        if old_canonical == new_canonical:
            return
        library.register_tag(new_canonical)
        # Only drop the library entry when the old name is itself a
        # canonical; an alias rename must not delete an unrelated canonical.
        if old_tag.strip().lower() in {c.lower() for c in library.all_canonicals()}:
            library.remove_canonical(old_tag)

    def delete_tag(self, tag: str) -> int:
        """Delete a tag from all files. Returns number of affected files."""
        files = list(self._tag_svc.get_files_by_tag(self._library_root, tag))
        self._tag_svc.delete_tag(self._library_root, tag)
        get_library().remove_canonical(tag)
        return len(files)

    def remove_tag_from_file(self, filepath: str, tag: str) -> None:
        """Remove a tag from a specific file."""
        self._tag_svc.remove_tag(self._library_root, filepath, tag)

    def get_files_for_tag(self, tag: str) -> list[str]:
        """Return files that have the given tag."""
        return list(self._tag_svc.get_files_by_tag(self._library_root, tag))
