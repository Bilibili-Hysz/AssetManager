"""File listing route: /api/files."""
import asyncio
import os
from time import perf_counter
from urllib.parse import quote

from aiohttp import web

from AssetsManager.application import DirectoryListOptions, ProjectDepthConfig
from AssetsManager.core.format_utils import format_size
from AssetsManager.domain.errors import ValidationError
from AssetsManager.lan.routes._helpers import get_lan, get_asset_service, get_metadata_service, require_permission, validate_path


async def handle_files(request):
    lan = get_lan(request)
    started = perf_counter()
    target = None
    outcome = "error"
    status = 500
    item_count = -1
    try:
        if not require_permission(request, "browse"):
            status = 403
            return web.json_response({"error": "Forbidden"}, status=status)
        rel_path = request.query.get("path", "")
        sort_by = request.query.get("sort", "name")
        order = request.query.get("order", "asc")
        filter_cat = request.query.get("filter", "all")
        search = request.query.get("search", "").lower()

        target = validate_path(lan, rel_path)
        if not target.is_dir():
            status = 404
            return web.json_response({"error": "Not a directory"}, status=status)

        settings = lan.current_settings
        from AssetsManager.core.settings import AppSettings
        depth_config = ProjectDepthConfig.from_dict(AppSettings.instance().get("sidebar_depth_cfg"))
        show_hidden = settings.get("show_hidden", False)
        include_types = settings.get("include_types", None)
        exclude_patterns = settings.get("exclude_patterns", [])
        max_depth = settings.get("max_depth", 0)
        current_depth = len(rel_path.strip("/").split("/")) if rel_path.strip("/") else 0
        scan_summaries = request.query.get("summaries", "true").lower() == "true"

        def _list():
            return get_asset_service(request).list_directory(
                lan.library_root,
                target,
                DirectoryListOptions(
                    sort_by=sort_by,
                    order=order,
                    filter_category=filter_cat,
                    search=search,
                    show_hidden=show_hidden,
                    include_types=tuple(include_types) if include_types else None,
                    exclude_patterns=tuple(exclude_patterns or []),
                    max_depth=max_depth,
                    current_depth=current_depth,
                    scan_summaries=scan_summaries,
                    project_depth=depth_config.global_depth,
                    branch_name=rel_path.strip("/").split("/", 1)[0] if rel_path.strip("/") else None,
                    branch_depths=depth_config.branches,
                ),
            )

        try:
            listing = await asyncio.to_thread(_list)
        except PermissionError:
            status = 403
            return web.json_response({"error": "Permission denied"}, status=status)
        except OSError:
            status = 500
            return web.json_response({"error": "Failed to list directory"}, status=status)

        file_paths = [str(item.absolute_path) for item in listing.items if not item.is_dir]
        cached_stats = get_metadata_service(request).get_cached_stats(
            lan.library_root, file_paths
        )

        items = []
        for item in listing.items:
            if item.is_dir:
                thumb_url = None
                if item.preview_path:
                    rel_preview = os.path.relpath(item.preview_path, lan.library_root).replace("\\", "/")
                    thumb_url = f"/api/thumbnails/{quote(rel_preview, safe='/')}"
                items.append({
                    "name": item.name, "path": item.path, "type": "dir",
                    "size": 0, "size_fmt": item.size_fmt,
                    "modified": item.modified, "extension": item.extension, "category": item.category,
                    "is_project": item.is_project,
                    "thumbnail_url": thumb_url,
                })
            else:
                cached = cached_stats.get(str(item.absolute_path))
                if cached and cached[0] is not None and cached[1] is not None:
                    fs, mtime = cached
                else:
                    fs, mtime = item.size, item.modified
                rel_enc = quote(item.path, safe="/")
                thumb_url = f"/api/thumbnails/{rel_enc}"
                items.append({
                    "name": item.name, "path": item.path, "type": "file",
                    "size": fs, "size_fmt": format_size(fs),
                    "modified": mtime, "extension": item.extension, "category": item.category,
                    "is_project": False,
                    "thumbnail_url": thumb_url,
                })

        total = sum(i["size"] for i in items)
        outcome = "success"
        status = 200
        item_count = listing.total_count
        return web.json_response({
            "current_path": listing.current_path,
            "parent_path": listing.parent_path,
            "items": items,
            "total_count": listing.total_count,
            "total_size": total,
            "total_size_fmt": format_size(total),
        })
    except web.HTTPException as exc:
        status = exc.status
        raise
    finally:
        _record_files_route(lan, started, target, outcome, status, item_count)


async def handle_directory_summaries(request):
    """Hydrate a bounded set of direct child-directory summaries on demand."""
    lan = get_lan(request)
    started = perf_counter()
    status = 500
    requested_count = 0
    result_count = 0
    outcome = "error"
    try:
        if not require_permission(request, "browse"):
            status = 403
            return web.json_response({"error": "Forbidden"}, status=status)
        try:
            payload = await request.json()
        except (ValueError, TypeError):
            status = 400
            return web.json_response({"error": "Invalid JSON body"}, status=status)
        parent_path = payload.get("parent_path") if isinstance(payload, dict) else None
        paths = payload.get("paths") if isinstance(payload, dict) else None
        if not isinstance(parent_path, str) or not isinstance(paths, list):
            status = 400
            return web.json_response({"error": "parent_path and 1-48 paths are required"}, status=status)

        asset_service = get_asset_service(request)
        try:
            asset_service.validate_directory_summary_paths(paths)
        except ValidationError as exc:
            status = 400
            return web.json_response({"error": exc.message}, status=status)
        requested_count = len(paths)

        try:
            parent = validate_path(lan, parent_path)
            try:
                parent = asset_service.validate_directory_summary_parent(parent)
            except ValidationError as exc:
                status = 400
                return web.json_response({"error": exc.message}, status=status)
            directories = [validate_path(lan, path) for path in paths]
        except (web.HTTPException, OSError):
            status = 400
            return web.json_response({"error": "Invalid directory path"}, status=status)

        try:
            summaries = await asyncio.to_thread(
                asset_service.summarize_directories, directories, parent=parent
            )
        except ValidationError as exc:
            status = 400
            return web.json_response({"error": exc.message}, status=status)
        items = []
        for path, directory in zip(paths, directories, strict=True):
            preview, item_count = summaries[str(directory)]
            thumbnail_url = None
            if preview:
                relative_preview = os.path.relpath(preview, lan.library_root).replace("\\", "/")
                thumbnail_url = f"/api/thumbnails/{quote(relative_preview, safe='/')}"
            items.append({"path": path, "item_count": item_count, "size_fmt": f"{item_count} items", "thumbnail_url": thumbnail_url})
        status = 200
        outcome = "success"
        result_count = len(items)
        return web.json_response({"items": items})
    finally:
        _record_directory_summaries_route(lan, started, outcome, status, requested_count, result_count)

def _record_files_route(lan, started: float, target, outcome: str, status: int, item_count: int) -> None:
    recorder = getattr(lan, "performance_recorder", None)
    if recorder is None or not recorder.enabled:
        return
    try:
        recorder.record(
            "lan.files",
            (perf_counter() - started) * 1000,
            session_token=getattr(lan, "session_token", None),
            path=str(target) if target is not None else None,
            attributes={"outcome": outcome, "status": status, "item_count": item_count},
        )
    except Exception:
        # Observability must not alter an HTTP response after work completed.
        pass


def _record_directory_summaries_route(lan, started: float, outcome: str, status: int, requested_count: int, result_count: int) -> None:
    recorder = getattr(lan, "performance_recorder", None)
    if recorder is None or not recorder.enabled:
        return
    try:
        recorder.record(
            "lan.directory_summaries",
            (perf_counter() - started) * 1000,
            session_token=getattr(lan, "session_token", None),
            attributes={
                "outcome": outcome, "status": status,
                "requested_count": requested_count, "result_count": result_count,
            },
        )
    except Exception:
        pass
