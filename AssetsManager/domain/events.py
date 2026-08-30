"""Domain events — immutable records of things that happened.

Domain events are pure data objects with no infrastructure dependencies.
They complement Qt signals for business logic that needs to be testable
without Qt, and can be used for undo/redo event sourcing in the future.
"""
from __future__ import annotations

from dataclasses import dataclass

from AssetsManager.core.event_contracts import DomainEventBase


@dataclass(frozen=True)
class DomainEvent(DomainEventBase):
    """Base class for all domain events."""


# ── Library events ───────────────────────────────────────────────

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
class MaintenanceChanged(DomainEvent):
    """A database maintenance or integrity run settled in a library session.

    Pure UI-notification, not projection data: deliberately absent from
    ``runtime_events.EVENT_DOMAINS``, so the RuntimeEventRouter (which only
    subscribes to mapped types) never routes it — publishing it is a no-op
    for projections by design.  Consumers subscribe on the event bus
    directly, e.g. the settings dialog's queued Qt bridge.
    """
    library_root: str = ""
    session_token: str = ""
    kind: str = "maintenance"  # "maintenance" | "integrity"


@dataclass(frozen=True)
class PresenceChanged(DomainEvent):
    """Online presence changed within a specific library session."""
    library_root: str = ""
    session_token: str = ""


# ── File events ──────────────────────────────────────────────────

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
class AssetTagsChanged(DomainEvent):
    """Tags for one asset changed within a specific library session.

    Single-asset mutations carry ``file_path`` (plus ``new_tags``).  Catalog
    wide operations such as ``rename_tag``/``delete_tag`` publish exactly one
    batch event with ``paths`` covering every affected asset and empty
    ``file_path``/``new_tags`` — consumers must re-read the per-asset state.
    """
    library_root: str = ""
    session_token: str = ""
    file_path: str = ""
    new_tags: tuple[str, ...] = ()
    paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class TagCatalogChanged(DomainEvent):
    """The tag catalog changed within a specific library session."""
    library_root: str = ""
    session_token: str = ""


@dataclass(frozen=True)
class AssetNotesChanged(DomainEvent):
    """Notes for one asset changed within a specific library session."""
    library_root: str = ""
    session_token: str = ""
    file_path: str = ""


@dataclass(frozen=True)
class AssetUrlsChanged(DomainEvent):
    """URLs for one asset changed within a specific library session."""
    library_root: str = ""
    session_token: str = ""
    file_path: str = ""
    new_urls: tuple[str, ...] = ()


# ── Quota events ────────────────────────────────────────────────

@dataclass(frozen=True)
class QuotaChanged(DomainEvent):
    """A download quota changed."""
    library_root: str = ""
    session_token: str = ""
    name: str = ""


# ── Collection events ────────────────────────────────────────────

@dataclass(frozen=True)
class CollectionChanged(DomainEvent):
    """A user collection (manual reference set or smart query view) changed.

    Catalog-wide mutations (create/rename/delete/query update) carry only
    ``collection_id``/``kind`` with empty ``paths``; membership changes
    (add/remove files) list every affected member path in ``paths`` so the
    runtime router can normalize them for projection invalidation.  The
    event never carries file data: collections are query views / reference
    sets, never file moves.
    """
    library_root: str = ""
    session_token: str = ""
    collection_id: int = 0
    kind: str = ""  # "manual" | "smart"
    paths: tuple[str, ...] = ()
