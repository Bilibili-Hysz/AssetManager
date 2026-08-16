"""Download routes: /api/download/{path}, /api/download/batch."""
import asyncio
import json
import os
from pathlib import Path
from time import perf_counter
from urllib.parse import quote

from aiohttp import web

from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.routes._helpers import build_zip_async, get_lan, require_permission, sanitize_filename, validate_path
from AssetsManager.lan.routes.quota import (
    apply_free_quota_headers,
    apply_free_quota_identity_cookie,
    consume_free_download_quota,
    quota_retry_after_seconds,
)

MAX_BATCH_DOWNLOAD_PATHS = 100
MAX_BATCH_DOWNLOAD_BYTES = 500 * 1024 * 1024  # 500 MB


def _quota_denied_response(
    quota_result: dict, quota_headers: dict[str, str]
) -> web.HTTPTooManyRequests:
    """Build the 429 response for a denied download; the caller owns cleanup."""
    retry_after = quota_retry_after_seconds(quota_result["info"], quota_result)
    if retry_after > 0:
        quota_headers["Retry-After"] = str(retry_after)
    return web.HTTPTooManyRequests(
        text=json.dumps(
            {
                "error": (
                    "Free download quota exhausted"
                    if quota_result["reason"] == "exhausted"
                    else "Please wait before downloading again"
                ),
                "quota": quota_result["info"],
            }
        ),
        content_type="application/json",
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
            try:
                response = web.FileResponse(
                    target,
                    headers={
                        "Content-Disposition": _content_disposition_filename(target.name),
                    },
                )
            except Exception:
                # Existence is guaranteed by validate_path; a construction
                # failure means the file disappeared or is unreadable.
                status = 404
                return error_response("File not found", status=status, code="not_found")

            quota_result = consume_free_download_quota(request)
            quota_headers: dict[str, str] = {}
            apply_free_quota_headers(quota_headers, quota_result["info"])
            if not quota_result["allowed"]:
                # The FileResponse is constructed but never sent, so nothing
                # needs closing before rejecting the download.
                status = 429
                exc = _quota_denied_response(quota_result, quota_headers)
                apply_free_quota_identity_cookie(exc, request)
                raise exc
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

            quota_result = consume_free_download_quota(request)
            quota_headers = {}
            apply_free_quota_headers(quota_headers, quota_result["info"])
            if not quota_result["allowed"]:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                status = 429
                exc = _quota_denied_response(quota_result, quota_headers)
                apply_free_quota_identity_cookie(exc, request)
                raise exc
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
        _record_download_route(lan, started, response_path, outcome, status, kind)


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

        quota_result = consume_free_download_quota(request)
        quota_headers: dict[str, str] = {}
        apply_free_quota_headers(quota_headers, quota_result["info"])
        if not quota_result["allowed"]:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            status = 429
            exc = _quota_denied_response(quota_result, quota_headers)
            apply_free_quota_identity_cookie(exc, request)
            raise exc

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
        _record_batch_download_route(lan, started, outcome, status, target_count)


def _record_download_route(lan, started: float, response_path, outcome: str, status: int, kind: str) -> None:
    services = getattr(lan, "services", None)
    activity_log = getattr(services, "activity_log", None)
    if activity_log is not None and outcome == "response_ready":
        activity_log.add(None, "download", str(response_path or kind), ip="unknown")
    recorder = getattr(lan, "performance_recorder", None)
    if recorder is None or not recorder.enabled:
        return
    try:
        recorder.record(
            "lan.download",
            (perf_counter() - started) * 1000,
            session_token=getattr(lan, "session_token", None),
            path=str(response_path) if response_path is not None else None,
            attributes={
                "outcome": outcome,
                "status": status,
                "phase": "response_ready" if outcome == "response_ready" else "failed",
                "kind": kind,
            },
        )
    except Exception:
        # Diagnostics must not alter response construction or transfer semantics.
        pass


def _record_batch_download_route(lan, started: float, outcome: str, status: int, target_count: int) -> None:
    recorder = getattr(lan, "performance_recorder", None)
    if recorder is None or not recorder.enabled:
        return
    try:
        recorder.record(
            "lan.download_batch",
            (perf_counter() - started) * 1000,
            session_token=getattr(lan, "session_token", None),
            attributes={
                "outcome": outcome,
                "status": status,
                "phase": "response_ready" if outcome == "response_ready" else "failed",
                "target_count": target_count,
            },
        )
    except Exception:
        # Diagnostics must not alter response construction or transfer semantics.
        pass
