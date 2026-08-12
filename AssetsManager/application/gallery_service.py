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
from time import monotonic
from typing import Any, Iterable
from urllib.parse import quote

from AssetsManager.application.context import ConnectionProvider, LibrarySession, session_operation
from AssetsManager.application.tag_service import TagService
from AssetsManager.core.database import DatabaseManager
from AssetsManager.core.format_utils import format_size
from AssetsManager.core.path_resolver import library_data_dir
from AssetsManager.domain.asset import IMAGE_EXTS, assert_under_root
from AssetsManager.domain.errors import MissingPathError, PathEscapeError
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import FileSystemChanged

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
    thousands of entries): a full walk with per-file stat aggregation for
    a 70k-file library takes ~13s on a local disk, so the previous 10s
    budget made gallery views fail with 429 on such libraries. The bounds
    still cap runaway/abusive walks (entry budget ~3x a large real
    library).
    """

    max_entries: int = 150_000
    max_files: int = 150_000
    max_directories: int = 40_000
    max_depth: int = 64
    max_seconds: float = 30.0


class GalleryTraversalLimitError(RuntimeError):
    """Raised when a gallery walk exceeds its bounded traversal budget."""

    def __init__(self, message: str, *, status: int = 413) -> None:
        super().__init__(message)
        self.status = status


class _TraversalBudget:
    def __init__(self, limits: GalleryTraversalLimits) -> None:
        self.limits = limits
        self.started_at = monotonic()
        self.entries = 0
        self.files = 0
        self.directories = 0

    def check_time(self) -> None:
        if monotonic() - self.started_at > self.limits.max_seconds:
            raise GalleryTraversalLimitError("Gallery traversal time budget exceeded", status=429)

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
    thumbnail_url: str
    image_url: str
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
            "thumbnail_url": self.thumbnail_url,
            "image_url": self.image_url,
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
        # RuntimeData persistence: the projection survives process restarts
        # (a 286 GB library takes tens of seconds to build). FileSystemChanged
        # events delete it, and the TTL is a safety net for missed events.
        self._disk_cache_ttl = 3600.0
        # Background home projection: the full-library walk for very large
        # libraries takes tens of seconds, so it must never block a request.
        # Requests read the cache; a miss returns a "building" signal and a
        # daemon thread computes the projection and fills the cache.
        self._building: set[str] = set()
        self._build_lock = threading.Lock()
        self._refresh_timer: threading.Timer | None = None
        self._closed = False
        self._fs_subscription = get_event_bus().subscribe_weak(
            FileSystemChanged, self._on_file_system_changed
        )

    def _on_file_system_changed(self, event: FileSystemChanged) -> None:
        """Invalidate the home projection on library changes and schedule a
        background rebuild (debounced so a burst of file events rebuilds
        once, shortly after the last change)."""
        if event.kind in {"gallery", "shop"}:
            return
        root_key = str(Path(event.library_root).resolve())
        with self._home_cache_lock:
            self._home_cache.pop(root_key, None)
        # The persisted projection is stale too; delete it so a restart does
        # not resurrect the pre-change view.
        try:
            disk = self._disk_cache_path(root_key)
            if disk.is_file():
                disk.unlink()
        except OSError:
            pass
        with self._build_lock:
            if self._refresh_timer is not None:
                self._refresh_timer.cancel()
            self._refresh_timer = threading.Timer(
                self._home_cache_ttl, self._ensure_home_building, args=(str(event.library_root),)
            )
            self._refresh_timer.daemon = True
            self._refresh_timer.start()

    def close(self) -> None:
        """Stop background work; called when the owning session closes."""
        self._closed = True
        with self._build_lock:
            if self._refresh_timer is not None:
                self._refresh_timer.cancel()
                self._refresh_timer = None
        try:
            self._fs_subscription.unsubscribe()
        except Exception:
            pass

    @session_operation
    def get_home_cached(
        self, library_root: str | Path
    ) -> "GalleryHome | None":
        """Return a home projection, or None when a build is needed.

        Fresh memory cache -> value. Stale memory -> the stale value plus
        a background rebuild. No memory -> try the RuntimeData disk cache
        (served immediately, rebuilt in the background); no disk cache ->
        None plus a background build.
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
            disk = self._load_disk_cache(root_key)
            if disk is not None:
                self._home_cache[root_key] = (now, disk)
                self._ensure_home_building(root_key)
                return disk
        self._ensure_home_building(root_key)
        return None

    def _disk_cache_path(self, root_key: str) -> Path:
        """RuntimeData location for the persisted home projection."""
        return library_data_dir(Path(root_key).resolve()) / "gallery_home.json"

    def _load_disk_cache(self, root_key: str) -> "GalleryHome | None":
        """Load a persisted projection within its TTL, or None."""
        path = self._disk_cache_path(root_key)
        try:
            if not path.is_file():
                return None
            raw = json.loads(path.read_text(encoding="utf-8"))
            saved_at = float(raw.get("saved_at", 0))
            if time.time() - saved_at > self._disk_cache_ttl:
                return None
            projection = raw.get("projection")
            if not isinstance(projection, dict):
                return None
            return GalleryHome(
                featured=projection.get("featured"),
                collections=projection.get("collections", []),
                projects=projection.get("projects", []),
                recent=projection.get("recent", []),
                stats=projection.get("stats", {}),
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            _log.debug("Gallery home disk cache unreadable for %s", root_key, exc_info=True)
            return None

    def _save_disk_cache(self, root_key: str, home: "GalleryHome") -> None:
        """Persist the projection atomically (tmp + rename)."""
        try:
            path = self._disk_cache_path(root_key)
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "saved_at": time.time(),
                "projection": home.to_response(),
            }
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            os.replace(tmp, path)
        except OSError:
            _log.debug("Gallery home disk cache write failed", exc_info=True)

    def prewarm_home(self, library_root: str | Path) -> None:
        """Kick off a background home projection build (idempotent).

        Called after the LAN server starts so the first /gallery visit
        finds a warm cache instead of a building state. Never blocks.
        """
        try:
            self._ensure_home_building(str(Path(library_root).resolve()))
        except Exception:
            _log.debug("Gallery home prewarm skipped", exc_info=True)

    def _ensure_home_building(self, root_key: str) -> None:
        """Start a background home build for *root_key* unless one is
        already running or the service is closed.

        Idempotence comes from the ``_building`` set, not the cache, so
        callers may invoke this while holding ``_home_cache_lock`` (the
        stale-value path) without deadlocking.
        """
        if self._closed:
            return
        with self._build_lock:
            if root_key in self._building:
                return
            self._building.add(root_key)
        thread = threading.Thread(
            target=self._build_home_background, args=(root_key,), daemon=True
        )
        thread.start()

    def _build_home_background(self, root_key: str) -> None:
        """Compute the projection off the request path; failures leave the
        cache empty so the next request retries the build."""
        try:
            self._compute_home(root_key)
        except Exception:
            _log.exception("Background gallery home build failed for %s", root_key)
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

    @staticmethod
    def _thumbnail_url(relative_path: str, size: int) -> str:
        encoded = quote(relative_path, safe="/")
        return f"/api/thumbnails/{encoded}?size={size}"

    @staticmethod
    def _image_url(relative_path: str) -> str:
        """Build the URI-encoded high-resolution image preview URL."""
        encoded = quote(relative_path, safe="")
        return f"/api/image?path={encoded}"

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
        thumbnail_size: int = 512,
    ) -> dict[str, Any] | None:
        target = (root / relative_path).resolve()
        try:
            target.relative_to(root)
            if (
                not target.is_file()
                or target.suffix.lower() not in _SAFE_GALLERY_IMAGE_EXTS
                or cls._path_contains_reparse_point(root, target)
            ):
                return None
            stat_result = stat_result or target.stat()
        except (OSError, ValueError):
            return None
        width, height, aspect_ratio = cls._image_dimensions(target)
        parent = cls._parent_path(relative_path)
        return GalleryImage(
            name=target.name,
            path=relative_path,
            parent_path=parent or "",
            thumbnail_url=cls._thumbnail_url(relative_path, thumbnail_size),
            image_url=cls._image_url(relative_path),
            width=width,
            height=height,
            aspect_ratio=aspect_ratio,
            modified=int(stat_result.st_mtime),
            size=int(stat_result.st_size),
            extension=target.suffix.lower(),
        ).to_dict()

    @staticmethod
    def _entry_is_reparse_point(entry: os.DirEntry[str]) -> bool:
        """Return whether *entry* is a link, junction, or reparse point."""
        try:
            if entry.is_symlink():
                return True
            is_junction = getattr(entry, "is_junction", None)
            if callable(is_junction) and is_junction():
                return True
            stat_result = entry.stat(follow_symlinks=False)
        except OSError:
            return True
        return bool(
            int(getattr(stat_result, "st_file_attributes", 0))
            & _FILE_ATTRIBUTE_REPARSE_POINT
        )

    @classmethod
    def _path_contains_reparse_point(cls, root: Path, target: Path) -> bool:
        """Check every component between root and target without following it."""
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
    ) -> list[os.DirEntry[str]]:
        """Materialize only entries which have already consumed traversal budget."""
        visible: list[os.DirEntry[str]] = []
        try:
            with os.scandir(target) as iterator:
                for entry in iterator:
                    budget.check_time()
                    if self._entry_is_reparse_point(entry):
                        budget.visit_entry(depth + 1, is_file=False)
                        continue
                    try:
                        is_file = entry.is_file(follow_symlinks=False)
                    except OSError:
                        is_file = False
                    budget.visit_entry(depth + 1, is_file=is_file)
                    if not entry.name.startswith("."):
                        visible.append(entry)
        except OSError:
            return visible
        budget.check_time()
        visible.sort(key=lambda entry: entry.name.casefold())
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
    ) -> dict[str, Any] | None:
        try:
            if self._path_contains_reparse_point(root, target):
                return None
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

        for entry in self._visible_entries(target, budget, depth):
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
            try:
                stat_result = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            total_size += int(stat_result.st_size)
            file_count += 1
            direct_file_count += 1
            modified = int(stat_result.st_mtime)
            latest_modified = max(latest_modified, modified)
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
        cover = self._describe_image(root, cover_path, thumbnail_size=512) if cover_path else None
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
            "cover_url": cover.get("thumbnail_url") if cover else None,
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
                if (described := self._describe_image(root, path, stat_result=stat_result, thumbnail_size=512))
            ]
        return node

    @staticmethod
    def _summary(node: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in node.items() if key not in {"children", "entries"}}

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
        node = self._build_node(
            root,
            "",
            root,
            include_entries=True,
            budget=_TraversalBudget(self._limits),
            depth=0,
            image_refs=refs,
            node_counts=node_counts,
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
            described = self._describe_image(root, ref.path, thumbnail_size=512)
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
            self._home_cache[str(root)] = (time.monotonic(), home)
        self._save_disk_cache(str(root), home)
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
            described = self._describe_image(root, normalized, thumbnail_size=512)
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
