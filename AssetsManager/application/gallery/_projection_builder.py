"""Gallery projection builder mixin: walk the filesystem into response nodes.

Owns path normalization, per-image description, reparse-point checks and the
recursive ``_build_node`` / ``_build_project_node`` traversal.  It references
``_project_floor`` (owned by ``_GalleryIncrementalMixin``) and ``_closed``
(owned by ``GalleryService``); those are declared below so static analysis
resolves them without a runtime import cycle.
"""
from __future__ import annotations

import os
from pathlib import Path
from stat import S_ISREG
from typing import Any, Callable

from AssetsManager.application.project_service import ProjectDepthConfig
from AssetsManager.core.format_utils import format_size
from AssetsManager.domain.asset import assert_under_root
from AssetsManager.domain.errors import MissingPathError, PathEscapeError

from AssetsManager.application.gallery._types import (
    GalleryImage,
    GalleryTraversalLimitError,
    _FILE_ATTRIBUTE_REPARSE_POINT,
    _ImageRef,
    _SAFE_GALLERY_IMAGE_EXTS,
    _StateNode,
    _TraversalBudget,
)

try:  # Pillow is a runtime dependency, but metadata must remain best-effort.
    from PIL import Image
except Exception:  # pragma: no cover - exercised only in minimal installations.
    Image = None  # type: ignore[assignment,misc]


class _GalleryProjectionMixin:
    # ``_closed`` is owned by GalleryService.__init__; ``_project_floor`` is
    # a staticmethod owned by _GalleryIncrementalMixin. Declared so pyright
    # resolves self._closed / self._project_floor inside this mixin.
    _closed: bool = False
    _project_floor: Callable[..., int]

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
                    if self._closed:
                        raise GalleryTraversalLimitError("Gallery build cancelled")
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

    def _aggregate_project(
        self,
        root: Path,
        relative_path: str,
        target: Path,
        *,
        budget: _TraversalBudget,
        depth: int,
        image_refs: list[_ImageRef] | None = None,
        known_files: dict[str, tuple[int, int]] | None = None,
    ) -> tuple[int, int, list[tuple[str, os.stat_result]], int]:
        """Walk one project subtree without projecting child nodes.

        The project is the gallery's display leaf (project depth from
        ``sidebar_depth_cfg``): its whole subtree collapses into size /
        file count / latest modification and an artwork list.  No child
        summaries, covers, or state nodes are produced for inner
        directories, which is what keeps very large libraries (and their
        textures/models folders) from generating a cover per directory.
        """
        budget.enter_directory(depth)
        total_size = 0
        file_count = 0
        latest_modified = 0
        images: list[tuple[str, os.stat_result]] = []
        stack: list[tuple[Path, str, int]] = [(target, relative_path, depth)]
        while stack:
            current, rel, current_depth = stack.pop()
            if self._closed:
                raise GalleryTraversalLimitError("Gallery build cancelled")
            for entry, stat_result in self._visible_entries(current, budget, current_depth):
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                    is_file = entry.is_file(follow_symlinks=False)
                except OSError:
                    continue
                child_rel = "/".join(part for part in (rel, entry.name) if part)
                if is_dir:
                    stack.append((Path(entry.path), child_rel, current_depth + 1))
                    continue
                if not is_file:
                    continue
                if stat_result is None:
                    try:
                        stat_result = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                total_size += int(stat_result.st_size)
                file_count += 1
                modified = int(stat_result.st_mtime)
                latest_modified = max(latest_modified, modified)
                if known_files is not None:
                    known_files[child_rel] = (int(stat_result.st_size), modified)
                if entry.name.lower().endswith(tuple(_SAFE_GALLERY_IMAGE_EXTS)):
                    images.append((child_rel, stat_result))
                    if image_refs is not None:
                        image_refs.append(_ImageRef(child_rel, modified))
        images.sort(key=lambda item: item[0].casefold())
        return total_size, file_count, images, latest_modified

    def _build_project_node(
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
    ) -> dict[str, Any] | None:
        """Build one project leaf node: the whole subtree aggregates into a
        single node (stats, artwork list, cover) with no inner directory
        projected.  Used both from ``_build_node`` for directories at the
        project floor and directly for project-root collection pages."""
        proj_size, proj_files, proj_images, proj_modified = self._aggregate_project(
            root, relative_path, target,
            budget=budget,
            depth=depth,
            image_refs=image_refs,
            known_files=known_files,
        )
        if proj_files == 0:
            return None  # empty subtree pruned like an empty directory
        cover_path = proj_images[0][0] if proj_images else None
        cover = (
            self._describe_image(root, cover_path, budget=budget)
            if cover_path
            else None
        )
        node: dict[str, Any] = {
            "name": target.name,
            "path": relative_path,
            "kind": "project",
            "parent_path": self._parent_path(relative_path),
            "cover_path": cover_path,
            "width": cover.get("width") if cover else None,
            "height": cover.get("height") if cover else None,
            "aspect_ratio": cover.get("aspect_ratio") if cover else None,
            "modified": proj_modified,
            "size": proj_size,
            "size_fmt": format_size(proj_size),
            "file_count": proj_files,
            "artwork_count": len(proj_images),
            "child_count": 0,
            "tags": [],
        }
        if include_entries:
            node["entries"] = [
                described
                for path, stat_result in proj_images
                if (
                    described := self._describe_image(
                        root, path, stat_result=stat_result, budget=budget
                    )
                )
            ]
        if node_counts is not None:
            node_counts["project"] = node_counts.get("project", 0) + 1
        if state_nodes is not None:
            state_nodes[relative_path] = _StateNode(
                summary=self._summary(node),
                direct_images=[path for path, _stat_result in proj_images],
                children=[],
            )
        return node

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
        project_depth: ProjectDepthConfig | None = None,
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
        if project_depth is not None and relative_path:
            # A caller may point straight into a project (e.g. a stale
            # /gallery/collection link). The project is the display leaf;
            # anything deeper is not part of the projection.
            if len(relative_path.split("/")) > self._project_floor(project_depth, relative_path):
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
                child_floor = (
                    self._project_floor(project_depth, child_relative)
                    if project_depth is not None
                    else None
                )
                if child_floor is not None and depth + 1 == child_floor:
                    # Project leaf: aggregate the whole subtree into one
                    # node (project depth from sidebar_depth_cfg) instead
                    # of projecting every inner directory.
                    child_node = self._build_project_node(
                        root, child_relative, child_path,
                        include_entries=False,
                        budget=budget,
                        depth=depth + 1,
                        image_refs=image_refs,
                        node_counts=node_counts,
                        state_nodes=state_nodes,
                        known_files=known_files,
                    )
                    if child_node is None:
                        continue
                    child_nodes.append(child_node)
                    total_size += int(child_node["size"])
                    file_count += int(child_node["file_count"])
                    latest_modified = max(latest_modified, int(child_node["modified"]))
                    continue
                if child_floor is not None and depth + 1 > child_floor:
                    # Inside a project while building a project root
                    # directly: not part of the projection (project roots
                    # go through _build_project_node, so this is defensive).
                    continue
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
                    project_depth=project_depth,
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
