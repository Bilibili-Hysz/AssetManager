"""TagTreeController — data access for the tag tree panel.

Wraps TagStore and TagLibrary operations so that TagTreePanel
remains a pure UI renderer with no direct store access.
"""
from __future__ import annotations

import logging

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
        """Return all tags with their file lists for tree rendering."""
        tags = self.get_all_tags()
        result = []
        for tag in tags:
            files = self.get_files_by_tag(tag)
            result.append({"tag": tag, "count": len(files), "files": files})
        return result

    def add_tag(self, tag: str) -> None:
        """Register a tag in the canonical library.

        Calls TagLibrary.canonical() to ensure the tag is registered in the
        synonym map. The tag will appear in get_all_tags() once any file
        is associated with it.
        """
        canonical = get_library().canonical(tag.strip())
        if canonical:
            get_library()._save()

    def rename_tag(self, old_tag: str, new_tag: str) -> None:
        """Rename a tag across all files."""
        self._tag_svc.rename_tag(self._library_root, old_tag, new_tag)

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
