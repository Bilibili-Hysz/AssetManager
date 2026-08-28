"""Download routes: /api/download/{path}, /api/download/batch."""
import asyncio
import os
from pathlib import Path
from time import perf_counter
from urllib.parse import quote

from aiohttp import web

from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.routes._helpers import build_zip_async, get_lan, require_permission, sanitize_filename, validate_path
from AssetsManager.lan.routes._telemetry import record_route_event
from AssetsManager.lan.safe_open import SafeOpenError, read_safe_file
from AssetsManager.lan.routes.quota import (
    apply_free_quota_headers,
    apply_free_quota_identity_cookie,
    consume_free_download_quota,
    get_free_download_quota_info,
    quota_retry_after_seconds,
    QuotaUnavailableError,
)

MAX_BATCH_DOWNLOAD_PATHS = 100
MAX_BATCH_DOWNLOAD_BYTES = 500 * 1024 * 1024  # 500 MB


def _preflight_exhausted_response(request) -> web.Response | None:
    """Fast-deny an already-exhausted identity before expensive preparation.

    Read-only preflight: any store failure, a disabled quota, or a non-zero
    remaining budget returns ``None`` and the request follows the legacy
    flow (whose authoritative consume stays the single source of truth).
    Only the exact exhausted case is short-circuited so batch/directory
    downloads stop paying for size estimation plus ZIP creation they could
    never receive; interval rate-limiting is deliberately not predicted.
    """
    try:
        info = get_free_download_quota_info(request)
    except Exception:
        return None
    if not info.get("enabled") or info.get("remaining") != 0:
        return None
    result = {"allowed": False, "reason": "exhausted", "retry_after_seconds": 0, "info": info}
    headers: dict[str, str] = {}
    apply_free_quota_headers(headers, info)
    response = _quota_denied_response(result, headers)
    apply_free_quota_identity_cookie(response, request)
    return response


def _quota_unavailable_response() -> web.Response:
    return error_response(
        "Quota unavailable",
        status=503,
        code="service_unavailable",
    )


def _quota_denied_response(
    quota_result: dict, quota_headers: dict[str, str]
) -> web.Response:
    """Build the canonical 429 response for a denied download."""
    retry_after = quota_retry_after_seconds(quota_result["info"], quota_result)
    if retry_after > 0:
        quota_headers["Retry-After"] = str(retry_after)
    return error_response(
        (
            "Free download quota exhausted"
            if quota_result["reason"] == "exhausted"
            else "Please wait before downloading again"
        ),
        status=429,
        code="download_quota_exhausted" if quota_result["reason"] == "exhausted" else "download_rate_limited",
        details={"quota": quota_result["info"], "retry_after": retry_after},
        extra={"quota": quota_result["info"]},
        headers=quota_headers,
    )


def _content_disposition_filename(name: str) -> str:
    clean = sanitize_filename(name)
    ascii_name = clean.encode("ascii", "ignore").decode("ascii") or "download"
    header = f'attachment; filename="{ascii_name}"'
    if clean != ascii_name:
        header += f"; filename*=UTF-8''{quote(clean, safe='')}"
    return header


def _file_response_with_cleanup(
    request,
    path: str,
    *,
    filename: str,
    write_eof=None,
    extra_headers: dict[str, str] | None = None,
) -> web.FileResponse:
    headers = {"Content-Disposition": _content_disposition_filename(filename)}
    if extra_headers:
        headers.update(extra_headers)
    response = web.FileResponse(
        path,
        headers=headers,
    )
    original_write_eof = write_eof or response.write_eof

    def _cleanup() -> None:
        try:
            os.unlink(path)
        except OSError:
            pass

    async def _write_eof_and_cleanup(data: bytes = b""):
        try:
            return await original_write_eof(data)
        finally:
            _cleanup()

    response.write_eof = _write_eof_and_cleanup
    # Client aborts and prepare() failures never reach write_eof, which
    # would leave the temporary ZIP behind forever; the request task's
    # completion is the final cleanup point (idempotent with the normal
    # write_eof path).
    task = getattr(request, "task", None)
    if task is not None:
        task.add_done_callback(lambda _finished: _cleanup())
    return response


def _estimate_download_size(target: Path) -> int:
    if target.is_file():
        return target.stat().st_size
    if target.is_dir():
        total = 0
        for dirpath, dirnames, filenames in os.walk(target):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fname in filenames:
                if fname.startswith("."):
                    continue
                try:
                    total += (Path(dirpath) / fname).stat().st_size
                except OSError:
                    pass
        return total
    return 0


def _estimate_batch_download_size(targets: list[tuple[str, Path]]) -> int:
    total_bytes = 0
    for _, target in targets:
        try:
            total_bytes += _estimate_download_size(target)
        except OSError:
            pass
    return total_bytes


async def handle_download(request):
    lan = get_lan(request)
    started = perf_counter()
    status = 500
    outcome = "error"
    kind = "none"
    response_path = None
    try:
        if not require_permission(request, "download"):
            status = 403
            return error_response("Forbidden", status=status, code="forbidden")

        rel_path = request.match_info["path"]  # aiohttp decodes match_info once
        target = validate_path(lan, rel_path)

        if target.is_file():
            # Read-only preflight runs before the full in-memory read: an
            # exhausted identity must not pay for a complete file read it can
            # never receive (batch/directory downloads already gate first).
            preflight = _preflight_exhausted_response(request)
            if preflight is not None:
                status = 429
                return preflight

            try:
                body, _identity = await asyncio.to_thread(
                    read_safe_file, getattr(lan, "library_root", target.parent), target,
                )
            except (SafeOpenError, OSError, ValueError):
                status = 404
                return error_response("File not found", status=status, code="not_found")

            response = web.Response(
                body=body,
                headers={
                    "Content-Disposition": _content_disposition_filename(target.name),
                },
            )
            try:
                quota_result = await asyncio.to_thread(consume_free_download_quota, request)
            except QuotaUnavailableError:
                status = 503
                return _quota_unavailable_response()
            quota_headers: dict[str, str] = {}
            apply_free_quota_headers(quota_headers, quota_result["info"])
            if not quota_result["allowed"]:
                # The FileResponse is constructed but never sent, so nothing
                # needs closing before rejecting the download.
                status = 429
                response = _quota_denied_response(quota_result, quota_headers)
                apply_free_quota_identity_cookie(response, request)
                return response
            apply_free_quota_identity_cookie(response, request)
            status = 200
            outcome = "response_ready"
            kind = "file"
            response_path = target
            return response

        if target.is_dir():
            try:
                total_bytes = await asyncio.to_thread(_estimate_download_size, target)
            except OSError:
                total_bytes = 0
            if total_bytes > MAX_BATCH_DOWNLOAD_BYTES:
                status = 413
                return error_response(
                    f"Total size exceeds limit ({MAX_BATCH_DOWNLOAD_BYTES // (1024*1024)} MB)",
                    status=status,
                    code="payload_too_large",
                    extra={"total_bytes": total_bytes, "limit_bytes": MAX_BATCH_DOWNLOAD_BYTES},
                )

            preflight = _preflight_exhausted_response(request)
            if preflight is not None:
                status = 429
                return preflight

            import tempfile
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".zip")
            os.close(tmp_fd)
            result = await build_zip_async(request, [(target, None)], tmp_path)
            if result is None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                return error_response("Failed to create ZIP", status=status, code="internal_error")

            try:
                quota_result = await asyncio.to_thread(consume_free_download_quota, request)
            except QuotaUnavailableError:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                status = 503
                return _quota_unavailable_response()
            quota_headers = {}
            apply_free_quota_headers(quota_headers, quota_result["info"])
            if not quota_result["allowed"]:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                status = 429
                response = _quota_denied_response(quota_result, quota_headers)
                apply_free_quota_identity_cookie(response, request)
                return response
            status = 200
            outcome = "response_ready"
            kind = "directory_zip"
            response_path = target
            zip_name = f"{target.name}.zip"
            response = _file_response_with_cleanup(request, tmp_path, filename=zip_name, extra_headers=quota_headers)
            apply_free_quota_identity_cookie(response, request)
            return response

        status = 404
        return error_response("File not found", status=status, code="not_found")
    except web.HTTPException as exc:
        status = exc.status
        raise
    finally:
        # Successful downloads land in the activity log off the event loop;
        # ordering and swallow-on-error semantics live inside ActivityLog.add.
        services = getattr(lan, "services", None)
        activity_log = getattr(services, "activity_log", None)
        if activity_log is not None and outcome == "response_ready":
            await asyncio.to_thread(
                activity_log.add,
                None,
                "download",
                str(response_path or kind),
                ip="unknown",
            )
        record_route_event(
            lan,
            "lan.download",
            started=started,
            status=status,
            outcome=outcome,
            path=response_path,
            kind=kind,
            phase="response_ready" if outcome == "response_ready" else "failed",
        )


async def handle_batch_download(request):
    lan = get_lan(request)
    started = perf_counter()
    status = 500
    outcome = "error"
    target_count = 0
    try:
        if not require_permission(request, "download"):
            status = 403
            return error_response("Forbidden", status=status, code="forbidden")
        try:
            body = await request.json()
        except Exception:
            status = 400
            return error_response("Invalid request body", status=status, code="bad_request")

        paths = body.get("paths", [])
        if not paths:
            status = 400
            return error_response("No paths provided", status=status, code="bad_request")
        if not isinstance(paths, list):
            status = 400
            return error_response("Invalid paths format", status=status, code="bad_request")
        if len(paths) > MAX_BATCH_DOWNLOAD_PATHS:
            status = 400
            return error_response(
                f"Too many paths (max {MAX_BATCH_DOWNLOAD_PATHS})", status=status, code="bad_request"
            )

        targets = []
        for rel_path in paths:
            if not isinstance(rel_path, str):
                continue
            try:
                target = validate_path(lan, rel_path)
                if target.exists():
                    targets.append((rel_path, target))
            except web.HTTPException:
                raise
            except Exception:
                continue

        if not targets:
            status = 400
            return error_response("No valid paths", status=status, code="bad_request")
        target_count = len(targets)

        # Enforce total-size limit
        if any(target.is_dir() for _, target in targets):
            total_bytes = await asyncio.to_thread(_estimate_batch_download_size, targets)
        else:
            total_bytes = _estimate_batch_download_size(targets)
        if total_bytes > MAX_BATCH_DOWNLOAD_BYTES:
            status = 413
            return error_response(
                f"Total size exceeds limit ({MAX_BATCH_DOWNLOAD_BYTES // (1024*1024)} MB)",
                status=status,
                code="payload_too_large",
                extra={"total_bytes": total_bytes, "limit_bytes": MAX_BATCH_DOWNLOAD_BYTES},
            )

        preflight = _preflight_exhausted_response(request)
        if preflight is not None:
            status = 429
            return preflight

        import tempfile
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".zip")
        os.close(tmp_fd)
        result = await build_zip_async(request, [(target, None) for _, target in targets], tmp_path)
        if result is None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            return error_response("Failed to create ZIP", status=status, code="internal_error")

        try:
            quota_result = await asyncio.to_thread(consume_free_download_quota, request)
        except QuotaUnavailableError:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            status = 503
            return _quota_unavailable_response()
        quota_headers: dict[str, str] = {}
        apply_free_quota_headers(quota_headers, quota_result["info"])
        if not quota_result["allowed"]:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            status = 429
            response = _quota_denied_response(quota_result, quota_headers)
            apply_free_quota_identity_cookie(response, request)
            return response

        if len(targets) == 1:
            zip_name = f"{targets[0][1].name}.zip"
        else:
            zip_name = f"download_{len(targets)}_items.zip"
        status = 200
        outcome = "response_ready"
        response = _file_response_with_cleanup(request, tmp_path, filename=zip_name, extra_headers=quota_headers)
        apply_free_quota_identity_cookie(response, request)
        return response
    except web.HTTPException as exc:
        status = exc.status
        raise
    finally:
        record_route_event(
            lan,
            "lan.download_batch",
            started=started,
            status=status,
            outcome=outcome,
            target_count=target_count,
            phase="response_ready" if outcome == "response_ready" else "failed",
        )
