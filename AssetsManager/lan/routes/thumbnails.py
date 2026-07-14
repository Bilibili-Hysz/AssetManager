"""Thumbnail routes: /api/thumbnails/{path}, /api/thumbnails/batch."""
import asyncio
import base64
from urllib.parse import unquote

from aiohttp import web

from AssetsManager.lan.routes._helpers import get_lan, require_permission, validate_path, get_thumbnail_service


async def handle_thumbnail(request):
    if not require_permission(request, "preview"):
        return web.json_response({"error": "Forbidden"}, status=403)

    lan = get_lan(request)
    rel_path = unquote(request.match_info["path"])
    target = validate_path(lan, rel_path)
    try:
        max_size = min(max(int(request.query.get("size", "512")), 16), 2048)
    except (ValueError, TypeError):
        max_size = 512

    svc = get_thumbnail_service(request)

    def _resolve():
        return svc.resolve(
            target, lan.thumbnail_dir, max_size=max_size,
            blur_tags=lan.blur_tags, db_conn=lan.db_conn,
        )

    result = await asyncio.to_thread(_resolve)

    if not result.found:
        return web.Response(status=404)
    source_path = result.source_path
    if source_path is None:
        return web.Response(status=404)

    if not result.should_blur and max_size >= 256 and not result.cache_hit:
        return web.FileResponse(source_path)

    def _process():
        return svc.process_image(source_path, max_size, result.should_blur)

    processed = await asyncio.to_thread(_process)
    if processed is None:
        return web.FileResponse(source_path)

    body, content_type = processed
    return web.Response(
        body=body, content_type=content_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )


async def handle_thumbnail_batch(request):
    if not require_permission(request, "preview"):
        return web.json_response({"error": "Forbidden"}, status=403)

    lan = get_lan(request)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    paths = body.get("paths", [])
    try:
        max_size = min(max(int(body.get("size", 512)), 16), 2048)
    except (ValueError, TypeError):
        max_size = 512
    if not paths or len(paths) > 100:
        return web.json_response({"error": "Provide 1-100 paths"}, status=400)

    svc = get_thumbnail_service(request)

    def _batch_resolve():
        result = {}
        for rel_path in paths:
            try:
                target = validate_path(lan, rel_path)
                resolved = svc.resolve(
                    target, lan.thumbnail_dir, max_size=max_size,
                    blur_tags=lan.blur_tags, db_conn=lan.db_conn,
                )
                if not resolved.found:
                    continue
                source_path = resolved.source_path
                if source_path is None:
                    continue

                processed = svc.process_image(source_path, max_size, resolved.should_blur)
                if processed is None:
                    continue

                body_bytes, _ = processed
                result[rel_path] = base64.b64encode(body_bytes).decode("ascii")
            except web.HTTPException:
                raise
            except Exception:
                continue
        return result

    result = await asyncio.to_thread(_batch_resolve)
    return web.json_response({"thumbnails": result})
