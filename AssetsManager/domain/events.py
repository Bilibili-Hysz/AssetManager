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
    session_token: str = ""


@dataclass(frozen=True)
class ShareChanged(DomainEvent):
    """Share links changed within a specific library session."""
    library_root: str = ""
    session_token: str = ""


@dataclass(frozen=True)
class FavoritesChanged(DomainEvent):
    """Favorites changed for one principal within a library session."""
    library_root: str = ""
    session_token: str = ""
    owner_key: str = ""
    paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class UserChanged(DomainEvent):
    """Users changed within a specific library session."""
    library_root: str = ""
    session_token: str = ""


@dataclass(frozen=True)
class InviteChanged(DomainEvent):
    """Invite codes changed within a specific library session."""
    library_root: str = ""
    session_token: str = ""


@dataclass(frozen=True)
class ActivityChanged(DomainEvent):
    """Activity log entries changed within a specific library session."""
    library_root: str = ""
    session_token: str = ""


@dataclass(frozen=True)
class PresenceChanged(DomainEvent):
    """Online presence changed within a specific library session."""
    library_root: str = ""
    session_token: str = ""


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


@dataclass(frozen=True)
class FileSystemChanged(DomainEvent):
    """A session-scoped file operation completed its projection updates."""
    library_root: str = ""
    session_token: str = ""
    kind: str = ""
    paths: tuple[str, ...] = ()
    old_paths: tuple[str, ...] = ()


# ── Metadata events ──────────────────────────────────────────────

@dataclass(frozen=True)
class TagsChanged(DomainEvent):
    """Tags were modified for a file."""
    file_path: str = ""
    new_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssetTagsChanged(DomainEvent):
    """Tags for one asset changed within a specific library session."""
    library_root: str = ""
    session_token: str = ""
    file_path: str = ""
    new_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class TagCatalogChanged(DomainEvent):
    """The tag catalog changed within a specific library session."""
    library_root: str = ""
    session_token: str = ""


@dataclass(frozen=True)
class NotesChanged(DomainEvent):
    """Notes were modified for a file."""
    file_path: str = ""


@dataclass(frozen=True)
class AssetNotesChanged(DomainEvent):
    """Notes for one asset changed within a specific library session."""
    library_root: str = ""
    session_token: str = ""
    file_path: str = ""


@dataclass(frozen=True)
class UrlsChanged(DomainEvent):
    """URLs were modified for a file."""
    file_path: str = ""
    new_urls: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssetUrlsChanged(DomainEvent):
    """URLs for one asset changed within a specific library session."""
    library_root: str = ""
    session_token: str = ""
    file_path: str = ""
    new_urls: tuple[str, ...] = ()


# ── Commerce events ─────────────────────────────────────────────

@dataclass(frozen=True)
class ShopItemChanged(DomainEvent):
    """The library-backed shop catalog changed."""
    library_root: str = ""
    session_token: str = ""
    paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class ShopOrderChanged(DomainEvent):
    """A shop order or its delivery lifecycle changed."""
    library_root: str = ""
    session_token: str = ""
    order_id: str = ""


@dataclass(frozen=True)
class QuotaChanged(DomainEvent):
    """A commerce download/order quota changed."""
    library_root: str = ""
    session_token: str = ""
    name: str = ""
