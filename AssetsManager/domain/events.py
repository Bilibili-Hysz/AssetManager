"""Domain events — immutable records of things that happened.

Domain events are pure data objects with no infrastructure dependencies.
They complement Qt signals for business logic that needs to be testable
without Qt, and can be used for undo/redo event sourcing in the future.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DomainEvent:
    """Base class for all domain events."""
    timestamp: float = field(default_factory=time.time)


# ── Library events ───────────────────────────────────────────────

@dataclass(frozen=True)
class LibraryOpened(DomainEvent):
    """A library was opened."""
    library_root: str = ""


# ── File events ──────────────────────────────────────────────────

@dataclass(frozen=True)
class FileRenamed(DomainEvent):
    """A file or directory was renamed/moved."""
    old_path: str = ""
    new_path: str = ""


@dataclass(frozen=True)
class FileDeleted(DomainEvent):
    """A file or directory was deleted."""
    path: str = ""
    is_dir: bool = False


@dataclass(frozen=True)
class FileCreated(DomainEvent):
    """A new file or directory was created."""
    path: str = ""
    is_dir: bool = False


@dataclass(frozen=True)
class FileCopied(DomainEvent):
    """A file or directory was copied."""
    source_path: str = ""
    destination_path: str = ""


# ── Metadata events ──────────────────────────────────────────────

@dataclass(frozen=True)
class TagsChanged(DomainEvent):
    """Tags were modified for a file."""
    file_path: str = ""
    new_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class NotesChanged(DomainEvent):
    """Notes were modified for a file."""
    file_path: str = ""


@dataclass(frozen=True)
class UrlsChanged(DomainEvent):
    """URLs were modified for a file."""
    file_path: str = ""
    new_urls: tuple[str, ...] = ()


