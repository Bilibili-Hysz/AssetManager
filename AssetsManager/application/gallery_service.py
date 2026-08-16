"""Gallery projection service for the LAN WebUI.

The Gallery is a read-only projection over the library filesystem.  It deliberately
stays separate from ``ProjectService`` because its hierarchy is based on visible
folders and artwork files rather than the user-configurable project depth.  The
service only returns library-relative paths and reuses the canonical session,
connection and tag services.

The implementation is split across the ``gallery`` subpackage; this module keeps
the concrete ``GalleryService`` facade (construction, lifecycle, request
entry points and the full home build) plus the public re-exports so that every
previously importable symbol remains importable from this module.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from time import monotonic
from typing import Any, Callable, Iterable

from AssetsManager.application.context import ConnectionProvider, LibrarySession, session_operation
from AssetsManager.application.project_service import ProjectDepthConfig
from AssetsManager.application.tag_service import TagService
from AssetsManager.core.format_utils import format_size
from AssetsManager.domain.errors import MissingPathError, PathEscapeError
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import FileSystemChanged

from AssetsManager.application.gallery._incremental import _GalleryIncrementalMixin
from AssetsManager.application.gallery._persistence import _GalleryPersistenceMixin
from AssetsManager.application.gallery._projection_builder import _GalleryProjectionMixin
from AssetsManager.application.gallery._types import (
    GalleryCollection,
    GalleryHome,
    GalleryImage,  # noqa: F401  (re-exported for backwards compatibility)
    GalleryResolve,
    GalleryTraversalLimitError,
    GalleryTraversalLimits,
    _FILE_ATTRIBUTE_REPARSE_POINT,  # noqa: F401  (re-exported)
    _HomeState,
    _ImageRef,
    _IncrementalFallback,  # noqa: F401  (re-exported)
    _LEGACY_URL_KEYS,  # noqa: F401  (re-exported)
    _QueuedChange,
    _SAFE_GALLERY_IMAGE_EXTS,
    _StateNode,
    _TraversalBudget,
    _log,
    _strip_legacy_url_fields,  # noqa: F401  (re-exported)
)


class GalleryService(_GalleryPersistenceMixin, _GalleryProjectionMixin, _GalleryIncrementalMixin):
    """Build bounded Gallery projections for one live library session.

    The projection tree is capped at the project depth (``sidebar_depth_cfg``,
    the same config the desktop sidebar and the workspace use): directories
    at or below the configured depth are *projects* — display leaves whose
    whole subtree aggregates into one node.  Everything deeper inside a
    project (textures/, models/, ...) is never projected as a node, so a
    70k-file library with tens of thousands of inner directories only
    produces covers for the branches and the projects the user actually
    browses, not for every folder.
    """

    def __init__(
        self,
        connection_provider: ConnectionProvider | None = None,
        session: LibrarySession | None = None,
        *,
        limits: GalleryTraversalLimits | None = None,
        depth_config: ProjectDepthConfig | None = None,
    ) -> None:
        self._connection_provider = connection_provider
        self._session = session
        self._limits = limits or GalleryTraversalLimits()
        self._depth_config_override = depth_config
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
        if self._closed:
            return None
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
            if self._closed:
                # The service was closed while the prewarm waited out the
                # scanner; do not start one last full-library walk.
                return
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
            project_depth=self._depth_config(),
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
        config = self._depth_config()
        depth = len([part for part in normalized.split("/") if part])
        node = None
        if normalized:
            floor = self._project_floor(config, normalized)
            if depth == floor:
                # The collection page for a project root: the whole subtree
                # aggregates into the project node (inner dirs are not
                # projected).
                node = self._build_project_node(
                    root, normalized, target,
                    include_entries=True,
                    budget=_TraversalBudget(self._limits),
                    depth=depth,
                )
            elif depth > floor:
                return None  # inside a project: not part of the projection
        if node is None:
            node = self._build_node(
                root,
                normalized,
                target,
                include_entries=True,
                budget=_TraversalBudget(self._limits),
                depth=depth,
                project_depth=config,
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
