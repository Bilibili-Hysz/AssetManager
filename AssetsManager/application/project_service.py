"""Project listing application service."""
from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from AssetsManager.application.asset_filters import IMAGE_EXTS, find_first_image
from AssetsManager.application.asset_index_service import AssetIndexService
from AssetsManager.application.context import ConnectionProvider, LibrarySession, SessionBoundOperations
from AssetsManager.application.metadata_service import MetadataService
from AssetsManager.application.tag_service import TagService
from AssetsManager.core.database import db_write_lock
from AssetsManager.core.format_utils import CATEGORY_MAP, format_size

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProjectDepthConfig:
    global_depth: int = 2
    branch_depths: dict[str, int] | None = None

    @classmethod
    def from_dict(cls, data: dict | None) -> "ProjectDepthConfig":
        data = data or {}
        return cls(
            global_depth=int(data.get("depth", 2)),
            branch_depths=dict(data.get("branch_depths", {}) or {}),
        )

    @property
    def branches(self) -> dict[str, int]:
        return self.branch_depths or {}


@dataclass(frozen=True)
class ProjectListItem:
    name: str
    path: str
    is_project: bool
    thumbnail_url: str | None
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
            "thumbnail_url": self.thumbnail_url,
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
    thumbnail_url: str | None
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
            "thumbnail_url": self.thumbnail_url,
            "modified": self.modified,
            "download_url": f"/api/download/{quote(self.path, safe='/')}",
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
    popular_tags: list[dict]
    total_projects: int
    total_size: int

    def to_response(self) -> dict:
        return {
            "recent_projects": self.recent_projects,
            "popular_tags": self.popular_tags,
            "stats": {
                "total_projects": self.total_projects,
                "total_size": self.total_size,
                "total_size_fmt": format_size(self.total_size),
            },
        }


class ProjectService(SessionBoundOperations):
    """Build project list responses shared by LAN routes and future desktop views."""

    def __init__(self, connection_provider: ConnectionProvider,
                 session: LibrarySession | None = None):
        self._metadata_svc = MetadataService(connection_provider=connection_provider)
        self._tag_svc = TagService(connection_provider=connection_provider)
        if session is not None:
            self._bind_session(session)

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
        target_path = Path(target).resolve()
        depth_config = depth_config or ProjectDepthConfig()
        rel_path = rel_path.replace("\\", "/").strip("/")
        search = search.lower()
        current_depth = self._current_depth(root, target_path)

        # Collect candidate directories
        candidates: list[os.DirEntry] = []
        for entry in os.scandir(target_path):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            if search and search not in entry.name.lower():
                continue
            candidates.append(entry)

        # Batch-warm file_count cache for all candidates
        if db_conn is not None:
            self._batch_warm_file_counts(root, candidates, db_conn)

        items: list[ProjectListItem] = []
        for entry in candidates:
            items.append(self._entry_to_item(root, entry, current_depth, depth_config, db_conn))

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
            placeholders = ",".join("?" * len(paths))
            rows = db_conn.execute(
                f"SELECT file_path, cached_file_count FROM file_meta "
                f"WHERE file_path IN ({placeholders}) AND cached_file_count IS NOT NULL",
                paths,
            ).fetchall()
            cached = {r[0]: r[1] for r in rows if r[1] and r[1] > 0}
        except Exception:
            _log.debug("batch file count cache query failed")
            cached = {}

        # Compute counts for uncached directories
        to_write: dict[str, int] = {}
        for entry, path in zip(entries, paths):
            if path in cached:
                continue
            try:
                count = sum(1 for f in os.scandir(entry.path) if f.is_file() and not f.name.startswith("."))
            except OSError:
                count = 0
            to_write[path] = count

        # Batch write
        if to_write:
            try:
                with db_write_lock():
                    db_conn.executemany(
                        "INSERT INTO file_meta (file_path, cached_file_count) VALUES (?, ?) "
                        "ON CONFLICT(file_path) DO UPDATE SET cached_file_count=excluded.cached_file_count",
                        list(to_write.items()),
                    )
                    db_conn.commit()
            except Exception:
                _log.debug("batch file count cache write failed")

    def get_home(
        self,
        library_root: str | Path,
        depth_config: ProjectDepthConfig | None = None,
        db_conn: sqlite3.Connection | None = None,
    ) -> ProjectHome:
        root = Path(library_root).resolve()
        depth_config = depth_config or ProjectDepthConfig()
        projects = self._collect_projects(root, root, 0, "", depth_config)
        recent = sorted(projects, key=lambda p: p["mtime"], reverse=True)[:20]
        popular_tags = self._popular_tags(root, db_conn)
        total_size = self._library_total_size(root, db_conn)
        return ProjectHome(
            recent_projects=recent,
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
                [e for e in os.scandir(current) if e.is_dir() and not e.name.startswith(".")],
                key=lambda e: e.name.lower(),
            )
        except OSError:
            return projects
        for entry in entries:
            rel = os.path.relpath(entry.path, library_root).replace("\\", "/")
            child_branch = branch_name or entry.name
            effective_depth = depth_config.branches.get(child_branch, depth_config.global_depth)
            if (depth + 1) >= effective_depth:
                try:
                    mtime = entry.stat().st_mtime
                except OSError:
                    mtime = 0
                projects.append({"name": entry.name, "path": rel, "mtime": mtime})
            else:
                projects.extend(self._collect_projects(library_root, Path(entry.path), depth + 1, child_branch, depth_config))
        return projects

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
                [e for e in os.scandir(current) if e.is_dir() and not e.name.startswith(".")],
                key=lambda e: e.name.lower(),
            )
        except OSError:
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
        except Exception:
            _log.debug("popular tags query failed")
            return []

    @staticmethod
    def _library_total_size(root: Path, db_conn: sqlite3.Connection | None) -> int:
        if db_conn is None:
            return 0
        try:
            row = db_conn.execute(
                "SELECT total_size FROM library_stats WHERE library_path=?",
                (str(root),),
            ).fetchone()
            return (row[0] or 0) if row else 0
        except Exception:
            _log.debug("library total size query failed")
            return 0

    def get_project_detail(
        self,
        library_root: str | Path,
        target: str | Path,
        rel_path: str,
        db_conn: sqlite3.Connection | None = None,
    ) -> ProjectDetail:
        root = Path(library_root).resolve()
        target_path = Path(target).resolve()
        rel_path = rel_path.replace("\\", "/").strip("/")
        notes, urls = self._notes_and_urls(root, target_path)
        files, images = self._project_files(root, target_path)
        preview = find_first_image(target_path)
        thumb_url = None
        if preview:
            rel_preview = os.path.relpath(preview, root).replace("\\", "/")
            thumb_url = f"/api/thumbnails/{quote(rel_preview, safe='/')}"
        try:
            modified = target_path.stat().st_mtime
        except OSError:
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
            thumbnail_url=thumb_url,
            modified=modified,
        )

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
                [e for e in os.scandir(current) if e.is_dir() and not e.name.startswith(".")],
                key=lambda e: e.name.lower(),
            )
        except OSError:
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

        preview = find_first_image(entry_path)
        thumb_url = None
        if preview:
            rel_preview = os.path.relpath(preview, root).replace("\\", "/")
            thumb_url = f"/api/thumbnails/{quote(rel_preview, safe='/')}"

        total_size = self._dir_size(root, entry_path)
        file_count = self._file_count(root, entry_path, db_conn)
        tags = self._tags(root, entry_path, db_conn) if is_project else []
        notes = self._notes(root, entry_path) if is_project else ""
        try:
            modified = entry.stat().st_mtime
        except OSError:
            modified = 0

        return ProjectListItem(
            name=entry.name,
            path=rel,
            is_project=is_project,
            thumbnail_url=thumb_url,
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
        try:
            entries = sorted(os.scandir(target), key=lambda e: e.name.lower())
        except OSError:
            return files, images
        for entry in entries:
            if not entry.is_file() or entry.name.startswith("."):
                continue
            ext = Path(entry.name).suffix.lower()
            category = CATEGORY_MAP.get(ext, "other")
            try:
                size = entry.stat().st_size
            except OSError:
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
                images.append({
                    "name": entry.name,
                    "url": f"/api/thumbnails/{quote(rel_img, safe='/')}?size=1920",
                    "thumb_url": f"/api/thumbnails/{quote(rel_img, safe='/')}?size=512",
                })
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
        except Exception:
            _log.debug("directory size query failed")
            return 0

    @staticmethod
    def _file_count(root: Path, path: Path, db_conn: sqlite3.Connection | None) -> int:
        if db_conn is not None:
            try:
                indexed = AssetIndexService().query_by_parent(db_conn, root, path)
                if indexed:
                    return len(indexed)
                count_row = db_conn.execute(
                    "SELECT cached_file_count FROM file_meta WHERE file_path=?",
                    (str(path.resolve()),),
                ).fetchone()
                if count_row and count_row[0] is not None and count_row[0] > 0:
                    return count_row[0]
            except Exception:
                _log.debug("file count cache query failed")

        try:
            file_count = sum(1 for f in os.scandir(path) if f.is_file() and not f.name.startswith("."))
        except OSError:
            return 0

        if db_conn is not None:
            try:
                with db_write_lock():
                    db_conn.execute(
                        "INSERT INTO file_meta (file_path, cached_file_count) VALUES (?,?) "
                        "ON CONFLICT(file_path) DO UPDATE SET cached_file_count=excluded.cached_file_count",
                        (str(path.resolve()), file_count),
                    )
                    db_conn.commit()
            except Exception:
                _log.debug("file count cache write failed")
        return file_count

    def _tags(self, root: Path, path: Path, db_conn: sqlite3.Connection | None) -> list[str]:
        try:
            return self._tag_svc.get_tags_for_tree(root, path, db_conn=db_conn)
        except Exception:
            _log.debug("tag query failed")
            return []

    def _notes(self, root: Path, path: Path) -> str:
        try:
            return self._metadata_svc.get_notes(root, path)
        except Exception:
            _log.debug("notes query failed")
            return ""

    def _notes_and_urls(self, root: Path, path: Path) -> tuple[str, list[str]]:
        try:
            metadata = self._metadata_svc.get_metadata(root, path)
            return metadata.notes, list(metadata.urls)
        except Exception:
            _log.debug("metadata query failed")
            return "", []
