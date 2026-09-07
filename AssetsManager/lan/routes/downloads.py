"""Download routes: /api/download/{path}, /api/download/batch."""
import asyncio
import concurrent.futures
import os
from collections.abc import Callable
from pathlib import Path
from time import perf_counter
from urllib.parse import quote

from aiohttp import web

from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.routes._helpers import MAX_ZIP_SOURCE_BYTES, ZIP_EXECUTOR_APP_KEY, build_zip_async, get_lan, require_permission, sanitize_filename, validate_path
from AssetsManager.lan.routes._telemetry import record_route_event
from AssetsManager.lan.safe_open import SafeOpenError
from AssetsManager.lan.file_response import SafeFileResponse, open_download_file
from AssetsManager.lan.temporary_file_response import TemporaryFileResponse
from AssetsManager.lan.zip_resources import ZIP_BUDGET_APP_KEY, ZipReservation, get_process_zip_budget
from AssetsManager.lan.zip_sources import ZipLimitExceeded, estimate_zip_source_bytes
from AssetsManager.lan.zip_cleanup import cleanup_zip_path
from AssetsManager.lan.routes.quota import (
    apply_free_quota_headers,
    apply_free_quota_identity_cookie,
    consume_free_download_quota,
    get_free_download_quota_info,
    quota_retry_after_seconds,
    QuotaUnavailableError,
)

MAX_BATCH_DOWNLOAD_PATHS = 100
MAX_BATCH_DOWNLOAD_BYTES = MAX_ZIP_SOURCE_BYTES
_FALLBACK_SCAN_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="lan-zip-scan"
)



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
    extra_headers: dict[str, str] | None = None,
    on_cleanup: Callable[[], None] | None = None,
) -> TemporaryFileResponse:
    headers = {"Content-Disposition": _content_disposition_filename(filename)}
    if extra_headers:
        headers.update(extra_headers)
    return TemporaryFileResponse(
        request, path,
        headers=headers,
        on_cleanup=on_cleanup,
    )


def _estimate_download_size(target: Path) -> int:
    return estimate_zip_source_bytes([(target, None)])


def _estimate_batch_download_size(targets: list[tuple[str, Path]]) -> int:
    return estimate_zip_source_bytes([(target, None) for _, target in targets])


async def _estimate_reserved_zip_size(request, reservation: ZipReservation, estimate: Callable[[], int]) -> int:
    """Keep admission charged until the scan thread actually exits.

    A native future callback also runs after cancellation or event-loop
    shutdown; a coroutine finally alone would return the budget too early.
    """
    executor = request.app.get(ZIP_EXECUTOR_APP_KEY, _FALLBACK_SCAN_EXECUTOR)
    worker_reservation = reservation.retain()
    try:
        future = executor.submit(estimate)
    except BaseException:
        worker_reservation.release()
        raise
    future.add_done_callback(lambda _done: worker_reservation.release())
    wrapped = asyncio.wrap_future(future)
    # Retrieve a late scan exception even when the requester has gone away.
    wrapped.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    try:
        return await asyncio.shield(wrapped)
    except asyncio.CancelledError:
        future.cancel()
        raise


async def _prepare_zip_download(request, targets: list[tuple[Path, str | None]], *, filename: str, estimate: Callable[[], int]):
    preflight = _preflight_exhausted_response(request)
    if preflight is not None:
        return preflight
    budget = request.app.get(ZIP_BUDGET_APP_KEY, get_process_zip_budget())
    reservation = budget.try_acquire()
    if reservation is None:
        return error_response(
            "ZIP download capacity is busy", status=503,
            code="zip_capacity_exhausted", headers={"Retry-After": "1"},
        )

    tmp_path = None
    handed_off = False
    try:
        total_bytes = await _estimate_reserved_zip_size(request, reservation, estimate)
        if total_bytes > MAX_BATCH_DOWNLOAD_BYTES:
            raise ZipLimitExceeded("ZIP source size limit exceeded")

        import tempfile
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".zip")
        os.close(tmp_fd)
        result = await build_zip_async(request, targets, tmp_path, reservation=reservation)
        if result is None:
            return error_response("Failed to create ZIP", status=500, code="internal_error")
        try:
            quota_result = await asyncio.to_thread(consume_free_download_quota, request)
        except QuotaUnavailableError:
            return _quota_unavailable_response()
        quota_headers: dict[str, str] = {}
        apply_free_quota_headers(quota_headers, quota_result["info"])
        if not quota_result["allowed"]:
            response = _quota_denied_response(quota_result, quota_headers)
            apply_free_quota_identity_cookie(response, request)
            return response

        response = _file_response_with_cleanup(
            request, tmp_path, filename=filename, extra_headers=quota_headers,
            on_cleanup=reservation.release,
        )
        apply_free_quota_identity_cookie(response, request)
        handed_off = True
        return response
    except ZipLimitExceeded:
        return error_response("ZIP resource limits exceeded", status=413, code="zip_limits_exceeded")
    except OSError:
        return error_response("Failed to create ZIP", status=500, code="internal_error")
    finally:
        if not handed_off:
            if tmp_path is None:
                reservation.release()
            else:
                cleanup_zip_path(tmp_path, reservation.release)


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
            preflight = _preflight_exhausted_response(request)
            if preflight is not None:
                status = 429
                return preflight
            try:
                opened = await open_download_file(getattr(lan, "library_root", target.parent), target)
            except (SafeOpenError, OSError, ValueError):
                status = 404
                return error_response("File not found", status=status, code="not_found")

            handed_off = False
            try:
                response = SafeFileResponse(
                    request, opened,
                    headers={"Content-Disposition": _content_disposition_filename(target.name)},
                )
                if request.method != "HEAD":
                    try:
                        quota_result = await asyncio.to_thread(consume_free_download_quota, request)
                    except QuotaUnavailableError:
                        status = 503
                        return _quota_unavailable_response()
                    quota_headers: dict[str, str] = {}
                    apply_free_quota_headers(quota_headers, quota_result["info"])
                    if not quota_result["allowed"]:
                        status = 429
                        denied = _quota_denied_response(quota_result, quota_headers)
                        apply_free_quota_identity_cookie(denied, request)
                        return denied
                    response.headers.update(quota_headers)
                    apply_free_quota_identity_cookie(response, request)
                status = 200
                outcome = "response_ready"
                kind = "file"
                response_path = target
                handed_off = True
                return response
            finally:
                if not handed_off:
                    opened.close()

        if target.is_dir():
            response = await _prepare_zip_download(
                request, [(target, None)], filename=f"{target.name}.zip",
                estimate=lambda: _estimate_download_size(target),
            )
            status = response.status
            if status == 200:
                outcome = "response_ready"
                kind = "directory_zip"
                response_path = target
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

        zip_name = f"{targets[0][1].name}.zip" if len(targets) == 1 else f"download_{len(targets)}_items.zip"
        response = await _prepare_zip_download(
            request, [(target, None) for _, target in targets], filename=zip_name,
            estimate=lambda: _estimate_batch_download_size(targets),
        )
        status = response.status
        if status == 200:
            outcome = "response_ready"
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
