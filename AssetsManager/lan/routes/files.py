"""File listing route: /api/files."""
import asyncio
import os
from time import perf_counter
from urllib.parse import quote

from aiohttp import web

from AssetsManager.application import DirectoryListOptions, ProjectDepthConfig
from AssetsManager.core.format_utils import format_size
from AssetsManager.domain.errors import ValidationError
from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.routes._helpers import get_lan, get_asset_service, get_metadata_service, require_permission, validate_path
from AssetsManager.lan.routes._telemetry import record_route_event


# Upper bound for one paginated files page (LAN large-library prework).
FILES_MAX_LIMIT = 1000


def _parse_paging(request) -> tuple[int | None, int] | web.Response:
    """Parse optional ``limit``/``offset`` query params.

    Returns ``(limit, offset)`` where ``limit`` is ``None`` when the client
    did not ask for pagination (backward-compatible full listing), or an
    ``error_response`` with status 400 for malformed values.
    """
    limit_raw = request.query.get("limit")
    limit = None
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            return error_response(
                "Invalid limit", status=400, code="bad_request"
            )
        if not 1 <= limit <= FILES_MAX_LIMIT:
            return error_response(
                f"limit must be between 1 and {FILES_MAX_LIMIT}",
                status=400, code="bad_request",
            )
    offset_raw = request.query.get("offset", "0")
    try:
        offset = int(offset_raw)
    except (TypeError, ValueError):
        return error_response("Invalid offset", status=400, code="bad_request")
    if offset < 0:
        return error_response("offset must be >= 0", status=400, code="bad_request")
    return limit, offset


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
            return error_response("Forbidden", status=status, code="forbidden")
        rel_path = request.query.get("path", "")
        sort_by = request.query.get("sort", "name")
        order = request.query.get("order", "asc")
        filter_cat = request.query.get("filter", "all")
        search = request.query.get("search", "").lower()
        paging = _parse_paging(request)
        if isinstance(paging, web.Response):
            status = 400
            return paging
        limit, offset = paging

        target = validate_path(lan, rel_path)
        if not target.is_dir():
            status = 404
            return error_response("Not a directory", status=status, code="not_found")

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
            return error_response("Permission denied", status=status, code="forbidden")
        except OSError:
            status = 500
            return error_response("Failed to list directory", status=status, code="internal_error")

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
        # Pagination slices AFTER the service-side sort; totals always describe
        # the full filtered listing. Without limit/offset the response is
        # byte-identical to the pre-pagination contract (no new keys).
        payload = {
            "current_path": listing.current_path,
            "parent_path": listing.parent_path,
            "items": items,
            "total_count": listing.total_count,
            "total_size": total,
            "total_size_fmt": format_size(total),
        }
        if limit is not None or offset > 0:
            payload["total"] = len(items)
            payload["offset"] = offset
            payload["limit"] = limit
            payload["items"] = items[offset:offset + limit] if limit is not None else items[offset:]
        return web.json_response(payload)
    except web.HTTPException as exc:
        status = exc.status
        raise
    except Exception:
        # Non-HTTP failures converge on the shared JSON error contract through
        # the error_contract_middleware; the finally block still records the 500.
        raise
    finally:
        record_route_event(
            lan,
            "lan.files",
            started=started,
            status=status,
            outcome=outcome,
            path=target,
            item_count=item_count,
        )


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
            return error_response("Forbidden", status=status, code="forbidden")
        try:
            payload = await request.json()
        except (ValueError, TypeError):
            status = 400
            return error_response("Invalid JSON body", status=status, code="bad_request")
        parent_path = payload.get("parent_path") if isinstance(payload, dict) else None
        paths = payload.get("paths") if isinstance(payload, dict) else None
        if not isinstance(parent_path, str) or not isinstance(paths, list):
            status = 400
            return error_response(
                "parent_path and 1-48 paths are required", status=status, code="bad_request"
            )

        asset_service = get_asset_service(request)
        try:
            asset_service.validate_directory_summary_paths(paths)
        except ValidationError as exc:
            status = 400
            return error_response(exc.message, status=status, code="bad_request")
        requested_count = len(paths)

        try:
            parent = validate_path(lan, parent_path)
            try:
                parent = asset_service.validate_directory_summary_parent(parent)
            except ValidationError as exc:
                status = 400
                return error_response(exc.message, status=status, code="bad_request")
            directories = [validate_path(lan, path) for path in paths]
        except (web.HTTPException, OSError):
            status = 400
            return error_response("Invalid directory path", status=status, code="bad_request")

        try:
            summaries = await asyncio.to_thread(
                asset_service.summarize_directories, directories, parent=parent
            )
        except ValidationError as exc:
            status = 400
            return error_response(exc.message, status=status, code="bad_request")
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
    except Exception:
        # Non-HTTP failures converge on the shared JSON error contract through
        # the error_contract_middleware; the finally block still records the 500.
        raise
    finally:
        record_route_event(
            lan,
            "lan.directory_summaries",
            started=started,
            status=status,
            outcome=outcome,
            requested_count=requested_count,
            result_count=result_count,
        )
