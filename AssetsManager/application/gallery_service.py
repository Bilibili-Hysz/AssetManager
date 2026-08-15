"""Gallery projection service for the LAN WebUI.

The Gallery is a read-only projection over the library filesystem.  It deliberately
stays separate from ``ProjectService`` because its hierarchy is based on visible
folders and artwork files rather than the user-configurable project depth.  The
service only returns library-relative paths and reuses the canonical session,
connection and tag services.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from stat import S_ISREG
from time import monotonic
from typing import Any, Callable, Iterable

from AssetsManager.application.context import ConnectionProvider, LibrarySession, session_operation
from AssetsManager.application.tag_service import TagService
from AssetsManager.core.database import DatabaseManager
from AssetsManager.core.format_utils import format_size
from AssetsManager.domain.asset import IMAGE_EXTS, assert_under_root
from AssetsManager.domain.errors import MissingPathError, PathEscapeError
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import FileSystemChanged
from AssetsManager.repositories.gallery_home_repository import GalleryHomeRepository

try:  # Pillow is a runtime dependency, but metadata must remain best-effort.
    from PIL import Image
except Exception:  # pragma: no cover - exercised only in minimal installations.
    Image = None  # type: ignore[assignment,misc]

_log = logging.getLogger(__name__)
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


class GalleryService:
    """Build bounded Gallery projections for one live library session."""

    def __init__(
        self,
        connection_provider: ConnectionProvider | None = None,
        session: LibrarySession | None = None,
        *,
        limits: GalleryTraversalLimits | None = None,
    ) -> None:
        self._connection_provider = connection_provider
        self._session = session
        self._limits = limits or GalleryTraversalLimits()
        self._tag_service = TagService(connection_provider=connection_provider, session=session)
        # Home projection cache: the full-library traversal plus per-image
        # PIL header decodes is expensive; a short TTL keeps repeated loads
        # cheap without going stale (a library edit shows up within 30s).
        self._home_cache: dict[str, tuple[float, "GalleryHome"]] = {}
        self._home_cache_lock = threading.Lock()
        self._home_cache_ttl = 30.0
        # Persisted projection (library database): survives process restarts
        # (a 286 GB library takes tens of seconds to build). FileSystemChanged
        # events delete it, and the TTL is a safety net for missed events.
        self._persisted_ttl = 3600.0
        # Background home projection: the full-library walk for very large
        # libraries takes tens of seconds, so it must never block a request.
        # Requests read the cache; a miss returns a "building" signal and a
        # daemon thread computes the projection and fills the cache.
        self._building: set[str] = set()
        self._build_lock = threading.Lock()
        # Failed builds back off before retrying: without this, a library
        # that cannot finish within the budget would be re-walked on every
        # polling request (a 30-60s full traversal each time, pinning the
        # CPU). A failure stamps a timestamp; retries wait it out.
        self._build_failures: dict[str, float] = {}
        self._build_backoff = 60.0
        self._refresh_timer: threading.Timer | None = None
        # Incremental-update machinery: per-root pending event queue, a
        # short debounce, and per-root snapshots of the last build. All
        # counters share one lock so seq/generation ordering stays exact.
        self._pending_events: dict[str, list[_QueuedChange]] = {}
        self._pending_lock = threading.Lock()
        self._generation_lock = threading.Lock()
        self._incremental_debounce = 2.0
        self._inc_timer: threading.Timer | None = None
        self._home_states: dict[str, _HomeState] = {}
        self._home_generation = 0
        # Incremental telemetry: applied event count and fallback count since
        # construction (written only by the incremental worker thread).
        self._incremental_applied = 0
        self._incremental_fallbacks = 0
        self._closed = False
        self._fs_subscription = get_event_bus().subscribe_weak(
            FileSystemChanged, self._on_file_system_changed
        )

    def _on_file_system_changed(self, event: FileSystemChanged) -> None:
        """Queue library changes for incremental application, falling back
        to the full rebuild semantics when no snapshot is available."""
        if event.kind in {"gallery", "shop"}:
            return
        root_key = str(Path(event.library_root).resolve())
        with self._home_cache_lock:
            has_state = root_key in self._home_states and root_key in self._home_cache
        if not has_state:
            # No snapshot: run the historical full-rebuild invalidation.
            self._invalidate_and_schedule_full(root_key)
            return
        with self._generation_lock:
            self._home_generation += 1
            seq = self._home_generation
        with self._pending_lock:
            queue = self._pending_events.setdefault(root_key, [])
            queue.append(_QueuedChange(
                event.kind, tuple(event.paths), tuple(event.old_paths), seq,
            ))
            if len(queue) > self._MAX_PENDING_EVENTS:
                # Queue overflow: fall back to the full rebuild semantics.
                self._pending_events.pop(root_key, None)
                overflow = True
            else:
                overflow = False
        if overflow:
            self._invalidate_and_schedule_full(root_key)
            return
        self._schedule_incremental_apply(root_key)

    _MAX_PENDING_EVENTS = 500

    @staticmethod
    def _cancel_opposing_changes(changes: list[_QueuedChange]) -> list[_QueuedChange]:
        """Collapse bursts that net out before applying them.

        created(P)-then-deleted(P) cancels both (net zero against the
        snapshot); a move round-trip A->B then B->A cancels; a move chain
        A->B then B->C folds into A->C. Multi-path batch events pass
        through untouched.
        """
        result: list[_QueuedChange] = []
        for change in changes:
            if len(change.paths) != 1:
                result.append(change)
                continue
            path = change.paths[0]
            if change.kind == "deleted":
                for i in range(len(result) - 1, -1, -1):
                    prev = result[i]
                    if (
                        prev.kind in {"created", "copied", "restored"}
                        and prev.paths and prev.paths[0] == path
                    ):
                        result.pop(i)
                        break
                else:
                    result.append(change)
            elif change.kind == "moved" and len(change.old_paths) == 1:
                src, dst = change.old_paths[0], path
                cancelled = False
                for i in range(len(result) - 1, -1, -1):
                    prev = result[i]
                    if (
                        prev.kind == "moved" and len(prev.old_paths) == 1
                        and prev.paths[0] == src and prev.old_paths[0] == dst
                    ):
                        # Round-trip A->B then B->A: net zero.
                        result.pop(i)
                        cancelled = True
                        break
                if not cancelled:
                    for i in range(len(result) - 1, -1, -1):
                        prev = result[i]
                        if (
                            prev.kind == "moved" and len(prev.old_paths) == 1
                            and prev.paths[0] == src
                        ):
                            # Chain A->B then B->C folds to A->C.
                            result[i] = _QueuedChange(
                                "moved", (dst,), prev.old_paths, change.seq,
                            )
                            break
                    else:
                        result.append(change)
            else:
                result.append(change)
        return result

    def _invalidate_and_schedule_full(self, root_key: str) -> None:
        """Drop the cached/state/persisted projection and schedule a full
        rebuild (debounced so a burst of events rebuilds once)."""
        with self._home_cache_lock:
            self._home_cache.pop(root_key, None)
            self._home_states.pop(root_key, None)
        try:
            self._persist_repository(root_key).delete()
        except Exception:
            _log.debug("Gallery home persisted projection delete failed", exc_info=True)
        with self._build_lock:
            if self._refresh_timer is not None:
                self._refresh_timer.cancel()
            self._refresh_timer = threading.Timer(
                self._home_cache_ttl, self._ensure_home_building, args=(root_key,)
            )
            self._refresh_timer.daemon = True
            self._refresh_timer.start()

    def _schedule_incremental_apply(self, root_key: str) -> None:
        """Debounce pending changes into one short apply window."""
        if self._closed:
            return
        with self._build_lock:
            if self._inc_timer is not None:
                self._inc_timer.cancel()
            self._inc_timer = threading.Timer(
                self._incremental_debounce, self._apply_pending_home, args=(root_key,)
            )
            self._inc_timer.daemon = True
            self._inc_timer.start()

    def _apply_pending_home(self, root_key: str) -> None:
        """Apply queued changes incrementally; fall back to a full rebuild
        on any inconsistency, budget overrun, or concurrent full build."""
        with self._pending_lock:
            changes = self._pending_events.pop(root_key, None)
        if not changes:
            return
        with self._home_cache_lock:
            state = self._home_states.get(root_key)
            cached = self._home_cache.get(root_key)
        if state is None or cached is None:
            self._invalidate_and_schedule_full(root_key)
            return
        changes = [change for change in changes if change.seq > state.generation]
        changes = self._cancel_opposing_changes(changes)
        if not changes:
            return
        with self._build_lock:
            busy = root_key in self._building
            if not busy:
                self._building.add(root_key)
        if busy:
            # A full rebuild is running; its result supersedes the snapshot.
            # Re-queue briefly instead of racing it. (Scheduling must happen
            # outside _build_lock: _schedule_incremental_apply takes it, and
            # threading.Lock is not reentrant.)
            with self._pending_lock:
                self._pending_events.setdefault(root_key, []).extend(changes)
            self._schedule_incremental_apply(root_key)
            return
        try:
            home = cached[1]
            for change in changes:
                home = self._apply_change(root_key, state, change, home)
            self._incremental_applied += len(changes)
            with self._home_cache_lock:
                with self._generation_lock:
                    self._home_generation += 1
                    state.generation = self._home_generation
                self._home_cache[root_key] = (time.monotonic(), home)
            self._save_persisted_projection(root_key, home)
        except Exception:
            self._incremental_fallbacks += 1
            _log.info(
                "Incremental gallery apply fell back to a full rebuild "
                "(applied=%d, fallbacks=%d)",
                self._incremental_applied, self._incremental_fallbacks,
                exc_info=True,
            )
            self._invalidate_and_schedule_full(root_key)
        finally:
            with self._build_lock:
                self._building.discard(root_key)

    @property
    def incremental_stats(self) -> tuple[int, int]:
        """Return (applied_event_count, fallback_count) since construction."""
        return self._incremental_applied, self._incremental_fallbacks

    def close(self) -> None:
        """Stop background work; called when the owning session closes."""
        self._closed = True
        with self._build_lock:
            if self._refresh_timer is not None:
                self._refresh_timer.cancel()
                self._refresh_timer = None
            if self._inc_timer is not None:
                self._inc_timer.cancel()
                self._inc_timer = None
        try:
            self._fs_subscription.close()
        except Exception:
            pass

    def stop(self) -> None:
        """Lifecycle-adapter alias so runtime teardown can close this service."""
        self.close()

    @session_operation
    def get_home_cached(
        self, library_root: str | Path
    ) -> "GalleryHome | None":
        """Return a home projection, or None when a build is needed.

        Fresh memory cache -> value. Stale memory -> the stale value plus
        a background rebuild. No memory -> try the persisted projection in
        the library database (served immediately, rebuilt in the
        background); no persisted projection -> None plus a background
        build.
        """
        root = Path(library_root).resolve()
        root_key = str(root)
        now = time.monotonic()
        with self._home_cache_lock:
            cached = self._home_cache.get(root_key)
            if cached is not None:
                if now - cached[0] >= self._home_cache_ttl:
                    # Stale: serve it now, rebuild in the background.
                    self._ensure_home_building(root_key)
                return cached[1]
            persisted = self._load_persisted_projection(root_key)
            if persisted is not None:
                self._home_cache[root_key] = (now, persisted)
                self._ensure_home_building(root_key)
                return persisted
        self._ensure_home_building(root_key)
        return None

    def _persist_repository(self, root_key: str) -> GalleryHomeRepository:
        conn = self._connection(Path(root_key).resolve(), None, self._connection_provider)
        if conn is None:
            raise RuntimeError("Gallery persistence requires a connection provider")
        return GalleryHomeRepository(conn)

    def _load_persisted_projection(self, root_key: str) -> "GalleryHome | None":
        """Load the persisted projection within its TTL, or None."""
        try:
            row = self._persist_repository(root_key).get()
            if row is None:
                return None
            saved_at, projection_json = row
            if time.time() - saved_at > self._persisted_ttl:
                return None
            projection = json.loads(projection_json)
            if not isinstance(projection, dict):
                return None
            projection = _strip_legacy_url_fields(projection)
            return GalleryHome(
                featured=projection.get("featured"),
                collections=projection.get("collections", []),
                projects=projection.get("projects", []),
                recent=projection.get("recent", []),
                stats=projection.get("stats", {}),
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError, sqlite3.Error):
            _log.debug("Gallery home persisted projection unreadable for %s", root_key, exc_info=True)
            return None

    def _save_persisted_projection(self, root_key: str, home: "GalleryHome") -> None:
        """Persist the projection into the library database."""
        try:
            self._persist_repository(root_key).save(
                time.time(), json.dumps(home.to_response(), ensure_ascii=False)
            )
        except (OSError, sqlite3.Error):
            _log.debug("Gallery home persisted projection write failed", exc_info=True)

    def prewarm_home(
        self,
        library_root: str | Path,
        *,
        pre_wait: Callable[[], None] | None = None,
    ) -> None:
        """Kick off a background home projection build (idempotent).

        Called after the LAN server starts so the first /gallery visit
        finds a warm cache instead of a building state. ``pre_wait`` (if
        given) runs on the build thread before the walk — used to wait out
        the LAN scanner so the two full-library traversals do not compete
        for disk I/O. Never blocks the caller.
        """
        try:
            self._ensure_home_building(
                str(Path(library_root).resolve()), pre_wait=pre_wait
            )
        except Exception:
            _log.debug("Gallery home prewarm skipped", exc_info=True)

    def _ensure_home_building(
        self,
        root_key: str,
        *,
        pre_wait: Callable[[], None] | None = None,
    ) -> None:
        """Start a background home build for *root_key* unless one is
        already running, the service is closed, or a recent failure is
        still backing off (in which case a retry timer is re-armed).

        Idempotence comes from the ``_building`` set, not the cache, so
        callers may invoke this while holding ``_home_cache_lock`` (the
        stale-value path) without deadlocking.
        """
        if self._closed:
            return
        with self._build_lock:
            if root_key in self._building:
                return
            last_failure = self._build_failures.get(root_key)
            if last_failure is not None:
                remaining = self._build_backoff - (monotonic() - last_failure)
                if remaining > 0:
                    self._schedule_retry(root_key, remaining)
                    return
            self._building.add(root_key)
        thread = threading.Thread(
            target=self._build_home_background,
            args=(root_key,),
            kwargs={"pre_wait": pre_wait},
            daemon=True,
        )
        thread.start()

    def _schedule_retry(self, root_key: str, delay: float) -> None:
        """Re-arm the single retry timer (callers hold ``_build_lock``).

        Shared with ``_invalidate_and_schedule_full``: whichever reason
        triggers next wins, and the timer is always single.
        """
        if self._refresh_timer is not None:
            self._refresh_timer.cancel()
        self._refresh_timer = threading.Timer(
            delay, self._ensure_home_building, args=(root_key,)
        )
        self._refresh_timer.daemon = True
        self._refresh_timer.start()

    def _build_home_background(
        self, root_key: str, *, pre_wait: Callable[[], None] | None = None
    ) -> None:
        """Compute the projection off the request path; failures leave the
        cache empty, stamp the failure timestamp (retries then back off
        instead of re-walking on every poll), and let the next request
        retry after the backoff."""
        try:
            if pre_wait is not None:
                pre_wait()
            self._compute_home(root_key)
        except Exception:
            _log.exception("Background gallery home build failed for %s", root_key)
            with self._build_lock:
                self._build_failures[root_key] = monotonic()
        else:
            with self._build_lock:
                self._build_failures.pop(root_key, None)
        finally:
            with self._build_lock:
                self._building.discard(root_key)

    @staticmethod
    def _normalize_relative_path(value: str | Path | None) -> str:
        text = str(value or "").replace("\\", "/").strip()
        if not text or text == "." or text == "/":
            return ""
        if "\x00" in text:
            raise ValueError("path contains a NUL byte")
        parts: list[str] = []
        for part in text.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                raise ValueError("path escape detected")
            parts.append(part)
        return "/".join(parts)

    @staticmethod
    def _parent_path(relative_path: str) -> str | None:
        if not relative_path:
            return None
        parent = relative_path.rsplit("/", 1)[0] if "/" in relative_path else ""
        return parent

    @classmethod
    def _image_dimensions(cls, path: Path) -> tuple[int | None, int | None, float | None]:
        if Image is None:
            return None, None, None
        try:
            with Image.open(path) as image:
                width, height = image.size
            if width <= 0 or height <= 0:
                return None, None, None
            return width, height, width / height
        except Exception:
            return None, None, None

    @classmethod
    def _describe_image(
        cls,
        root: Path,
        relative_path: str,
        *,
        stat_result: os.stat_result | None = None,
        budget: "_TraversalBudget | None" = None,
    ) -> dict[str, Any] | None:
        target = (root / relative_path).resolve()
        try:
            target.relative_to(root)
            if target.suffix.lower() not in _SAFE_GALLERY_IMAGE_EXTS:
                return None
            if stat_result is None:
                stat_result = target.stat()
            # One stat serves both the file check and the reparse-point
            # check; the resolved target's chain was already vetted by the
            # caller (walk filter or _resolve_existing).
            if (
                not S_ISREG(int(stat_result.st_mode))
                or int(getattr(stat_result, "st_file_attributes", 0))
                & _FILE_ATTRIBUTE_REPARSE_POINT
            ):
                return None
        except (OSError, ValueError):
            return None
        width = height = aspect_ratio = None
        if budget is None or budget.can_decode():
            # Dimension decode is best-effort: past the soft budget the walk
            # keeps the cover path and skips the per-image decode so very
            # large libraries still finish within the hard budget.
            width, height, aspect_ratio = cls._image_dimensions(target)
        parent = cls._parent_path(relative_path)
        return GalleryImage(
            name=target.name,
            path=relative_path,
            parent_path=parent or "",
            width=width,
            height=height,
            aspect_ratio=aspect_ratio,
            modified=int(stat_result.st_mtime),
            size=int(stat_result.st_size),
            extension=target.suffix.lower(),
        ).to_dict()

    @classmethod
    def _path_contains_reparse_point(cls, root: Path, target: Path) -> bool:
        """Check every component between root and target without following it.

        Only called for public entry paths (resolve_existing, build entry);
        the recursive walk skips it because every child entry already
        passed the scandir-level reparse filter.
        """
        try:
            relative = target.relative_to(root)
        except ValueError:
            return True
        current = root
        for part in relative.parts:
            current /= part
            try:
                if os.path.islink(current):
                    return True
                stat_result = os.lstat(current)
            except OSError:
                return True
            if bool(
                int(getattr(stat_result, "st_file_attributes", 0))
                & _FILE_ATTRIBUTE_REPARSE_POINT
            ):
                return True
        return False

    @staticmethod
    def _connection(
        library_root: str | Path,
        db_conn: sqlite3.Connection | None,
        provider: ConnectionProvider | None,
    ) -> sqlite3.Connection | None:
        if db_conn is not None:
            return DatabaseManager.validate_connection_owner(
                Path(library_root).resolve(), db_conn, allow_unmanaged=True
            )
        if provider is None:
            return None
        root = Path(library_root).resolve()
        return DatabaseManager.validate_connection_owner(root, provider(root), allow_unmanaged=True)

    def _resolve_existing(self, root: Path, relative_path: str | Path | None) -> tuple[str, Path]:
        normalized = self._normalize_relative_path(relative_path)
        candidate = root / normalized
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise PathEscapeError(str(candidate), str(root)) from exc
        if self._path_contains_reparse_point(root, candidate):
            raise MissingPathError(normalized)
        try:
            target = assert_under_root(candidate, root)
        except PathEscapeError:
            raise
        except OSError as exc:
            raise MissingPathError(normalized) from exc
        if not target.exists() or self._path_contains_reparse_point(root, candidate):
            raise MissingPathError(normalized)
        # Resolve again from the canonical path immediately before inspection.
        target = assert_under_root(target, root)
        return normalized, target

    def _visible_entries(
        self, target: Path, budget: _TraversalBudget, depth: int
    ) -> list[tuple[os.DirEntry[str], os.stat_result | None]]:
        """Materialize only entries which have already consumed traversal
        budget.

        The reparse filter runs before any stat: symlink/junction come from
        the scandir entry attributes (no syscall), and only files pay the
        single ``stat(follow_symlinks=False)`` that ``_build_node`` reuses
        for size/mtime aggregation — that same call also surfaces the
        reparse-point attribute so exotic reparse files (OneDrive
        placeholders, ...) are skipped. Directories never stat: the
        symlink/junction checks above cover every reparse class that can
        escape the library tree.
        """
        visible: list[tuple[os.DirEntry[str], os.stat_result | None]] = []
        try:
            with os.scandir(target) as iterator:
                for entry in iterator:
                    budget.check_time()
                    try:
                        is_symlink = entry.is_symlink()
                        is_junction = False
                        is_junction_fn = getattr(entry, "is_junction", None)
                        if callable(is_junction_fn):
                            is_junction = is_junction_fn()
                    except OSError:
                        is_symlink = is_junction = False
                    if is_symlink or is_junction:
                        budget.visit_entry(depth + 1, is_file=False)
                        continue
                    try:
                        is_file = entry.is_file(follow_symlinks=False)
                    except OSError:
                        is_file = False
                    budget.visit_entry(depth + 1, is_file=is_file)
                    if entry.name.startswith("."):
                        continue
                    if not is_file:
                        # Directory: no stat (see docstring); _build_node
                        # recurses into it with stat_result=None.
                        visible.append((entry, None))
                        continue
                    try:
                        stat_result = entry.stat(follow_symlinks=False)
                    except OSError:
                        stat_result = None
                    if (
                        stat_result is not None
                        and int(getattr(stat_result, "st_file_attributes", 0))
                        & _FILE_ATTRIBUTE_REPARSE_POINT
                    ):
                        continue
                    visible.append((entry, stat_result))
        except OSError:
            return visible
        budget.check_time()
        visible.sort(key=lambda item: item[0].name.casefold())
        budget.check_time()
        return visible

    def _build_node(
        self,
        root: Path,
        relative_path: str,
        target: Path,
        *,
        include_entries: bool,
        budget: _TraversalBudget,
        depth: int,
        image_refs: list[_ImageRef] | None = None,
        node_counts: dict[str, int] | None = None,
        state_nodes: dict[str, _StateNode] | None = None,
        known_files: dict[str, tuple[int, int]] | None = None,
        skip_reparse_check: bool = False,
    ) -> dict[str, Any] | None:
        if not skip_reparse_check:
            # Public entry points resolve and re-check the chain once. The
            # recursion passes skip_reparse_check=True: every child already
            # passed the scandir-level reparse filter in _visible_entries,
            # and re-walking the component chain per directory costs tens of
            # thousands of lstat syscalls on large libraries.
            try:
                target = assert_under_root(target.resolve(), root)
                if self._path_contains_reparse_point(root, target):
                    return None
            except (OSError, PathEscapeError, ValueError):
                return None
        budget.enter_directory(depth)
        child_nodes: list[dict[str, Any]] = []
        direct_images: list[tuple[str, os.stat_result]] = []
        total_size = 0
        file_count = 0
        direct_file_count = 0
        latest_modified = 0

        for entry, stat_result in self._visible_entries(target, budget, depth):
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                is_file = entry.is_file(follow_symlinks=False)
            except OSError:
                continue
            child_relative = "/".join(part for part in (relative_path, entry.name) if part)
            child_path = Path(entry.path)

            if is_dir:
                child_node = self._build_node(
                    root,
                    child_relative,
                    child_path,
                    include_entries=False,
                    budget=budget,
                    depth=depth + 1,
                    image_refs=image_refs,
                    node_counts=node_counts,
                    state_nodes=state_nodes,
                    known_files=known_files,
                    skip_reparse_check=True,
                )
                if child_node is None:
                    continue
                child_nodes.append(child_node)
                total_size += int(child_node["size"])
                file_count += int(child_node["file_count"])
                latest_modified = max(latest_modified, int(child_node["modified"]))
                continue

            if not is_file:
                continue
            if stat_result is None:
                # The scan pre-fetched the stat; only retry when it failed.
                try:
                    stat_result = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
            total_size += int(stat_result.st_size)
            file_count += 1
            direct_file_count += 1
            modified = int(stat_result.st_mtime)
            latest_modified = max(latest_modified, modified)
            if known_files is not None:
                known_files[child_relative] = (int(stat_result.st_size), modified)
            if entry.name.lower().endswith(tuple(_SAFE_GALLERY_IMAGE_EXTS)):
                direct_images.append((child_relative, stat_result))
                if image_refs is not None:
                    image_refs.append(_ImageRef(child_relative, modified))

        if not child_nodes and direct_file_count == 0:
            return None

        child_nodes.sort(key=lambda item: (-int(item["modified"]), str(item["name"]).casefold()))
        direct_images.sort(key=lambda item: item[0].casefold())
        cover_path = (
            direct_images[0][0]
            if direct_images
            else next((str(child["cover_path"]) for child in child_nodes if child.get("cover_path")), None)
        )
        cover = self._describe_image(root, cover_path, budget=budget) if cover_path else None
        normalized = self._normalize_relative_path(relative_path)
        is_root = not normalized
        kind = "collection" if is_root or child_nodes else "project"
        if node_counts is not None and not is_root:
            node_counts[kind] = node_counts.get(kind, 0) + 1
        node: dict[str, Any] = {
            "name": root.name if is_root else target.name,
            "path": normalized,
            "kind": kind,
            "parent_path": self._parent_path(normalized),
            "cover_path": cover_path,
            "width": cover.get("width") if cover else None,
            "height": cover.get("height") if cover else None,
            "aspect_ratio": cover.get("aspect_ratio") if cover else None,
            "modified": latest_modified,
            "size": total_size,
            "size_fmt": format_size(total_size),
            "file_count": file_count,
            "artwork_count": len(direct_images) + sum(int(child["artwork_count"]) for child in child_nodes),
            "child_count": len(child_nodes),
            "tags": [],
        }
        if include_entries:
            node["children"] = [self._summary(child) for child in child_nodes]
            node["entries"] = [
                described
                for path, stat_result in direct_images
                if (described := self._describe_image(root, path, stat_result=stat_result, budget=budget))
            ]
        if state_nodes is not None:
            state_nodes[normalized or "/"] = _StateNode(
                summary=self._summary(node),
                direct_images=[path for path, _stat_result in direct_images],
                children=[str(child["path"]) for child in child_nodes],
            )
        return node

    @staticmethod
    def _summary(node: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in node.items() if key not in {"children", "entries"}}

    # ── Incremental appliers (file-level v1; anything else falls back) ──

    @staticmethod
    def _parent_rel(rel: str) -> str:
        return "/".join(part for part in rel.split("/")[:-1] if part)

    def _rel(self, root: Path, absolute: str) -> str | None:
        """Normalize an absolute event path to a library-relative path."""
        try:
            target = assert_under_root(Path(absolute).resolve(), root)
        except (OSError, PathEscapeError, ValueError):
            return None
        return self._normalize_relative_path(str(target.relative_to(root)))

    def _apply_change(
        self,
        root_key: str,
        state: _HomeState,
        change: _QueuedChange,
        home: GalleryHome,
    ) -> GalleryHome:
        root = Path(root_key).resolve()
        if change.kind in {"created", "copied", "restored"}:
            for path in change.paths:
                try:
                    is_dir = Path(path).is_dir()
                except OSError:
                    is_dir = False
                if is_dir:
                    home = self._apply_dir_event(root, state, home, path, None, "created")
                else:
                    home = self._apply_file_event(root, state, home, path, None, "created")
        elif change.kind == "deleted":
            for path in change.paths:
                rel = self._rel(root, path)
                if rel is not None and rel in state.nodes:
                    home = self._apply_dir_event(root, state, home, path, None, "deleted")
                else:
                    home = self._apply_file_event(root, state, home, path, None, "deleted")
        elif change.kind == "moved":
            for new_path, old_path in zip(change.paths, change.old_paths):
                try:
                    is_dir = Path(new_path).is_dir()
                except OSError:
                    is_dir = False
                if is_dir:
                    home = self._apply_dir_event(root, state, home, new_path, old_path, "moved")
                else:
                    home = self._apply_file_event(root, state, home, new_path, old_path, "moved")
        else:
            raise _IncrementalFallback(f"unsupported event kind {change.kind}")
        return home

    @staticmethod
    def _collect_descendants(state: _HomeState, key: str) -> list[str]:
        """Return *key* plus every descendant state key (depth-first)."""
        collected: list[str] = []
        stack = [key]
        while stack:
            current = stack.pop()
            collected.append(current)
            node = state.nodes.get(current)
            if node is not None:
                stack.extend(node.children)
        return collected

    def _apply_dir_event(
        self,
        root: Path,
        state: _HomeState,
        home: GalleryHome,
        new_abs: str,
        old_abs: str | None,
        kind: str,
    ) -> GalleryHome:
        conn = self._connection(root, None, self._connection_provider)
        if kind == "created":
            rel = self._rel(root, new_abs)
            if rel is None or not rel:
                raise _IncrementalFallback("directory path escapes the library")
            if rel in state.nodes:
                return home  # idempotent guard
            parent_key = self._parent_rel(rel) or "/"
            parent = state.nodes.get(parent_key)
            if parent is None:
                raise _IncrementalFallback(f"unknown parent {parent_key}")
            # Bounded sub-walk of the new subtree (raises the traversal limit
            # error on runaway trees; the caller falls back to a full build).
            sub_refs: list[_ImageRef] = []
            sub_nodes: dict[str, _StateNode] = {}
            sub_files: dict[str, tuple[int, int]] = {}
            try:
                sub_root = self._build_node(
                    root, rel, Path(new_abs),
                    include_entries=False,
                    budget=_TraversalBudget(self._limits),
                    depth=len(rel.split("/")),
                    image_refs=sub_refs,
                    node_counts=None,
                    state_nodes=sub_nodes,
                    known_files=sub_files,
                )
            except GalleryTraversalLimitError as exc:
                raise _IncrementalFallback("directory sub-walk exceeded budget") from exc
            if sub_root is None:
                # Empty directories are pruned by the projection: no-op.
                return home
            summary = sub_nodes[rel].summary
            state.nodes.update(sub_nodes)
            state.files.update(sub_files)
            state.refs.extend(sub_refs)
            parent.children.append(rel)
            if parent.summary.get("kind") == "project":
                parent.summary["kind"] = "collection"
            self._resort_children(state, parent_key)
            self._bump_ancestors(
                state, parent_key,
                size_delta=int(summary["size"]),
                file_delta=int(summary["file_count"]),
                artwork_delta=int(summary["artwork_count"]),
                modified_candidate=int(summary["modified"]),
                child_delta=1,
            )
            return self._recompose_home(root, state, conn)

        if kind == "deleted":
            rel = self._rel(root, new_abs)
            if rel is None or not rel or rel not in state.nodes:
                return home  # unknown or already applied
            node = state.nodes[rel]
            summary = node.summary
            parent_key = self._parent_rel(rel) or "/"
            parent = state.nodes.get(parent_key)
            if parent is None:
                raise _IncrementalFallback(f"unknown parent {parent_key}")
            parent_sole_content = (
                int(parent.summary["file_count"]) == int(summary["file_count"])
                and len(parent.children) == 1
            )
            if (
                not parent_sole_content
                and int(parent.summary["modified"]) == int(summary["modified"])
            ):
                raise _IncrementalFallback("deleted directory carried the max mtime")
            descendants = self._collect_descendants(state, rel)
            for key in descendants:
                state.nodes.pop(key, None)
            prefix = rel + "/"
            state.files = {
                path: entry for path, entry in state.files.items()
                if not path.startswith(prefix)
            }
            state.refs = [ref for ref in state.refs if not ref.path.startswith(prefix)]
            parent.children.remove(rel)
            self._bump_ancestors(
                state, parent_key,
                size_delta=-int(summary["size"]),
                file_delta=-int(summary["file_count"]),
                artwork_delta=-int(summary["artwork_count"]),
                modified_candidate=-1,
                child_delta=-1,
            )
            self._prune_empty_chain(state, parent_key)
            return self._recompose_home(root, state, conn)

        if kind == "moved" and old_abs is not None:
            rel_old = self._rel(root, old_abs)
            rel_new = self._rel(root, new_abs)
            if rel_old is None or rel_new is None or not rel_old or not rel_new:
                raise _IncrementalFallback("directory move escapes the library")
            if rel_old == rel_new:
                return home
            if rel_old not in state.nodes:
                raise _IncrementalFallback("moved source directory unknown")
            if rel_new in state.nodes:
                raise _IncrementalFallback("moved destination directory already known")
            if self._parent_rel(rel_old) == self._parent_rel(rel_new):
                # Same-parent rename: rewrite the subtree keys in place.
                keys = self._collect_descendants(state, rel_old)
                for key in keys:
                    new_key = rel_new + key[len(rel_old):]
                    moved_node = state.nodes.pop(key)
                    moved_node.summary["path"] = new_key
                    moved_node.summary["name"] = new_key.rsplit("/", 1)[-1]
                    moved_node.summary["parent_path"] = self._parent_rel(new_key)
                    moved_node.direct_images = [
                        rel_new + path[len(rel_old):] for path in moved_node.direct_images
                    ]
                    moved_node.children = [
                        rel_new + path[len(rel_old):] for path in moved_node.children
                    ]
                    cover = moved_node.summary.get("cover_path")
                    if cover:
                        moved_node.summary["cover_path"] = (
                            rel_new + cover[len(rel_old):]
                        )
                    state.nodes[new_key] = moved_node
                state.files = {
                    (
                        rel_new + path[len(rel_old):]
                        if path == rel_old or path.startswith(rel_old + "/")
                        else path
                    ): entry
                    for path, entry in state.files.items()
                }
                state.refs = [
                    _ImageRef(rel_new + ref.path[len(rel_old):], ref.modified)
                    if ref.path == rel_old or ref.path.startswith(rel_old + "/")
                    else ref
                    for ref in state.refs
                ]
                parent_key = self._parent_rel(rel_old) or "/"
                parent = state.nodes.get(parent_key)
                if parent is None:
                    raise _IncrementalFallback("moved parent unknown")
                parent.children = [
                    rel_new if path == rel_old else path for path in parent.children
                ]
                # Re-describe covers for the moved node and every ancestor:
                # their cover_paths may have pointed into the renamed subtree.
                cover_keys = [rel_new]
                key = parent_key
                while True:
                    cover_keys.append(key)
                    if key == "/":
                        break
                    key = self._parent_rel(key) or "/"
                for key in cover_keys:
                    if key in state.nodes:
                        self._recompute_cover(root, state, key)
                self._resort_children(state, parent_key)
                return self._recompose_home(root, state, conn)

            # Cross-parent move: delete from the old parent, then sub-walk
            # the destination (both guarded; any inconsistency falls back).
            home = self._apply_dir_event(root, state, home, old_abs, None, "deleted")
            return self._apply_dir_event(root, state, home, new_abs, None, "created")

        raise _IncrementalFallback(f"unsupported directory event {kind}")

    def _prune_empty_chain(self, state: _HomeState, start_key: str) -> None:
        """Remove nodes that became empty (no files, no child dirs),
        matching the build's pruning rule, cascading up to the root."""
        key = start_key
        while key != "/":
            node = state.nodes.get(key)
            if node is None or node.children or int(node.summary["file_count"]) > 0:
                # Not empty: only the kind may have flipped.
                if node is not None and not node.children:
                    node.summary["kind"] = "project"
                return
            parent_key = self._parent_rel(key) or "/"
            parent = state.nodes.get(parent_key)
            if parent is None:
                raise _IncrementalFallback(f"missing parent {parent_key}")
            state.nodes.pop(key, None)
            if key in parent.children:
                parent.children.remove(key)
            key = parent_key

    def _apply_file_event(
        self,
        root: Path,
        state: _HomeState,
        home: GalleryHome,
        new_abs: str,
        old_abs: str | None,
        kind: str,
    ) -> GalleryHome:
        conn = self._connection(root, None, self._connection_provider)
        if kind == "created":
            rel = self._rel(root, new_abs)
            if rel is None:
                raise _IncrementalFallback("created path escapes the library")
            if rel in state.files:
                return home  # idempotent guard: already applied
            target = Path(new_abs)
            try:
                if target.is_dir():
                    raise _IncrementalFallback("directory events are not incremental yet")
                st = target.stat()
            except OSError as exc:
                raise _IncrementalFallback("cannot stat created path") from exc
            is_image = target.suffix.lower() in _SAFE_GALLERY_IMAGE_EXTS
            parent_key = self._parent_rel(rel) or "/"
            parent = state.nodes.get(parent_key)
            if parent is None:
                raise _IncrementalFallback(f"unknown parent {parent_key}")
            state.files[rel] = (int(st.st_size), int(st.st_mtime))
            if is_image:
                state.refs.append(_ImageRef(rel, int(st.st_mtime)))
                parent.direct_images.append(rel)
                parent.direct_images.sort(key=lambda path: path.casefold())
                if parent.summary.get("cover_path") is None or parent.direct_images[0] == rel:
                    self._recompute_cover(root, state, parent_key)
            self._bump_ancestors(
                state, parent_key,
                size_delta=int(st.st_size),
                file_delta=1,
                artwork_delta=1 if is_image else 0,
                modified_candidate=int(st.st_mtime),
            )
            return self._recompose_home(root, state, conn)

        if kind == "deleted":
            rel = self._rel(root, new_abs)
            if rel is None or rel not in state.files:
                return home  # unknown or already applied
            size, mtime = state.files.pop(rel)
            parent_key = self._parent_rel(rel) or "/"
            parent = state.nodes.get(parent_key)
            if parent is None:
                raise _IncrementalFallback(f"unknown parent {parent_key}")
            parent_sole_content = int(parent.summary["file_count"]) == 1 and not parent.children
            if not parent_sole_content and int(parent.summary["modified"]) == mtime:
                # The subtree maximum left with this file; we cannot compute
                # the next maximum without re-walking. (When it is the
                # parent's only content the parent is pruned instead, so the
                # maximum is irrelevant.)
                raise _IncrementalFallback("deleted file carried the max mtime")
            is_image = any(ref.path == rel for ref in state.refs)
            if is_image:
                state.refs = [ref for ref in state.refs if ref.path != rel]
                if rel in parent.direct_images:
                    parent.direct_images.remove(rel)
                if parent.summary.get("cover_path") == rel:
                    self._recompute_cover(root, state, parent_key)
            self._bump_ancestors(
                state, parent_key,
                size_delta=-size,
                file_delta=-1,
                artwork_delta=-1 if is_image else 0,
                modified_candidate=-1,
            )
            self._prune_empty_chain(state, parent_key)
            return self._recompose_home(root, state, conn)

        if kind == "moved" and old_abs is not None:
            rel_old = self._rel(root, old_abs)
            rel_new = self._rel(root, new_abs)
            if rel_old is None or rel_new is None:
                raise _IncrementalFallback("moved path escapes the library")
            if rel_old == rel_new:
                return home
            if rel_old not in state.files:
                raise _IncrementalFallback("moved source unknown")
            if rel_new in state.files:
                raise _IncrementalFallback("moved destination already known")
            target = Path(new_abs)
            try:
                if target.is_dir():
                    raise _IncrementalFallback("directory moves are not incremental yet")
                st = target.stat()
            except OSError as exc:
                raise _IncrementalFallback("cannot stat moved target") from exc
            size, old_mtime = state.files.pop(rel_old)
            state.files[rel_new] = (int(st.st_size), int(st.st_mtime))
            is_image = any(ref.path == rel_old for ref in state.refs)
            if is_image:
                state.refs = [
                    ref if ref.path != rel_old else _ImageRef(rel_new, ref.modified)
                    for ref in state.refs
                ]
            old_parent_key = self._parent_rel(rel_old) or "/"
            new_parent_key = self._parent_rel(rel_new) or "/"
            old_parent = state.nodes.get(old_parent_key)
            new_parent = state.nodes.get(new_parent_key)
            if old_parent is None or new_parent is None:
                raise _IncrementalFallback("moved parent unknown")
            old_sole_content = int(old_parent.summary["file_count"]) == 1 and not old_parent.children
            if not old_sole_content and int(old_parent.summary["modified"]) == old_mtime:
                raise _IncrementalFallback("moved file carried the old max mtime")
            if is_image and rel_old in old_parent.direct_images:
                old_parent.direct_images.remove(rel_old)
                if old_parent.summary.get("cover_path") == rel_old:
                    self._recompute_cover(root, state, old_parent_key)
            if is_image:
                new_parent.direct_images.append(rel_new)
                new_parent.direct_images.sort(key=lambda path: path.casefold())
                if new_parent.summary.get("cover_path") is None or new_parent.direct_images[0] == rel_new:
                    self._recompute_cover(root, state, new_parent_key)
            self._bump_ancestors(
                state, old_parent_key,
                size_delta=-size,
                file_delta=-1,
                artwork_delta=-1 if is_image else 0,
                modified_candidate=-1,
            )
            self._prune_empty_chain(state, old_parent_key)
            self._bump_ancestors(
                state, new_parent_key,
                size_delta=int(st.st_size),
                file_delta=1,
                artwork_delta=1 if is_image else 0,
                modified_candidate=int(st.st_mtime),
            )
            return self._recompose_home(root, state, conn)

        raise _IncrementalFallback(f"unsupported event {kind}")

    def _bump_ancestors(
        self,
        state: _HomeState,
        start_key: str,
        *,
        size_delta: int,
        file_delta: int,
        artwork_delta: int,
        modified_candidate: int,
        child_delta: int = 0,
    ) -> None:
        """Propagate aggregate deltas from *start_key* up to the root."""
        parts = [part for part in start_key.split("/") if part]
        touched: list[str] = []
        for i in range(len(parts), -1, -1):
            key = "/".join(parts[:i]) or "/"
            node = state.nodes.get(key)
            if node is None:
                raise _IncrementalFallback(f"missing node {key}")
            summary = node.summary
            summary["size"] = max(0, int(summary["size"]) + size_delta)
            summary["size_fmt"] = format_size(int(summary["size"]))
            summary["file_count"] = max(0, int(summary["file_count"]) + file_delta)
            summary["artwork_count"] = max(0, int(summary["artwork_count"]) + artwork_delta)
            summary["child_count"] = max(0, int(summary["child_count"]) + child_delta)
            if modified_candidate > int(summary["modified"]):
                summary["modified"] = modified_candidate
            touched.append(key)
        for key in touched:
            if key == "/":
                continue
            parent_key = self._parent_rel(key) or "/"
            if state.nodes is not None and parent_key in state.nodes:
                self._resort_children(state, parent_key)

    def _resort_children(self, state: _HomeState, parent_key: str) -> None:
        parent = state.nodes.get(parent_key)
        if parent is None:
            raise _IncrementalFallback(f"missing parent {parent_key}")
        parent.children.sort(key=lambda path: (
            -int(state.nodes[path].summary["modified"]),
            str(state.nodes[path].summary["name"]).casefold(),
        ))

    def _recompute_cover(self, root: Path, state: _HomeState, node_key: str) -> None:
        node = state.nodes.get(node_key)
        if node is None:
            raise _IncrementalFallback(f"missing node {node_key}")
        summary = node.summary
        cover_path = (
            node.direct_images[0]
            if node.direct_images
            else next(
                (
                    state.nodes[child].summary.get("cover_path")
                    for child in node.children
                    if state.nodes[child].summary.get("cover_path")
                ),
                None,
            )
        )
        summary["cover_path"] = cover_path
        cover = self._describe_image(root, cover_path) if cover_path else None
        summary["width"] = cover.get("width") if cover else None
        summary["height"] = cover.get("height") if cover else None
        summary["aspect_ratio"] = cover.get("aspect_ratio") if cover else None

    def _recompose_home(self, root: Path, state: _HomeState, db_conn) -> GalleryHome:
        root_node = state.nodes.get("/")
        if root_node is None:
            raise _IncrementalFallback("root state missing")
        children = [
            state.nodes[path].summary for path in root_node.children
            if path in state.nodes
        ]
        collections = [item for item in children if item.get("kind") == "collection"]
        projects = [item for item in children if item.get("kind") == "project"]
        refs = sorted(state.refs, key=lambda item: (-item.modified, item.path.casefold()))
        recent: list[dict[str, Any]] = []
        for ref in refs[:24]:
            described = self._describe_image(root, ref.path)
            if described:
                recent.append(described)
        self._apply_tags_to_entries(root, recent, db_conn=db_conn)
        # The build counts every non-root node by kind, not just the
        # root's direct children.
        collections_count = sum(
            1 for key, entry in state.nodes.items()
            if key != "/" and entry.summary.get("kind") == "collection"
        )
        projects_count = sum(
            1 for key, entry in state.nodes.items()
            if key != "/" and entry.summary.get("kind") == "project"
        )
        stats = {
            "collections": collections_count,
            "projects": projects_count,
            "artworks": int(root_node.summary["artwork_count"]),
            "total_size_fmt": str(root_node.summary["size_fmt"]),
        }
        featured = collections[0] if collections else projects[0] if projects else root_node.summary
        return GalleryHome(featured, collections, projects, recent, stats)

    def _apply_tags(
        self,
        root: Path,
        node: dict[str, Any] | None,
        *,
        db_conn: sqlite3.Connection | None,
        extra_entries: Iterable[dict[str, Any]] = (),
    ) -> None:
        if node is None:
            return
        paths: list[str] = []
        seen: set[str] = set()

        def add_path(path: str) -> None:
            if path not in seen:
                seen.add(path)
                paths.append(path)

        def collect(current: dict[str, Any]) -> None:
            add_path(str(current["path"]))
            for child in current.get("children", ()):
                collect(child)
            for entry in current.get("entries", ()):
                add_path(str(entry["path"]))

        collect(node)
        for entry in extra_entries:
            add_path(str(entry["path"]))
        if not paths:
            return
        try:
            tags_by_path = self._tag_service.get_tags_for_files(
                root, [root / path for path in paths], db_conn=db_conn
            )
        except (RuntimeError, sqlite3.Error, ValueError):
            _log.debug("Gallery tag projection unavailable", exc_info=True)
            tags_by_path = {}

        def tags_for(relative_path: str) -> list[str]:
            key = str((root / relative_path).resolve())
            return list(tags_by_path.get(key, ()))

        def apply(current: dict[str, Any]) -> None:
            current["tags"] = tags_for(str(current["path"]))
            for child in current.get("children", ()):
                apply(child)
            for entry in current.get("entries", ()):
                entry["tags"] = tags_for(str(entry["path"]))

        apply(node)
        for entry in extra_entries:
            entry["tags"] = tags_for(str(entry["path"]))

    def _apply_tags_to_entries(
        self,
        root: Path,
        entries: list[dict[str, Any]],
        *,
        db_conn: sqlite3.Connection | None,
    ) -> None:
        if not entries:
            return
        try:
            tags_by_path = self._tag_service.get_tags_for_files(
                root, [root / str(entry["path"]) for entry in entries], db_conn=db_conn
            )
        except (RuntimeError, sqlite3.Error, ValueError):
            _log.debug("Gallery artwork tag projection unavailable", exc_info=True)
            return
        for entry in entries:
            key = str((root / str(entry["path"])).resolve())
            entry["tags"] = list(tags_by_path.get(key, ()))

    @staticmethod
    def _sort_entries(entries: list[dict[str, Any]], sort: str) -> None:
        if sort == "name":
            entries.sort(key=lambda item: str(item["name"]).casefold())
        else:
            entries.sort(key=lambda item: (-int(item["modified"]), str(item["name"]).casefold()))

    @session_operation
    def get_home(
        self,
        library_root: str | Path,
        *,
        db_conn: sqlite3.Connection | None = None,
    ) -> GalleryHome:
        root = Path(library_root).resolve()
        now = time.monotonic()
        with self._home_cache_lock:
            cached = self._home_cache.get(str(root))
            if cached is not None and now - cached[0] < self._home_cache_ttl:
                return cached[1]
        return self._compute_home(str(root), db_conn=db_conn)

    def _compute_home(
        self,
        root_key: str,
        *,
        db_conn: sqlite3.Connection | None = None,
    ) -> GalleryHome:
        """Compute and cache the home projection for *root_key*.

        Called both synchronously (get_home) and from the background
        builder thread; writes the cache so later reads are instant.
        """
        root = Path(root_key).resolve()
        conn = self._connection(root, db_conn, self._connection_provider)
        refs: list[_ImageRef] = []
        node_counts: dict[str, int] = {"collection": 0, "project": 0}
        state_nodes: dict[str, _StateNode] = {}
        known_files: dict[str, tuple[int, int]] = {}
        node = self._build_node(
            root,
            "",
            root,
            include_entries=True,
            budget=_TraversalBudget(self._limits),
            depth=0,
            image_refs=refs,
            node_counts=node_counts,
            state_nodes=state_nodes,
            known_files=known_files,
        )
        if node is None:
            return GalleryHome(None, [], [], [], {
                "collections": 0,
                "projects": 0,
                "artworks": 0,
                "total_size_fmt": format_size(0),
            })
        self._apply_tags(root, node, db_conn=conn)
        top_level: list[dict[str, Any]] = list(node.get("children", ()))
        collections: list[dict[str, Any]] = [
            item for item in top_level if item.get("kind") == "collection"
        ]
        projects: list[dict[str, Any]] = [
            item for item in top_level if item.get("kind") == "project"
        ]
        refs.sort(key=lambda item: (-item.modified, item.path.casefold()))
        recent: list[dict[str, Any]] = []
        for ref in refs[:24]:
            described = self._describe_image(root, ref.path)
            if described:
                recent.append(described)
        self._apply_tags_to_entries(root, recent, db_conn=conn)
        stats = {
            "collections": node_counts.get("collection", 0),
            "projects": node_counts.get("project", 0),
            "artworks": int(node["artwork_count"]),
            "total_size_fmt": str(node["size_fmt"]),
        }
        featured = collections[0] if collections else projects[0] if projects else self._summary(node)
        home = GalleryHome(featured, collections, projects, recent, stats)
        with self._home_cache_lock:
            with self._generation_lock:
                self._home_generation += 1
                generation = self._home_generation
            self._home_states[str(root)] = _HomeState(
                node=node,
                nodes=state_nodes,
                refs=refs,
                files=known_files,
                generation=generation,
            )
            self._home_cache[str(root)] = (time.monotonic(), home)
        self._save_persisted_projection(str(root), home)
        return home

    @session_operation
    def get_collection(
        self,
        library_root: str | Path,
        relative_path: str | Path | None = "",
        *,
        sort: str = "updated",
        kind: str = "all",
        db_conn: sqlite3.Connection | None = None,
    ) -> GalleryCollection | None:
        if sort not in {"updated", "name"}:
            raise ValueError("unsupported gallery sort")
        if kind not in {"all", "artwork", "works"}:
            raise ValueError("unsupported gallery kind")
        root = Path(library_root).resolve()
        normalized, target = self._resolve_existing(root, relative_path)
        if not target.is_dir():
            return None
        conn = self._connection(root, db_conn, self._connection_provider)
        node = self._build_node(
            root,
            normalized,
            target,
            include_entries=True,
            budget=_TraversalBudget(self._limits),
            depth=len([part for part in normalized.split("/") if part]),
        )
        if node is None:
            return None
        self._apply_tags(root, node, db_conn=conn)
        entries: list[dict[str, Any]] = list(node.get("entries", ()))
        if kind in {"artwork", "works"}:
            entries = [entry for entry in entries if entry.get("kind") == "artwork"]
        self._sort_entries(entries, sort)
        children: list[dict[str, Any]] = list(node.get("children", ()))
        return GalleryCollection(self._summary(node), children, entries)

    @session_operation
    def describe_entries(
        self,
        library_root: str | Path,
        relative_paths: Iterable[str | Path],
        *,
        db_conn: sqlite3.Connection | None = None,
    ) -> list[dict[str, Any]]:
        """Describe a bounded list of existing Gallery-compatible paths."""
        root = Path(library_root).resolve()
        conn = self._connection(root, db_conn, self._connection_provider)
        budget = _TraversalBudget(self._limits)
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw_path in list(relative_paths)[:500]:
            try:
                normalized, target = self._resolve_existing(root, raw_path)
            except (MissingPathError, PathEscapeError, ValueError):
                continue
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            if target.is_dir():
                node = self._build_node(
                    root,
                    normalized,
                    target,
                    include_entries=False,
                    budget=budget,
                    depth=len([part for part in normalized.split("/") if part]),
                )
                if node is not None:
                    result.append(self._summary(node))
                continue
            described = self._describe_image(root, normalized)
            if described is not None:
                result.append(described)
        self._apply_tags_to_entries(root, result, db_conn=conn)
        return result

    @session_operation
    def resolve(
        self,
        library_root: str | Path,
        relative_path: str | Path | None = "",
        *,
        db_conn: sqlite3.Connection | None = None,
    ) -> GalleryResolve:
        root = Path(library_root).resolve()
        normalized, target = self._resolve_existing(root, relative_path)
        if target.is_file() and target.suffix.lower() in _SAFE_GALLERY_IMAGE_EXTS:
            context = self._parent_path(normalized) or ""
            return GalleryResolve("artwork", normalized, context, context)
        if target.is_dir():
            node = self._build_node(
                root,
                normalized,
                target,
                include_entries=False,
                budget=_TraversalBudget(self._limits),
                depth=len([part for part in normalized.split("/") if part]),
            )
            resolved_kind = str(node.get("kind")) if node else "collection"
        else:
            resolved_kind = "collection"
        context = normalized
        return GalleryResolve(resolved_kind, normalized, context, context)


__all__ = [
    "GalleryCollection",
    "GalleryHome",
    "GalleryResolve",
    "GalleryService",
    "GalleryTraversalLimitError",
    "GalleryTraversalLimits",
]
