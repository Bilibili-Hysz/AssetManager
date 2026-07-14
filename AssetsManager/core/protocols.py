"""Service interfaces (Protocol) for core services.

Defines type-safe interfaces that panels can depend on instead of
concrete implementations. Enables testing with mock objects.

Usage (type annotation):
    from AssetsManager.core.protocols import TagStoreProtocol
    def update_tags(store: TagStoreProtocol): ...

Usage (runtime check):
    from AssetsManager.core.protocols import TagStoreProtocol
    assert isinstance(store, TagStoreProtocol)  # works at runtime too
"""
from __future__ import annotations
from typing import Protocol, runtime_checkable


@runtime_checkable
class TagStoreProtocol(Protocol):
    """Interface for tag storage operations."""

    def get_tags(self, filepath: str) -> list[str]:
        """Return tags for a file."""
        ...

    def get_tags_for_files(self, filepaths: list[str]) -> dict[str, list[str]]:
        """Return tags for many files keyed by resolved file path."""
        ...

    def add_tag(self, filepath: str, tag: str) -> None:
        """Add a tag to a file."""
        ...

    def remove_tag(self, filepath: str, tag: str) -> None:
        """Remove a tag from a file."""
        ...

    def remove_file(self, filepath: str) -> None:
        """Remove all tags for a file."""
        ...

    def get_all_tags(self) -> list[str]:
        """Return all unique tags."""
        ...

    def get_files_by_tag(self, tag: str) -> set[str]:
        """Return all file paths that have a given tag."""
        ...

    def save(self) -> None:
        """Persist pending changes."""
        ...
