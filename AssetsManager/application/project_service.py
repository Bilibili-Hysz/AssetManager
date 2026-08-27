"""Project listing application service."""
from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from AssetsManager.application.asset_filters import IMAGE_EXTS
from AssetsManager.application.context import ConnectionProvider, LibrarySession, session_operation
from AssetsManager.application.metadata_service import MetadataService
from AssetsManager.application.tag_service import TagService
from AssetsManager.core.database import DatabaseManager
from AssetsManager.core.format_utils import CATEGORY_MAP, format_size
from AssetsManager.core.directory_cache import DirectoryCache
from AssetsManager.core.path_resolver import root_identity, thumb_dir
from AssetsManager.core.thumbnail_key import WEBP_RENDER_PROFILES, normalize_webp_render_profile
from AssetsManager.application.thumbnail_cache_lifecycle import artifact_path
from AssetsManager.application.thumbnail_service import admit_thumbnail_cache_artifact
from AssetsManager.repositories.metadata_repository import MetadataRepository
from AssetsManager.repositories.asset_index_repository import AssetIndexRepository
from AssetsManager.repositories.thumbnail_repository import ThumbnailRepository

_log = logging.getLogger(__name__)

_DEPTH_MIN = 1
_DEPTH_MAX = 32
_DEPTH_DEFAULT = 2
_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400


def _is_link_or_reparse(entry: os.DirEntry) -> bool:
    """Return True for symlinks, junctions, or other reparse entries."""
    try:
        if entry.is_symlink():
            return True
        is_junction = getattr(entry, "is_junction", None)
        if callable(is_junction) and is_junction():
            return True
        stat_result = entry.stat(follow_symlinks=False)
        return bool(
            int(getattr(stat_result, "st_file_attributes", 0))
            & _FILE_ATTRIBUTE_REPARSE_POINT
        )
    except OSError:
        return True


@dataclass(frozen=True)
class _SafeDirEntry:
    """Snapshot a directory entry before its no-follow directory handle closes."""

    name: str
    path: str
    _stat_result: os.stat_result
    _is_dir: bool
    _is_file: bool
    _is_symlink: bool

    @classmethod
    def from_entry(cls, parent: Path, entry: os.DirEntry) -> "_SafeDirEntry":
        stat_result = entry.stat(follow_symlinks=False)
        return cls(
            name=entry.name,
            path=str(parent / entry.name),
            _stat_result=stat_result,
            _is_dir=entry.is_dir(follow_symlinks=False),
            _is_file=entry.is_file(follow_symlinks=False),
            _is_symlink=entry.is_symlink(),
        )

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        return self._is_dir

    def is_file(self, *, follow_symlinks: bool = True) -> bool:
        return self._is_file

    def is_symlink(self) -> bool:
        return self._is_symlink

    def stat(self, *, follow_symlinks: bool = True) -> os.stat_result:
        return self._stat_result


def _clamp_depth(value: object, default: int = _DEPTH_DEFAULT) -> int:
    """Return an int clamped to ``[_DEPTH_MIN, _DEPTH_MAX]``.

    Non-integer values (bools included) fall back to ``default`` so a
    corrupted config can never drive unbounded directory recursion.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    if value < _DEPTH_MIN:
        return _DEPTH_MIN
    if value > _DEPTH_MAX:
        return _DEPTH_MAX
    return value


@dataclass(frozen=True)
class ProjectDepthConfig:
    global_depth: int = _DEPTH_DEFAULT
    branch_depths: dict[str, int] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "global_depth", _clamp_depth(self.global_depth))
        if self.branch_depths is not None:
            object.__setattr__(
                self,
                "branch_depths",
                {
                    str(name): _clamp_depth(value, self.global_depth)
                    for name, value in self.branch_depths.items()
                },
            )

    @classmethod
    def from_dict(cls, data: dict | None) -> "ProjectDepthConfig":
        data = data or {}
        raw_branches = data.get("branch_depths", {}) or {}
        branch_depths = (
            {str(name): value for name, value in raw_branches.items()}
            if isinstance(raw_branches, dict) and raw_branches
            else None
        )
        return cls(
            global_depth=_clamp_depth(data.get("depth", _DEPTH_DEFAULT)),
            branch_depths=branch_depths,
        )

    @property
    def branches(self) -> dict[str, int]:
        return self.branch_depths or {}


@dataclass(frozen=True)
class ProjectListItem:
    name: str
    path: str
    is_project: bool
    thumbnail_path: str | None
    tags: list[str]
    total_size: int
    file_count: int
    notes: str
    modified: float

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "is_project": self.is_project,
            "thumbnail_path": self.thumbnail_path,
            "tags": self.tags[:10],
            "total_size": self.total_size,
            "total_size_fmt": format_size(self.total_size),
            "file_count": self.file_count,
            "notes": self.notes[:200] if self.notes else "",
            "modified": self.modified,
        }


@dataclass(frozen=True)
class ProjectListing:
    current_path: str
    parent_path: str
    items: tuple[ProjectListItem, ...]
    depth_config: ProjectDepthConfig
    current_depth: int
    total_count: int = 0
    offset: int = 0
    limit: int = 0

    def to_response(self) -> dict:
        items = [item.to_dict() for item in self.items]
        total_size = sum(item.total_size for item in self.items)
        return {
            "current_path": self.current_path,
            "parent_path": self.parent_path,
            "items": items,
            "depth_config": {
                "global": self.depth_config.global_depth,
                "branches": self.depth_config.branches,
                "current_depth": self.current_depth,
            },
            "total_count": self.total_count,
            "project_count": sum(1 for item in self.items if item.is_project),
            "folder_count": sum(1 for item in self.items if not item.is_project),
            "total_size": total_size,
            "total_size_fmt": format_size(total_size),
            "offset": self.offset,
            "limit": self.limit,
            "has_more": self.offset + len(self.items) < self.total_count,
        }


@dataclass(frozen=True)
class ProjectDetail:
    name: str
    path: str
    tags: list[str]
    notes: str
    urls: list[str]
    total_size: int
    file_count: int
    files: list[dict]
    images: list[dict]
    thumbnail_path: str | None
    modified: float

    def to_response(self) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "tags": self.tags,
            "notes": self.notes,
            "urls": self.urls,
            "total_size": self.total_size,
            "total_size_fmt": format_size(self.total_size),
            "file_count": self.file_count,
            "files": self.files,
            "images": self.images,
            "thumbnail_path": self.thumbnail_path,
            "modified": self.modified,
        }


@dataclass(frozen=True)
class ProjectTree:
    tree: list[dict]
    depth_config: ProjectDepthConfig

    def to_response(self) -> dict:
        return {
            "tree": self.tree,
            "depth_config": {
                "global": self.depth_config.global_depth,
                "branches": self.depth_config.branches,
            },
        }


@dataclass(frozen=True)
class ProjectHome:
    recent_projects: list[dict]
    preview_pool: list[dict]
    popular_tags: list[dict]
    total_projects: int
    total_size: int

    def to_response(self) -> dict:
        return {
            "recent_projects": self.recent_projects,
            "preview_pool": self.preview_pool,
            "popular_tags": self.popular_tags,
            "stats": {
                "total_projects": self.total_projects,
                "total_size": self.total_size,
                "total_size_fmt": format_size(self.total_size),
            },
        }


class ProjectService:
    """Build project list responses shared by LAN routes and future desktop views."""

    def __init__(self, connection_provider: ConnectionProvider,
                 session: LibrarySession | None = None):
        self._session = session
        self._session_root_identity = None
        if isinstance(session, LibrarySession):
            expected_provider = session.connection_for
            provider_self = getattr(connection_provider, "__self__", None)
            provider_func = getattr(connection_provider, "__func__", None)
            expected_func = getattr(expected_provider, "__func__", None)
            if not (
                connection_provider == expected_provider
                or (provider_self is session and provider_func is expected_func)
            ):
                raise ValueError(
                    "ProjectService connection provider does not belong to "
                    "the LibrarySession"
                )
            self._connection_provider = expected_provider
            self._session_root_identity = session.context.root_identity
            self._metadata_svc = MetadataService.for_session(session)
        else:
            self._connection_provider = connection_provider
            # Keep provider-only legacy probes/fakes on the raw compatibility
            # path.  The canonical path above intentionally accepts only a
            # real LibrarySession and cannot be widened for test doubles.
            self._metadata_svc = MetadataService(
                connection_provider=connection_provider
            )
        self._tag_svc = TagService(
            connection_provider=self._connection_provider, session=session
        )

    @staticmethod
    def _path_contains_link_or_reparse(root: Path, target: Path) -> bool:
        """Return True when a path component below root is a link/reparse point."""
        try:
            relative = target.relative_to(root)
        except ValueError:
            return True
        current = root
        for part in relative.parts:
            current /= part
            try:
                if current.is_symlink():
                    return True
                is_junction = getattr(current, "is_junction", None)
                if callable(is_junction) and is_junction():
                    return True
                stat_result = current.lstat()
            except OSError:
                return True
            if bool(
                int(getattr(stat_result, "st_file_attributes", 0))
                & _FILE_ATTRIBUTE_REPARSE_POINT
            ):
                return True
        return False

    @classmethod
    def _admit_public_target(
        cls, root: Path, target: str | Path
    ) -> tuple[Path, Path]:
        """Return the lexical and resolved target after containment checks."""
        target_input = Path(target)
        lexical_target = (
            target_input if target_input.is_absolute() else Path.cwd() / target_input
        )
        target_path = lexical_target.resolve()
        if not target_path.is_relative_to(root):
            raise ValueError("target must be under library_root")
        if (
            cls._path_contains_link_or_reparse(root, lexical_target)
            or cls._path_contains_link_or_reparse(root, target_path)
        ):
            raise ValueError("target must not pass through a link or reparse point")
        return lexical_target, target_path

    @classmethod
    def _revalidate_public_target(
        cls, root: Path, lexical_target: Path, target_path: Path
    ) -> None:
        """Reject a target replaced while a public operation was scanning it."""
        _lexical_target, current_target = cls._admit_public_target(
            root, lexical_target
        )
        if current_target != target_path:
            raise ValueError("target changed during project operation")

    @staticmethod
    def _open_directory_no_follow(path: Path) -> int:
        """Open every POSIX path component with no-follow semantics."""
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW
        current_fd = os.open(path.anchor or os.sep, flags)
        try:
            for part in path.parts:
                if part in ("", path.anchor):
                    continue
                next_fd = os.open(part, flags, dir_fd=current_fd)
                os.close(current_fd)
                current_fd = next_fd
            return current_fd
        except OSError:
            os.close(current_fd)
            raise

    @staticmethod
    def _directory_entry_snapshot(path: Path) -> list[_SafeDirEntry]:
        """Snapshot entries without following a replaced directory component."""
        directory_fd: int | None = None
        try:
            if os.name == "posix" and hasattr(os, "O_NOFOLLOW"):
                directory_fd = ProjectService._open_directory_no_follow(path)
                iterator = os.scandir(directory_fd)
            else:
                if ProjectService._path_contains_link_or_reparse(path.parent, path):
                    return []
                iterator = os.scandir(path)
            with iterator as entries:
                snapshot = [_SafeDirEntry.from_entry(path, entry) for entry in entries]
            if os.name != "posix" and ProjectService._path_contains_link_or_reparse(
                path.parent, path
            ):
                return []
            return snapshot
        except OSError:
            return []
        finally:
            if directory_fd is not None:
                os.close(directory_fd)

    @staticmethod
    def _safe_directory_entries(path: Path) -> list[_SafeDirEntry]:
        """Return visible, non-link directories without following them."""
        return [
            entry
            for entry in ProjectService._directory_entry_snapshot(path)
            if not entry.name.startswith(".")
            and not _is_link_or_reparse(entry)
            and entry.is_dir(follow_symlinks=False)
        ]

    @staticmethod
    def _safe_file_entries(path: Path) -> list[_SafeDirEntry]:
        """Return visible, non-link files without following them."""
        return [
            entry
            for entry in ProjectService._directory_entry_snapshot(path)
            if not entry.name.startswith(".")
            and not _is_link_or_reparse(entry)
            and entry.is_file(follow_symlinks=False)
        ]

    @classmethod
    def _first_image(cls, path: Path) -> Path | None:
        for entry in cls._safe_file_entries(path):
            if Path(entry.name).suffix.lower() in IMAGE_EXTS:
                return Path(entry.path)
        return None

    @staticmethod
    def _safe_file_path(root: Path, path: Path) -> bool:
        """Return True only for a regular file with no linked path component."""
        try:
            if ProjectService._path_contains_link_or_reparse(root, path):
                return False
            return path.is_file() and not path.is_symlink()
        except OSError:
            return False

    def _connection(
        self, library_root: str | Path, db_conn: sqlite3.Connection | None
    ) -> sqlite3.Connection:
        if isinstance(self._session, LibrarySession):
            requested = root_identity(library_root, strict=False)
            captured = self._session_root_identity
            if captured is None or requested.map_key != captured.map_key:
                raise ValueError(
                    "ProjectService library_root does not match the bound "
                    "LibrarySession"
                )
            expected = self._session.connection_for(captured)
            if db_conn is not None and db_conn is not expected:
                raise ValueError(
                    "ProjectService connection does not belong to the bound "
                    "LibrarySession"
                )
            return DatabaseManager.require_managed_connection_owner(captured, expected)

        root = Path(library_root).resolve()
        conn = db_conn if db_conn is not None else self._connection_provider(root)
        return DatabaseManager.validate_connection_owner(root, conn, allow_unmanaged=True)

    @session_operation
    def list_projects(
        self,
        library_root: str | Path,
        target: str | Path,
        rel_path: str = "",
        sort_by: str = "name",
        order: str = "asc",
        search: str = "",
        depth_config: ProjectDepthConfig | None = None,
        db_conn: sqlite3.Connection | None = None,
        offset: int = 0,
        limit: int = 0,
    ) -> ProjectListing:
        root = Path(library_root).resolve()
        lexical_target, target_path = self._admit_public_target(root, target)
        db_conn = self._connection(root, db_conn)
        depth_config = depth_config or ProjectDepthConfig()
        rel_path = rel_path.replace("\\", "/").strip("/")
        search = search.lower()
        current_depth = self._current_depth(root, target_path)

        # Collect candidate directories
        candidates: list[os.DirEntry] = []
        for entry in self._safe_directory_entries(target_path):
            if search and search not in entry.name.lower():
                continue
            candidates.append(entry)
        self._revalidate_public_target(root, lexical_target, target_path)

        # Batch-warm file_count cache for all candidates
        if db_conn is not None:
            self._batch_warm_file_counts(root, candidates, db_conn)

        items: list[ProjectListItem] = []
        for entry in candidates:
            self._revalidate_public_target(root, lexical_target, target_path)
            items.append(self._entry_to_item(root, entry, current_depth, depth_config, db_conn))
        self._revalidate_public_target(root, lexical_target, target_path)

        self._sort(items, sort_by, order)

        total_count = len(items)

        # Apply pagination
        if offset > 0:
            items = items[offset:]
        if limit > 0:
            items = items[:limit]

        parent = os.path.dirname(rel_path) if rel_path else ""
        return ProjectListing(
            current_path=rel_path,
            parent_path=parent,
            items=tuple(items),
            depth_config=depth_config,
            current_depth=current_depth,
            total_count=total_count,
            offset=offset,
            limit=limit,
        )

    def _batch_warm_file_counts(
        self,
        root: Path,
        entries: list[os.DirEntry],
        db_conn: sqlite3.Connection,
    ) -> None:
        """Batch-query and batch-write file counts to avoid N+1 DB calls."""
        paths = [str(Path(e.path).resolve()) for e in entries]
        if not paths:
            return

        # Batch query existing counts
        try:
            cached = MetadataRepository(db_conn).batch_get_cached_file_counts(paths)
        except sqlite3.ProgrammingError:
            raise
        except sqlite3.Error:
            _log.warning("batch file count cache query failed", exc_info=True)
            cached = {}

        # Compute counts for uncached directories
        to_write: dict[str, int] = {}
        for entry, path in zip(entries, paths, strict=True):
            if path in cached:
                continue
            try:
                count = len(self._safe_file_entries(Path(entry.path)))
            except OSError:
                count = 0
            to_write[path] = count

        # Batch write
        if to_write:
            try:
                MetadataRepository(db_conn).batch_set_cached_file_counts(to_write)
            except sqlite3.ProgrammingError:
                raise
            except sqlite3.Error:
                _log.warning("batch file count cache write failed", exc_info=True)

    @session_operation
    def get_home(
        self,
        library_root: str | Path,
        depth_config: ProjectDepthConfig | None = None,
        db_conn: sqlite3.Connection | None = None,
    ) -> ProjectHome:
        root = Path(library_root).resolve()
        db_conn = self._connection(root, db_conn)
        depth_config = depth_config or ProjectDepthConfig()
        projects = self._collect_projects(root, root, 0, "", depth_config)
        self._attach_cached_thumbnails(root, projects, db_conn)
        recent = sorted(projects, key=lambda p: p["mtime"], reverse=True)[:20]
        preview_pool = [
            {
                "name": project["name"],
                "path": project["path"],
                "thumbnail_path": project["thumbnail_path"],
            }
            for project in projects
            if project.get("thumbnail_path")
        ]
        popular_tags = self._popular_tags(root, db_conn)
        total_size = self._library_total_size(root, db_conn)
        return ProjectHome(
            recent_projects=recent,
            preview_pool=preview_pool,
            popular_tags=popular_tags,
            total_projects=len(projects),
            total_size=total_size,
        )

    def _collect_projects(
        self,
        library_root: Path,
        current: Path,
        depth: int,
        branch_name: str,
        depth_config: ProjectDepthConfig,
    ) -> list[dict]:
        projects: list[dict] = []
        try:
            entries = sorted(
                self._safe_directory_entries(current),
                key=lambda e: e.name.lower(),
            )
        except OSError:
            _log.warning("project scan failed: %s", current, exc_info=True)
            return projects
        for entry in entries:
            rel = os.path.relpath(entry.path, library_root).replace("\\", "/")
            child_branch = branch_name or entry.name
            effective_depth = depth_config.branches.get(child_branch, depth_config.global_depth)
            if (depth + 1) >= effective_depth:
                try:
                    mtime = entry.stat(follow_symlinks=False).st_mtime
                except OSError:
                    _log.warning("project mtime lookup failed: %s", entry.path, exc_info=True)
                    mtime = 0
                projects.append({"name": entry.name, "path": rel, "mtime": mtime})
            else:
                projects.extend(self._collect_projects(
                    library_root, Path(entry.path), depth + 1, child_branch, depth_config,
                ))
        return projects

    def _attach_cached_thumbnails(
        self,
        library_root: Path,
        projects: list[dict],
        db_conn: sqlite3.Connection | None,
    ) -> None:
        if db_conn is None:
            return
        try:
            root = library_root.resolve()
            paths = [str((root / project["path"]).resolve()) for project in projects]
            if self._session is None:
                # Preserve legacy/test doubles that still expose DirectoryCache(conn).
                cache = DirectoryCache(db_conn)
            else:
                cache = DirectoryCache(
                    db_conn, library_root=root, session=self._session
                )
            validate_cache = getattr(cache, "validate_for", None)
            if callable(validate_cache):
                validate_cache(root)
            cached_entries = cache.get_batch(paths)
            attached_paths: set[str] = set()
            for project, path in zip(projects, paths, strict=True):
                try:
                    cached = cached_entries.get(path)
                    if not cached or cached.mtime != project["mtime"] or not cached.preview_path:
                        continue
                    project_path = (root / project["path"]).resolve()
                    preview_input = Path(cached.preview_path)
                    preview = preview_input.resolve()
                    preview.relative_to(root)
                    preview.relative_to(project_path)
                    if self._path_contains_link_or_reparse(root, preview_input):
                        continue
                    if not preview.is_file():
                        continue
                    rel_preview = os.path.relpath(preview, root).replace("\\", "/")
                    project["thumbnail_path"] = rel_preview
                    attached_paths.add(path)
                except (OSError, ValueError):
                    continue
            ProjectService._attach_baked_thumbnails(
                root, projects, paths, attached_paths, db_conn,
            )
        except OSError:
            return

    @staticmethod
    def _attach_baked_thumbnails(
        library_root: Path,
        projects: list[dict],
        project_paths: list[str],
        attached_paths: set[str],
        db_conn: sqlite3.Connection,
    ) -> None:
        """Project baked thumbnail rows onto projects without directory previews."""
        # Fast path: every project already has a directory-cache preview, so
        # the full thumbnail_cache scan (plus two stats per row) is pure waste.
        if len(attached_paths) == len(project_paths):
            return
        try:
            rows = ThumbnailRepository(db_conn).list_metadata()
        except sqlite3.ProgrammingError:
            raise
        except sqlite3.Error:
            _log.warning("baked thumbnail cache query failed", exc_info=True)
            return

        baked_root = thumb_dir(str(library_root)).resolve()
        project_by_path = {
            Path(project_path): project_path
            for project_path in project_paths
            if project_path not in attached_paths
        }
        candidates: dict[str, tuple[Path, str, int, tuple[int, int, str, str]]] = {}
        for row in rows:
            try:
                if row.artifact_kind != "webp":
                    continue
                cache_key = str(row.cache_key)
                profile = row.render_profile
                if profile is None:
                    profile_token = ""
                    profile_known = 0
                else:
                    profile_token = normalize_webp_render_profile(str(profile))
                    profile_known = 1
                profile_size = int(row.baked_size)
                if profile_size <= 0:
                    continue
                if profile_known and profile_size != WEBP_RENDER_PROFILES[profile_token]:
                    continue
                source_input = Path(row.source_path)
                if source_input.suffix.lower() not in IMAGE_EXTS:
                    continue
                source = source_input.resolve()
                source.relative_to(library_root)
                if ProjectService._path_contains_link_or_reparse(
                    library_root, source_input
                ):
                    continue
                source_stat = source.stat()
                if not source.is_file() or source_stat.st_size != int(row.source_size):
                    continue
                if row.source_mtime_ns is not None:
                    if source_stat.st_mtime_ns != int(row.source_mtime_ns):
                        continue
                elif source_stat.st_mtime != row.source_mtime:
                    continue
                baked_candidate = baked_root / f"{cache_key}.webp"
                baked_input = artifact_path(baked_root, cache_key, "webp")
                if baked_input is None:
                    continue
                if ProjectService._path_contains_link_or_reparse(
                    baked_root, baked_candidate
                ):
                    continue
                baked = baked_input
                baked_stat = baked.stat()
                if not baked.is_file() or baked_stat.st_mtime <= 0:
                    continue
                if admit_thumbnail_cache_artifact(baked, profile_size) is None:
                    continue
                project_path = source.parent
                while project_path != library_root.parent:
                    project_key = project_by_path.get(project_path)
                    if project_key is not None:
                        source.relative_to(project_path)
                        rank = (profile_size, profile_known, profile_token, cache_key)
                        current = candidates.get(project_key)
                        if current is None or rank > current[3]:
                            candidates[project_key] = (
                                source, cache_key, profile_size, rank,
                            )
                        break
                    if project_path == library_root:
                        break
                    project_path = project_path.parent
            except (OSError, TypeError, ValueError):
                continue

        for project, project_path in zip(projects, project_paths, strict=True):
            if project_path in attached_paths:
                continue
            candidate = candidates.get(project_path)
            if candidate is None:
                continue
            source, _cache_key, _profile_size, _rank = candidate
            rel_source = os.path.relpath(source, library_root).replace("\\", "/")
            project["thumbnail_path"] = rel_source

    @session_operation
    def count_projects(
        self,
        library_root: str | Path,
        depth_config: ProjectDepthConfig | None = None,
    ) -> int:
        """Count total projects at effective depth."""
        root = Path(library_root).resolve()
        depth_config = depth_config or ProjectDepthConfig()
        return self._count_projects_recursive(root, root, 0, "", depth_config)

    def _count_projects_recursive(
        self,
        library_root: Path,
        current: Path,
        depth: int,
        branch_name: str,
        depth_config: ProjectDepthConfig,
    ) -> int:
        count = 0
        try:
            entries = sorted(
                self._safe_directory_entries(current),
                key=lambda e: e.name.lower(),
            )
        except OSError:
            _log.warning("project count scan failed: %s", current, exc_info=True)
            return count
        for entry in entries:
            child_branch = branch_name or entry.name
            effective_depth = depth_config.branches.get(child_branch, depth_config.global_depth)
            if (depth + 1) >= effective_depth:
                count += 1
            else:
                count += self._count_projects_recursive(library_root, Path(entry.path), depth + 1, child_branch, depth_config)
        return count

    def _popular_tags(self, root: Path, db_conn: sqlite3.Connection | None) -> list[dict]:
        try:
            return self._tag_svc.list_tags(root, db_conn=db_conn)[:20]
        except sqlite3.ProgrammingError:
            raise
        except sqlite3.Error:
            _log.warning("popular tags query failed", exc_info=True)
            return []

    @staticmethod
    def _library_total_size(root: Path, db_conn: sqlite3.Connection | None) -> int:
        if db_conn is None:
            return 0
        try:
            return MetadataRepository(db_conn).get_library_total_size(str(root))
        except sqlite3.ProgrammingError:
            raise
        except sqlite3.Error:
            _log.warning("library total size query failed", exc_info=True)
            return 0

    @session_operation
    def get_project_detail(
        self,
        library_root: str | Path,
        target: str | Path,
        rel_path: str,
        db_conn: sqlite3.Connection | None = None,
    ) -> ProjectDetail:
        root = Path(library_root).resolve()
        lexical_target, target_path = self._admit_public_target(root, target)
        db_conn = self._connection(root, db_conn)
        rel_path = rel_path.replace("\\", "/").strip("/")
        notes, urls = self._notes_and_urls(root, target_path)
        self._revalidate_public_target(root, lexical_target, target_path)
        files, images = self._project_files(root, target_path)
        self._revalidate_public_target(root, lexical_target, target_path)
        preview = self._first_image(target_path)
        self._revalidate_public_target(root, lexical_target, target_path)
        thumb_path = None
        if preview:
            rel_preview = os.path.relpath(preview, root).replace("\\", "/")
            thumb_path = rel_preview
        self._revalidate_public_target(root, lexical_target, target_path)
        try:
            modified = target_path.stat().st_mtime
        except OSError:
            _log.warning("project mtime lookup failed: %s", target_path, exc_info=True)
            modified = 0

        return ProjectDetail(
            name=target_path.name,
            path=rel_path,
            tags=self._tags(root, target_path, db_conn),
            notes=notes,
            urls=urls,
            total_size=self._dir_size(root, target_path),
            file_count=len(files),
            files=files,
            images=images,
            thumbnail_path=thumb_path,
            modified=modified,
        )

    @session_operation
    def build_tree(
        self,
        library_root: str | Path,
        depth_config: ProjectDepthConfig | None = None,
    ) -> ProjectTree:
        root = Path(library_root).resolve()
        depth_config = depth_config or ProjectDepthConfig()
        tree = self._scan_tree(root, root, 0, "", depth_config)
        return ProjectTree(tree=tree, depth_config=depth_config)

    def _scan_tree(
        self,
        library_root: Path,
        current: Path,
        depth: int,
        branch_name: str,
        depth_config: ProjectDepthConfig,
    ) -> list[dict]:
        nodes: list[dict] = []
        try:
            entries = sorted(
                self._safe_directory_entries(current),
                key=lambda e: e.name.lower(),
            )
        except OSError:
            _log.warning("project tree scan failed: %s", current, exc_info=True)
            return nodes
        for entry in entries:
            rel = os.path.relpath(entry.path, library_root).replace("\\", "/")
            child_branch = branch_name or entry.name
            effective_depth = depth_config.branches.get(child_branch, depth_config.global_depth)
            is_leaf = (depth + 1) >= effective_depth
            node = {
                "name": entry.name,
                "path": rel,
                "is_leaf": is_leaf,
                "children": [] if is_leaf else self._scan_tree(library_root, Path(entry.path), depth + 1, child_branch, depth_config),
            }
            nodes.append(node)
        return nodes

    def _entry_to_item(
        self,
        root: Path,
        entry: os.DirEntry,
        current_depth: int,
        depth_config: ProjectDepthConfig,
        db_conn: sqlite3.Connection | None,
    ) -> ProjectListItem:
        entry_path = Path(entry.path)
        rel = os.path.relpath(entry.path, root).replace("\\", "/")
        child_depth = current_depth + 1
        branch_name = rel.split("/")[0] if "/" in rel else rel
        effective_depth = depth_config.branches.get(branch_name, depth_config.global_depth)
        is_project = child_depth >= effective_depth

        preview = self._first_image(entry_path)
        thumb_path = None
        if preview:
            rel_preview = os.path.relpath(preview, root).replace("\\", "/")
            thumb_path = rel_preview

        total_size = self._dir_size(root, entry_path)
        file_count = self._file_count(root, entry_path, db_conn)
        tags = self._tags(root, entry_path, db_conn) if is_project else []
        notes = self._notes(root, entry_path) if is_project else ""
        try:
            modified = entry.stat(follow_symlinks=False).st_mtime
        except OSError:
            _log.warning("project mtime lookup failed: %s", entry.path, exc_info=True)
            modified = 0

        return ProjectListItem(
            name=entry.name,
            path=rel,
            is_project=is_project,
            thumbnail_path=thumb_path,
            tags=tags,
            total_size=total_size,
            file_count=file_count,
            notes=notes,
            modified=modified,
        )

    @staticmethod
    def _project_files(root: Path, target: Path) -> tuple[list[dict], list[dict]]:
        files: list[dict] = []
        images: list[dict] = []
        entries = sorted(
            ProjectService._safe_file_entries(target),
            key=lambda e: e.name.lower(),
        )
        for entry in entries:
            ext = Path(entry.name).suffix.lower()
            category = CATEGORY_MAP.get(ext, "other")
            try:
                size = entry.stat(follow_symlinks=False).st_size
            except OSError:
                _log.warning("project file size lookup failed: %s", entry.path, exc_info=True)
                size = 0
            files.append({
                "name": entry.name,
                "size": size,
                "size_fmt": format_size(size),
                "extension": ext,
                "category": category,
            })
            if ext in IMAGE_EXTS:
                rel_img = os.path.relpath(entry.path, root).replace("\\", "/")
                images.append({"name": entry.name, "path": rel_img})
        return files, images

    @staticmethod
    def _current_depth(root: Path, target: Path) -> int:
        try:
            rel_to_root = os.path.relpath(target, root)
        except ValueError:
            rel_to_root = ""
        return len([p for p in rel_to_root.replace("\\", "/").split("/") if p and p != "."])

    @staticmethod
    def _sort(items: list[ProjectListItem], sort_by: str, order: str) -> None:
        reverse = order == "desc"
        if sort_by == "name":
            items.sort(key=lambda item: item.name.lower(), reverse=reverse)
        elif sort_by == "date":
            items.sort(key=lambda item: item.modified, reverse=reverse)
        elif sort_by == "size":
            items.sort(key=lambda item: item.total_size, reverse=reverse)
        items.sort(key=lambda item: 0 if item.is_project else -1)

    def _dir_size(self, root: Path, path: Path) -> int:
        try:
            total_size, _ = self._metadata_svc.get_dir_size(root, path, force=False)
            return total_size
        except sqlite3.ProgrammingError:
            raise
        except (OSError, sqlite3.Error):
            _log.warning("directory size query failed", exc_info=True)
            return 0

    def _file_count(self, root: Path, path: Path, db_conn: sqlite3.Connection | None) -> int:
        if db_conn is not None:
            try:
                indexed = AssetIndexRepository(db_conn).query_by_parent(
                    str(root.resolve()), str(path.resolve()),
                )
                if indexed:
                    return sum(
                        1
                        for indexed_entry in indexed
                        if self._safe_file_path(root, Path(indexed_entry.file_path))
                    )
                cached_count = MetadataRepository(db_conn).get_cached_file_count(
                    str(path.resolve())
                )
                if cached_count is not None:
                    return cached_count
            except sqlite3.ProgrammingError:
                raise
            except sqlite3.Error:
                _log.warning("file count cache query failed", exc_info=True)

        try:
            file_count = len(ProjectService._safe_file_entries(path))
        except OSError:
            _log.warning("file count scan failed: %s", path, exc_info=True)
            return 0

        if db_conn is not None:
            try:
                MetadataRepository(db_conn).set_cached_file_count(
                    str(path.resolve()), file_count
                )
            except sqlite3.ProgrammingError:
                raise
            except sqlite3.Error:
                _log.warning("file count cache write failed", exc_info=True)
        return file_count

    def _tags(self, root: Path, path: Path, db_conn: sqlite3.Connection | None) -> list[str]:
        try:
            return self._tag_svc.get_tags_for_tree(root, path, db_conn=db_conn)
        except sqlite3.ProgrammingError:
            raise
        except (OSError, sqlite3.Error):
            _log.warning("tag query failed", exc_info=True)
            return []

    def _notes(self, root: Path, path: Path) -> str:
        try:
            return self._metadata_svc.get_notes(root, path)
        except sqlite3.ProgrammingError:
            raise
        except (OSError, sqlite3.Error):
            _log.warning("notes query failed", exc_info=True)
            return ""

    def _notes_and_urls(self, root: Path, path: Path) -> tuple[str, list[str]]:
        try:
            metadata = self._metadata_svc.get_metadata(root, path)
            return metadata.notes, list(metadata.urls)
        except sqlite3.ProgrammingError:
            raise
        except (OSError, sqlite3.Error):
            _log.warning("metadata query failed", exc_info=True)
            return "", []
