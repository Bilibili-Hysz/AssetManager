"""Gallery projection types, errors, constants and helpers.

These definitions are shared by the mixin modules and the concrete
``GalleryService``.  This module must not import ``GalleryService`` so the
mixin modules stay cycle-free.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from time import monotonic
from typing import Any

from AssetsManager.core.format_utils import format_size
from AssetsManager.domain.asset import IMAGE_EXTS

# Keep the historical logger name so gallery log records remain addressable
# under the original module path after the split into a subpackage.
_log = logging.getLogger("AssetsManager.application.gallery_service")

_SAFE_GALLERY_IMAGE_EXTS = IMAGE_EXTS - {".svg"}
_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400


@dataclass(frozen=True)
class GalleryTraversalLimits:
    """Upper bounds for one gallery projection walk.

    Defaults are sized for very large libraries (hundreds of GB / tens of
    thousands of entries).  A full 70k-file walk with per-file stat
    aggregation plus per-directory cover decode takes 30-60s on a real
    library, so the hard time budget is generous while a separate soft
    decode budget (``decode_soft_seconds``, default 70% of the hard one)
    drops cover dimension decodes once the walk runs long — the walk then
    always finishes and persists instead of failing with 429.  The bounds
    still cap runaway/abusive walks (entry budget ~3x a large real
    library).
    """

    max_entries: int = 150_000
    max_files: int = 150_000
    max_directories: int = 40_000
    max_depth: int = 64
    max_seconds: float = 60.0
    decode_soft_seconds: float | None = None


class GalleryTraversalLimitError(RuntimeError):
    """Raised when a gallery walk exceeds its bounded traversal budget."""

    def __init__(self, message: str, *, status: int = 413) -> None:
        super().__init__(message)
        self.status = status


class _IncrementalFallback(RuntimeError):
    """Signal that an incremental apply cannot proceed; rebuild fully."""


class _TraversalBudget:
    def __init__(self, limits: GalleryTraversalLimits) -> None:
        self.limits = limits
        self.started_at = monotonic()
        soft = limits.decode_soft_seconds
        self.decode_until = self.started_at + (
            soft if soft is not None else limits.max_seconds * 0.7
        )
        self.entries = 0
        self.files = 0
        self.directories = 0

    def _progress(self) -> str:
        return (
            f"entries={self.entries}, files={self.files}, "
            f"directories={self.directories}, elapsed={monotonic() - self.started_at:.1f}s"
        )

    def check_time(self) -> None:
        if monotonic() - self.started_at > self.limits.max_seconds:
            raise GalleryTraversalLimitError(
                f"Gallery traversal time budget exceeded ({self._progress()})",
                status=429,
            )

    def can_decode(self) -> bool:
        """Whether expensive per-image dimension decodes are still allowed.

        Cover decodes are best-effort metadata; once the walk has used its
        soft budget the walk keeps going and records cover paths without
        dimensions rather than failing the whole build.
        """
        return monotonic() < self.decode_until

    def enter_directory(self, depth: int) -> None:
        self.check_time()
        if depth > self.limits.max_depth:
            raise GalleryTraversalLimitError("Gallery traversal depth budget exceeded")
        self.directories += 1
        if self.directories > self.limits.max_directories:
            raise GalleryTraversalLimitError("Gallery traversal directory budget exceeded")

    def visit_entry(self, depth: int, *, is_file: bool) -> None:
        self.check_time()
        if depth > self.limits.max_depth:
            raise GalleryTraversalLimitError("Gallery traversal depth budget exceeded")
        self.entries += 1
        if self.entries > self.limits.max_entries:
            raise GalleryTraversalLimitError("Gallery traversal entry budget exceeded")
        if is_file:
            self.files += 1
            if self.files > self.limits.max_files:
                raise GalleryTraversalLimitError("Gallery traversal file budget exceeded")


@dataclass(frozen=True)
class GalleryImage:
    name: str
    path: str
    parent_path: str
    width: int | None
    height: int | None
    aspect_ratio: float | None
    modified: int
    size: int
    extension: str
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "kind": "artwork",
            "parent_path": self.parent_path,
            "width": self.width,
            "height": self.height,
            "aspect_ratio": self.aspect_ratio,
            "modified": self.modified,
            "size": self.size,
            "size_fmt": format_size(self.size),
            "extension": self.extension,
            "tags": list(self.tags),
        }


@dataclass(frozen=True)
class GalleryHome:
    featured: dict[str, Any] | None
    collections: list[dict[str, Any]]
    projects: list[dict[str, Any]]
    recent: list[dict[str, Any]]
    stats: dict[str, Any]

    def to_response(self) -> dict[str, Any]:
        return {
            "featured": self.featured,
            "collections": self.collections,
            "projects": self.projects,
            "recent": self.recent,
            "stats": self.stats,
        }


@dataclass(frozen=True)
class GalleryCollection:
    collection: dict[str, Any]
    children: list[dict[str, Any]]
    entries: list[dict[str, Any]]
    next_cursor: str | None = None

    def to_response(self) -> dict[str, Any]:
        return {
            "collection": self.collection,
            "children": self.children,
            "entries": self.entries,
            "next_cursor": self.next_cursor,
        }


@dataclass(frozen=True)
class GalleryResolve:
    kind: str
    path: str
    gallery_context: str
    workspace_context: str

    def to_response(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "path": self.path,
            "gallery_context": self.gallery_context,
            "workspace_context": self.workspace_context,
        }


@dataclass(frozen=True)
class _ImageRef:
    path: str
    modified: int


@dataclass(frozen=True)
class _QueuedChange:
    """One FileSystemChanged event queued for incremental application."""

    kind: str
    paths: tuple[str, ...]
    old_paths: tuple[str, ...]
    seq: int


@dataclass
class _StateNode:
    """One node of the incremental state tree.

    Mutable by convention: only the single incremental worker thread (or
    the synchronous build path) touches these after construction.
    """

    summary: dict[str, Any]  # response-form summary (mutated in place)
    direct_images: list[str]  # sorted direct image rel paths
    children: list[str]  # child rel paths in response order


@dataclass
class _HomeState:
    """Snapshot backing incremental home updates.

    ``nodes`` is the full state tree keyed by normalized relative path
    ("/" for the root), ``refs`` every library image with its mtime,
    ``files`` every file (idempotency registry), and ``generation`` the
    per-service monotonic counter stamped at build/apply time. The
    incremental applier only trusts events newer than this generation;
    any inconsistency falls back to a full rebuild.
    """

    node: dict[str, Any] | None
    nodes: dict[str, _StateNode]
    refs: list[_ImageRef]
    files: dict[str, tuple[int, int]]  # rel path -> (size, mtime)
    generation: int


# Pre-separation persisted projections carried transport URLs (``cover_url``,
# ``thumbnail_url``, ``image_url``) inside the home JSON.  Those keys are now
# assembled only at the LAN route layer, so a legacy row must have them
# stripped on load to keep the restored projection URL-free.
_LEGACY_URL_KEYS = frozenset({"cover_url", "thumbnail_url", "image_url"})


def _strip_legacy_url_fields(value: Any) -> Any:
    """Recursively drop legacy URL keys from a persisted projection value."""
    if isinstance(value, dict):
        return {
            key: _strip_legacy_url_fields(item)
            for key, item in value.items()
            if key not in _LEGACY_URL_KEYS
        }
    if isinstance(value, list):
        return [_strip_legacy_url_fields(item) for item in value]
    return value
