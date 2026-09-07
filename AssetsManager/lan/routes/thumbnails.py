"""Thumbnail routes: /api/thumbnails/{path}, /api/thumbnails/batch."""
import asyncio
import base64
import os
from pathlib import Path
from time import perf_counter

from aiohttp import web

from AssetsManager.application.media.analysis import (
    ensure_audio_waveform,
    ensure_extracted_palette,
)
from AssetsManager.application.media.decoders import decoder_for
from AssetsManager.application.thumbnail_service import (
    MAX_THUMBNAIL_BATCH_BYTES,
    ThumbnailAdmissionError,
    ThumbnailSourceChangedError,
    admit_thumbnail_source,
    finalize_pil_image,
    process_image_snapshot,
    validate_thumbnail_source,
)
from AssetsManager.core.constants import AUDIO_EXTS
from AssetsManager.domain.asset import IMAGE_EXTS, VIDEO_EXTS
from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.routes._helpers import (
    MEDIA_CACHE_HEADERS,
    PRIVATE_PREVIEW_HEADERS,
    build_snapshot_media_etag,
    etag_matches,
    get_lan,
    get_services,
    get_thumbnail_service,
    inspect_raster_bytes,
    media_not_modified,
    require_permission,
    validate_path,
)
from AssetsManager.lan.routes._telemetry import record_route_event
from AssetsManager.lan.safe_open import SafeOpenError, read_safe_file

_SAFE_IMAGE_EXTS = IMAGE_EXTS - {".svg"}
_NOSNIFF_HEADERS = {"X-Content-Type-Options": "nosniff"}
MAX_THUMBNAIL_SOURCE_BYTES = 64 * 1024 * 1024


def _thumbnail_target_key(target: Path) -> str:
    """Normalize aliases using the host filesystem's case semantics."""
    return os.path.normcase(str(target.resolve(strict=False)))


def _thumbnail_source_root(lan, source_path: Path) -> Path:
    """Return the only root permitted for a resolved thumbnail source."""
    for root in (Path(lan.library_root), Path(lan.thumbnail_dir)):
        try:
            source_path.relative_to(root)
        except ValueError:
            continue
        return root
    raise ThumbnailSourceChangedError(source_path)


def _derivatives_recorder(request):
    """Library-scoped media-derivative recorder for the on-demand analysis
    passes (N-B2), or ``None`` when the runtime snapshot predates the field
    (legacy fakes) — the passes then run without registering anything."""
    runtime_services = getattr(get_services(request), "runtime_services", None)
    return getattr(runtime_services, "media_derivatives_recorder", None)


def _decoded_thumbnail_factory(encoded: bytes):
    """Lazy PIL decode of already-encoded thumbnail bytes (palette seam).

    The generated WEBP is a downscaled render of the source, so decoding it
    is a small fixed-cost pass and ``extract_palette`` downsizes further to
    <=64px. The factory runs only when the ``extracted_palette`` row is still
    missing, and every failure is swallowed inside the ensure-pass.
    """
    from io import BytesIO

    from PIL import Image

    def _decode():
        with Image.open(BytesIO(encoded)) as image:
            return image.convert("RGB")

    return _decode


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
                allow_legacy_cache=False,
            )

        result = await asyncio.to_thread(_resolve)
        cache_hit = result.cache_hit
        if not result.found or result.source_path is None:
            status = 404
            return web.Response(status=status)
        source_path = result.source_path
        is_audio = source_path.suffix.lower() in AUDIO_EXTS

        if source_path.suffix.lower() not in _SAFE_IMAGE_EXTS and not is_audio:
            # Professional formats (RAW/PSD) are not Pillow-readable but are
            # safe raster sources when the media decoder registry routes the
            # extension; without the optional extras this stays a plain 404.
            if decoder_for(source_path.suffix) is None:
                status = 404
                return web.Response(status=status)
        media_decoder = (
            None
            if source_path.suffix.lower() in _SAFE_IMAGE_EXTS or is_audio
            else decoder_for(source_path.suffix)
        )

        # The resolved source can be an original, a WebP cache artifact, or a
        # video frame. Validate and final-open that selected source before any
        # conditional response, rather than using the request target's stat.
        validate_thumbnail_source(source_path, result.source_identity)
        source_root = _thumbnail_source_root(lan, source_path)

        # RAW/PSD originals are not browser-renderable rasters, so the
        # original-bytes delivery path is decoder-formats-only excluded: the
        # processed WEBP branch below is the only delivery. Audio gets the
        # same treatment — the original bytes are not an image at all.
        try:
            source_body, source_identity = await asyncio.to_thread(
                read_safe_file,
                source_root,
                source_path,
                max_bytes=MAX_THUMBNAIL_SOURCE_BYTES,
                expected_identity=result.source_identity,
            )
        except (SafeOpenError, OSError, ValueError):
            raise ThumbnailSourceChangedError(source_path) from None

        # A normal large raster keeps the historical original-byte response,
        # but its claimed suffix is never enough to authorize browser delivery.
        # Recheck policy after the final-open snapshot so a tag tightened while
        # resolving cannot turn an unblurred response into a 304 or raw leak.
        raw_candidate = (
            not result.should_blur and max_size >= 256 and not result.cache_hit
            and media_decoder is None and not is_audio
        )
        policy_check = getattr(svc, "check_blur", None)
        raw_content_type = (
            await asyncio.to_thread(inspect_raster_bytes, source_body)
            if raw_candidate
            else None
        )

        recorder = _derivatives_recorder(request)

        def _process(should_blur: bool):
            if is_audio:
                # On-demand waveform (N-B2): generate-at-most-once with the
                # asset_derivatives row as the marker, register the PNG
                # payload and deliver it as image/png (blur is a no-op — a
                # waveform carries no source content).
                waveform = ensure_audio_waveform(
                    recorder,
                    source_path,
                    source_body=source_body,
                    source_suffix=source_path.suffix,
                )
                if waveform is None:
                    return None
                return waveform, "image/png"
            if media_decoder is not None:
                # Content gate for decoder formats: the successful decode IS
                # the validation (fail closed like the Pillow verify gate);
                # encoding reuses the shared WEBP pipeline tail.
                pil = media_decoder.decode_bytes(source_body, max_dim=max_size)
                if pil is None:
                    return None
                # Palette pass from the decoded source pixels (params-only
                # row; the row-exists check inside makes repeats free).
                ensure_extracted_palette(recorder, source_path, pil)
                return finalize_pil_image(pil, max_size, should_blur)
            processed = process_image_snapshot(
                svc,
                source_path,
                source_body,
                max_size,
                should_blur,
                result.source_identity,
            )
            if processed is not None and not should_blur:
                # Palette pass from the generated (downscaled) thumbnail; a
                # blurred render would only describe the blur, not the asset.
                ensure_extracted_palette(
                    recorder,
                    source_path,
                    _decoded_thumbnail_factory(processed[0]),
                )
            return processed

        async def _emit(body: bytes, content_type: str, kind: str, *, blurred: bool):
            """Emit one selected representation after its final policy check."""
            nonlocal delivery, outcome, status
            if blurred:
                delivery = kind
                status = 200
                outcome = "success"
                return web.Response(
                    body=body,
                    content_type=content_type,
                    headers=PRIVATE_PREVIEW_HEADERS,
                )
            etag = await asyncio.to_thread(
                build_snapshot_media_etag,
                "thumb", source_identity, body, content_type,
                query=dict(request.query),
            )
            final_should_blur = bool(
                await asyncio.to_thread(
                    policy_check, target, lan.blur_tags, None, lan.library_root,
                )
                if callable(policy_check)
                else result.should_blur
            )
            if final_should_blur:
                processed = await asyncio.to_thread(_process, True)
                if processed is None:
                    status = 500
                    return error_response(
                        "Failed to process image",
                        status=status,
                        code="internal_error",
                        headers=_NOSNIFF_HEADERS,
                    )
                rendered_body, rendered_type = processed
                delivery = "processed"
                status = 200
                outcome = "success"
                return web.Response(
                    body=rendered_body,
                    content_type=rendered_type,
                    headers=PRIVATE_PREVIEW_HEADERS,
                )
            if etag_matches(request, etag):
                status = 304
                outcome = "not_modified"
                return media_not_modified(etag)
            delivery = kind
            status = 200
            outcome = "success"
            return web.Response(
                body=body,
                content_type=content_type,
                headers={**MEDIA_CACHE_HEADERS, "ETag": etag},
            )

        # Keep the old original-byte fast path, but only after verifying its
        # captured bytes. The policy check below is deliberately after that
        # verification, immediately before this raw response can be emitted.
        if raw_candidate and raw_content_type is not None:
            return await _emit(
                source_body, raw_content_type, "original", blurred=False,
            )

        effective_should_blur = result.should_blur
        processed = await asyncio.to_thread(_process, effective_should_blur)
        final_should_blur = bool(
            await asyncio.to_thread(
                policy_check, target, lan.blur_tags, None, lan.library_root,
            )
            if callable(policy_check)
            else result.should_blur
        )
        if final_should_blur and not effective_should_blur:
            effective_should_blur = True
            processed = await asyncio.to_thread(_process, True)
        if processed is None:
            if is_audio:
                status = 404
                return web.Response(status=status)
            if media_decoder is not None:
                # Never fall back to serving the RAW/PSD original bytes (a
                # browser cannot render them; for blurred assets serving the
                # original would leak content). Blur keeps the 500 semantics
                # of serve_blur_gated_raster; non-blur fails closed with 404.
                if effective_should_blur:
                    status = 500
                    return error_response(
                        "Failed to process image",
                        status=status,
                        code="internal_error",
                        headers=_NOSNIFF_HEADERS,
                    )
                status = 404
                return web.Response(status=status)
            if effective_should_blur:
                status = 500
                return error_response(
                    "Failed to process image",
                    status=status,
                    code="internal_error",
                    headers=_NOSNIFF_HEADERS,
                )
            content_type = raw_content_type or await asyncio.to_thread(
                inspect_raster_bytes, source_body,
            )
            if content_type is None:
                status = 404
                return web.Response(status=status)
            return await _emit(source_body, content_type, "original", blurred=False)

        body, content_type = processed
        return await _emit(
            body, content_type, "processed", blurred=effective_should_blur,
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
        record_route_event(
            lan,
            "lan.thumbnail",
            started=started,
            status=status,
            outcome=outcome,
            path=target,
            delivery=delivery,
            cache_hit=cache_hit,
        )


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
                if not target.is_file() or (
                    target.suffix.lower() not in IMAGE_EXTS | VIDEO_EXTS
                    and decoder_for(target.suffix) is None
                ):
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
            pending = []

            def render(source_path, source_body, resolved, should_blur):
                batch_decoder = decoder_for(source_path.suffix)
                if batch_decoder is not None:
                    # Same content-gate/encode tail as the single route.
                    pil = batch_decoder.decode_bytes(source_body, max_dim=max_size)
                    return (
                        finalize_pil_image(pil, max_size, should_blur)
                        if pil is not None
                        else None
                    )
                return process_image_snapshot(
                    svc,
                    source_path,
                    source_body,
                    max_size,
                    should_blur,
                    resolved.source_identity,
                )

            for aliases, target in unique_paths:
                try:
                    resolved = svc.resolve(
                        target, lan.thumbnail_dir, max_size=max_size,
                        blur_tags=lan.blur_tags, library_root=lan.library_root,
                        allow_legacy_cache=False,
                    )
                    if not resolved.found:
                        continue
                    source_path = resolved.source_path
                    if source_path is None:
                        continue
                    validate_thumbnail_source(source_path, resolved.source_identity)
                    source_body, _source_identity = read_safe_file(
                        _thumbnail_source_root(lan, source_path),
                        source_path,
                        max_bytes=MAX_THUMBNAIL_SOURCE_BYTES,
                        expected_identity=resolved.source_identity,
                    )
                    processed = render(
                        source_path, source_body, resolved, resolved.should_blur,
                    )
                    if processed is None:
                        continue
                    body_bytes, _ = processed
                    pending.append(
                        (
                            aliases,
                            target,
                            resolved.should_blur,
                            base64.b64encode(body_bytes).decode("ascii"),
                        )
                    )
                except (ThumbnailAdmissionError, ThumbnailSourceChangedError):
                    failed += 1
                except web.HTTPException:
                    raise
                except Exception:
                    failed += 1

            # Every response is checked only after the complete worker pass:
            # an entry rendered early cannot escape an intervening blur-policy
            # tightening while the rest of the batch is processed.
            for aliases, target, initially_blurred, encoded in pending:
                try:
                    policy_check = getattr(svc, "check_blur", None)
                    final_should_blur = bool(
                        policy_check(target, lan.blur_tags, None, lan.library_root)
                        if callable(policy_check)
                        else initially_blurred
                    )
                    if final_should_blur and not initially_blurred:
                        failed += 1
                        continue
                    result.update({alias: encoded for alias in aliases})
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
        record_route_event(
            lan,
            "lan.thumbnail_batch",
            started=started,
            status=status,
            outcome=outcome,
            requested_count=requested_count,
            result_count=result_count,
            failed_count=failed_count,
        )
