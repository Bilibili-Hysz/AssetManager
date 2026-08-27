"""Thumbnail routes: /api/thumbnails/{path}, /api/thumbnails/batch."""
import asyncio
import base64
import mimetypes
import os
from pathlib import Path
from time import perf_counter

from aiohttp import web

from AssetsManager.application.thumbnail_service import (
    MAX_THUMBNAIL_BATCH_BYTES,
    ThumbnailAdmissionError,
    ThumbnailSourceChangedError,
    admit_thumbnail_source,
    process_image_snapshot,
    validate_thumbnail_source,
)
from AssetsManager.domain.asset import IMAGE_EXTS, VIDEO_EXTS
from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.routes._helpers import (
    PRIVATE_PREVIEW_HEADERS,
    PUBLIC_PREVIEW_HEADERS,
    get_lan,
    get_thumbnail_service,
    require_permission,
    validate_path,
)
from AssetsManager.lan.safe_open import SafeOpenError, read_safe_file

_SAFE_IMAGE_EXTS = IMAGE_EXTS - {".svg"}
_NOSNIFF_HEADERS = {"X-Content-Type-Options": "nosniff"}


def _thumbnail_target_key(target: Path) -> str:
    """Normalize aliases using the host filesystem's case semantics."""
    return os.path.normcase(str(target.resolve(strict=False)))


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
            return error_response("Forbidden", status=status, code="forbidden")

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

        # Re-check immediately before either FileResponse or processing. This
        # narrows the admission/consumption gap but cannot make a path open
        # atomic against replacement between this check and the consumer.
        validate_thumbnail_source(source_path, result.source_identity)

        if not result.should_blur and max_size >= 256 and not result.cache_hit:
            outcome = "success"
            status = 200
            delivery = "original"
            try:
                body, _identity = await asyncio.to_thread(
                    read_safe_file, lan.library_root, source_path,
                    expected_identity=result.source_identity,
                )
            except (SafeOpenError, OSError, ValueError):
                raise ThumbnailSourceChangedError(source_path) from None
            return web.Response(
                body=body,
                content_type=mimetypes.guess_type(source_path.name)[0] or "application/octet-stream",
                headers=_NOSNIFF_HEADERS,
            )

        source_root = lan.library_root
        try:
            source_path.relative_to(source_root)
        except ValueError:
            source_root = source_path.parent
        try:
            source_body, _source_identity = await asyncio.to_thread(
                read_safe_file,
                source_root,
                source_path,
                expected_identity=result.source_identity,
            )
        except (SafeOpenError, OSError, ValueError):
            raise ThumbnailSourceChangedError(source_path) from None

        def _process():
            return process_image_snapshot(
                svc,
                source_path,
                source_body,
                max_size,
                result.should_blur,
                result.source_identity,
            )

        processed = await asyncio.to_thread(_process)
        outcome = "success"
        status = 200
        if processed is None:
            if result.should_blur:
                outcome = "error"
                status = 500
                return error_response(
                    "Failed to process image",
                    status=status,
                    code="internal_error",
                    headers=_NOSNIFF_HEADERS,
                )
            delivery = "original"
            return web.Response(
                body=source_body,
                content_type=mimetypes.guess_type(source_path.name)[0] or "application/octet-stream",
                headers=_NOSNIFF_HEADERS,
            )

        body, content_type = processed
        delivery = "processed"
        return web.Response(
            body=body,
            content_type=content_type,
            headers=(
                PRIVATE_PREVIEW_HEADERS
                if result.should_blur
                else PUBLIC_PREVIEW_HEADERS
            ),
        )
    except ThumbnailAdmissionError as exc:
        status = 413
        return error_response(
            "Thumbnail source exceeds size limit",
            status=status,
            code="payload_too_large",
            extra={"source_bytes": exc.size, "limit_bytes": exc.limit},
        )
    except ThumbnailSourceChangedError:
        status = 409
        return error_response(
            "Thumbnail source changed during request",
            status=status,
            code="source_changed",
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
            return error_response("Forbidden", status=status, code="forbidden")
        try:
            body = await request.json()
        except Exception:
            status = 400
            return error_response("Invalid JSON", status=status, code="bad_request")

        paths = body.get("paths", [])
        try:
            max_size = min(max(int(body.get("size", 512)), 16), 2048)
        except (ValueError, TypeError):
            max_size = 512
        if not paths or len(paths) > 100:
            status = 400
            return error_response("Provide 1-100 paths", status=status, code="bad_request")
        requested_count = len(paths)

        # Validate and budget unique sources before entering the worker. This
        # prevents duplicate paths from multiplying decode work and ensures a
        # batch cannot admit more source bytes than its fixed budget.
        unique_paths: list[tuple[list[str], Path]] = []
        seen_targets: dict[str, list[str]] = {}
        total_bytes = 0
        try:
            for rel_path in paths:
                if not isinstance(rel_path, str):
                    continue
                target = validate_path(lan, rel_path)
                target_key = _thumbnail_target_key(target)
                aliases = seen_targets.get(target_key)
                if aliases is not None:
                    aliases.append(rel_path)
                    continue
                if target.suffix.lower() not in IMAGE_EXTS | VIDEO_EXTS or not target.is_file():
                    continue
                source_bytes = admit_thumbnail_source(target)
                if source_bytes is None:
                    continue
                total_bytes += source_bytes
                if total_bytes > MAX_THUMBNAIL_BATCH_BYTES:
                    status = 413
                    return error_response(
                        "Thumbnail batch exceeds size limit",
                        status=status,
                        code="payload_too_large",
                        extra={
                            "total_bytes": total_bytes,
                            "limit_bytes": MAX_THUMBNAIL_BATCH_BYTES,
                        },
                    )
                aliases = [rel_path]
                seen_targets[target_key] = aliases
                unique_paths.append((aliases, target))
        except ThumbnailAdmissionError as exc:
            status = 413
            return error_response(
                "Thumbnail source exceeds size limit",
                status=status,
                code="payload_too_large",
                extra={"source_bytes": exc.size, "limit_bytes": exc.limit},
            )

        svc = get_thumbnail_service(request)

        def _batch_resolve():
            result = {}
            failed = 0
            for aliases, target in unique_paths:
                try:
                    resolved = svc.resolve(
                        target, lan.thumbnail_dir, max_size=max_size,
                        blur_tags=lan.blur_tags, library_root=lan.library_root,
                    )
                    if not resolved.found:
                        continue
                    source_path = resolved.source_path
                    if source_path is None:
                        continue
                    validate_thumbnail_source(source_path, resolved.source_identity)
                    source_root = lan.library_root
                    try:
                        source_path.relative_to(source_root)
                    except ValueError:
                        source_root = source_path.parent
                    source_body, _source_identity = read_safe_file(
                        source_root,
                        source_path,
                        expected_identity=resolved.source_identity,
                    )
                    processed = process_image_snapshot(
                        svc,
                        source_path,
                        source_body,
                        max_size,
                        resolved.should_blur,
                        resolved.source_identity,
                    )
                    if processed is None:
                        continue

                    body_bytes, _ = processed
                    encoded = base64.b64encode(body_bytes).decode("ascii")
                    result.update({alias: encoded for alias in aliases})
                except (ThumbnailAdmissionError, ThumbnailSourceChangedError):
                    failed += 1
                except web.HTTPException:
                    raise
                except Exception:
                    failed += 1
            return result, failed

        result, failed_count = await asyncio.to_thread(_batch_resolve)
        result_count = len(result)
        outcome = "partial" if failed_count else "success"
        status = 200
        return web.json_response(
            {"thumbnails": result},
            headers={"Cache-Control": "private, no-store"},
        )
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
