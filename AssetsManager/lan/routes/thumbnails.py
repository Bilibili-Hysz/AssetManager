"""Thumbnail routes: /api/thumbnails/{path}, /api/thumbnails/batch."""
import asyncio
import base64
from time import perf_counter

from aiohttp import web

from AssetsManager.domain.asset import IMAGE_EXTS
from AssetsManager.lan.routes._helpers import get_lan, require_permission, validate_path, get_thumbnail_service

_SAFE_IMAGE_EXTS = IMAGE_EXTS - {".svg"}
_NOSNIFF_HEADERS = {"X-Content-Type-Options": "nosniff"}


async def handle_thumbnail(request):
    lan = get_lan(request)
    started = perf_counter()
    target = None
    outcome = "error"
    status = 500
    delivery = "none"
    cache_hit = False
    try:
        if not require_permission(request, "preview"):
            status = 403
            return web.json_response({"error": "Forbidden"}, status=status)

        rel_path = request.match_info["path"]  # aiohttp decodes match_info once
        target = validate_path(lan, rel_path)
        try:
            max_size = min(max(int(request.query.get("size", "512")), 16), 2048)
        except (ValueError, TypeError):
            max_size = 512

        svc = get_thumbnail_service(request)

        def _resolve():
            return svc.resolve(
                target, lan.thumbnail_dir, max_size=max_size,
                blur_tags=lan.blur_tags, library_root=lan.library_root,
            )

        result = await asyncio.to_thread(_resolve)
        cache_hit = result.cache_hit
        if not result.found or result.source_path is None:
            status = 404
            return web.Response(status=status)
        source_path = result.source_path

        if source_path.suffix.lower() not in _SAFE_IMAGE_EXTS:
            status = 404
            return web.Response(status=status)

        if not result.should_blur and max_size >= 256 and not result.cache_hit:
            outcome = "success"
            status = 200
            delivery = "original"
            return web.FileResponse(source_path, headers=_NOSNIFF_HEADERS)

        def _process():
            return svc.process_image(source_path, max_size, result.should_blur)

        processed = await asyncio.to_thread(_process)
        outcome = "success"
        status = 200
        if processed is None:
            if result.should_blur:
                outcome = "error"
                status = 500
                return web.json_response(
                    {"error": "Failed to process image"},
                    status=status,
                    headers=_NOSNIFF_HEADERS,
                )
            delivery = "original"
            return web.FileResponse(source_path, headers=_NOSNIFF_HEADERS)

        body, content_type = processed
        delivery = "processed"
        return web.Response(
            body=body, content_type=content_type,
            headers={
                "Cache-Control": "public, max-age=3600",
                "X-Content-Type-Options": "nosniff",
            },
        )
    except web.HTTPException as exc:
        status = exc.status
        raise
    finally:
        _record_thumbnail_route(lan, started, target, outcome, status, delivery, cache_hit)


def _record_thumbnail_route(lan, started, target, outcome, status, delivery, cache_hit) -> None:
    recorder = getattr(lan, "performance_recorder", None)
    if recorder is None or not recorder.enabled:
        return
    try:
        recorder.record(
            "lan.thumbnail",
            (perf_counter() - started) * 1000,
            session_token=getattr(lan, "session_token", None),
            path=str(target) if target is not None else None,
            attributes={
                "outcome": outcome,
                "status": status,
                "delivery": delivery,
                "cache_hit": cache_hit,
            },
        )
    except Exception:
        # Diagnostics must not affect preview delivery or security outcomes.
        pass


async def handle_thumbnail_batch(request):
    lan = get_lan(request)
    started = perf_counter()
    outcome = "error"
    status = 500
    requested_count = 0
    result_count = 0
    failed_count = 0
    try:
        if not require_permission(request, "preview"):
            status = 403
            return web.json_response({"error": "Forbidden"}, status=status)
        try:
            body = await request.json()
        except Exception:
            status = 400
            return web.json_response({"error": "Invalid JSON"}, status=status)

        paths = body.get("paths", [])
        try:
            max_size = min(max(int(body.get("size", 512)), 16), 2048)
        except (ValueError, TypeError):
            max_size = 512
        if not paths or len(paths) > 100:
            status = 400
            return web.json_response({"error": "Provide 1-100 paths"}, status=status)
        requested_count = len(paths)

        svc = get_thumbnail_service(request)

        def _batch_resolve():
            result = {}
            failed = 0
            for rel_path in paths:
                try:
                    target = validate_path(lan, rel_path)
                    resolved = svc.resolve(
                        target, lan.thumbnail_dir, max_size=max_size,
                        blur_tags=lan.blur_tags, library_root=lan.library_root,
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
                    failed += 1
            return result, failed

        result, failed_count = await asyncio.to_thread(_batch_resolve)
        result_count = len(result)
        outcome = "partial" if failed_count else "success"
        status = 200
        return web.json_response({"thumbnails": result})
    except web.HTTPException as exc:
        status = exc.status
        raise
    finally:
        _record_thumbnail_batch_route(
            lan, started, outcome, status, requested_count, result_count, failed_count
        )


def _record_thumbnail_batch_route(
    lan, started: float, outcome: str, status: int, requested_count: int, result_count: int, failed_count: int
) -> None:
    recorder = getattr(lan, "performance_recorder", None)
    if recorder is None or not recorder.enabled:
        return
    try:
        recorder.record(
            "lan.thumbnail_batch",
            (perf_counter() - started) * 1000,
            session_token=getattr(lan, "session_token", None),
            attributes={
                "outcome": outcome,
                "status": status,
                "requested_count": requested_count,
                "result_count": result_count,
                "failed_count": failed_count,
            },
        )
    except Exception:
        # Diagnostics must not affect preview delivery or security outcomes.
        pass
