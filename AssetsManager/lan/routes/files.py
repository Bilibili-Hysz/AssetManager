"""File listing route: /api/files."""
import asyncio
import os
from urllib.parse import quote

from aiohttp import web

from AssetsManager.application import DirectoryListOptions
from AssetsManager.core.format_utils import format_size
from AssetsManager.lan.routes._helpers import batch_cached_stats, get_lan, get_asset_service, require_permission, validate_path


async def handle_files(request):
    if not require_permission(request, "browse"):
        return web.json_response({"error": "Forbidden"}, status=403)

    lan = get_lan(request)
    rel_path = request.query.get("path", "")
    sort_by = request.query.get("sort", "name")
    order = request.query.get("order", "asc")
    filter_cat = request.query.get("filter", "all")
    search = request.query.get("search", "").lower()

    target = validate_path(lan, rel_path)
    if not target.is_dir():
        return web.json_response({"error": "Not a directory"}, status=404)

    settings = lan.current_settings
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
            ),
        )

    try:
        listing = await asyncio.to_thread(_list)
    except PermissionError:
        return web.json_response({"error": "Permission denied"}, status=403)
    except OSError:
        return web.json_response({"error": "Failed to list directory"}, status=500)

    file_paths = [str(item.absolute_path) for item in listing.items if not item.is_dir]
    cached_stats = batch_cached_stats(str(lan.library_root), file_paths, lan.connection_for)

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
                "thumbnail_url": thumb_url,
            })

    total = sum(i["size"] for i in items)
    return web.json_response({
        "current_path": listing.current_path,
        "parent_path": listing.parent_path,
        "items": items,
        "total_count": listing.total_count,
        "total_size": total,
        "total_size_fmt": format_size(total),
    })
