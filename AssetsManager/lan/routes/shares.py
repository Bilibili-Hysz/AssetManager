"""Share link routes: /api/shares/*, /s/{id}."""
import asyncio
import logging
from pathlib import Path
from time import perf_counter

from urllib.parse import quote

from aiohttp import web

from AssetsManager.domain.errors import ValidationError
from AssetsManager.domain.share import ShareLink
from AssetsManager.domain.asset import IMAGE_EXTS
from AssetsManager.lan.path_guard import PathGuardError, assert_under_root, reject_path_text
from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.routes._helpers import LAN_APP_KEY, get_lan, get_share_service, get_request_principal, get_share_token, require_permission, sanitize_filename, set_share_cookie, set_request_principal, validate_path
from AssetsManager.lan.principal import principal_for_request
from AssetsManager.lan.utils import get_local_ip

_log = logging.getLogger(__name__)

_SAFE_IMAGE_EXTS = IMAGE_EXTS - {".svg"}


def _content_disposition_filename(name: str) -> str:
    clean = sanitize_filename(name)
    ascii_name = clean.encode("ascii", "ignore").decode("ascii") or "download"
    header = f'attachment; filename="{ascii_name}"'
    if clean != ascii_name:
        header += f"; filename*=UTF-8''{quote(clean, safe='')}"
    return header


def _resolve_share_target(lan, share: ShareLink, rel_path: str) -> Path | None:
    """Resolve a path within a share's scope, with path traversal protection.

    Reuses the PathGuard character gate and the shared containment predicate
    instead of inline checks, so ``..`` segments, control characters, and
    NTFS stream separators are all rejected by the same code every other
    route uses.
    """
    try:
        reject_path_text(rel_path)
        candidate = assert_under_root(lan.library_root, Path(lan.library_root) / rel_path)
    except (PathGuardError, ValueError, OSError):
        return None
    for sp in share.paths:
        try:
            full = (Path(lan.library_root) / sp).resolve()
        except (ValueError, OSError):
            continue
        if not full.exists():
            continue
        if candidate == full or candidate.is_relative_to(full):
            if candidate.exists():
                return candidate
    return None


async def handle_create_share(request):
    if not require_permission(request, "manage_links"):
        return error_response("Forbidden", status=403, code="forbidden")

    lan = get_lan(request)
    share_svc = get_share_service(request)
    principal = get_request_principal(request)

    try:
        body = await request.json()
    except Exception:
        return error_response("Invalid request body", status=400, code="bad_request")

    paths = body.get("paths", [])
    if not paths:
        return error_response("No paths provided", status=400, code="bad_request")
    if len(paths) > 100:
        return error_response("Too many paths (max 100)", status=400, code="bad_request")

    valid_paths = []
    for p in paths:
        if not isinstance(p, str) or not p.strip():
            continue
        try:
            target = validate_path(lan, p)
            if target.exists():
                valid_paths.append(p)
        except web.HTTPException:
            raise
        except Exception:
            continue

    if not valid_paths:
        return error_response("No valid paths", status=400, code="bad_request")

    try:
        password = share_svc.validate_password(body.get("password"))
    except ValidationError as exc:
        return error_response(exc.message, status=400, code="bad_request")

    expires_hours = body.get("expires_hours")
    if expires_hours is not None:
        if isinstance(expires_hours, bool) or not isinstance(expires_hours, (int, str)):
            return error_response("Invalid expiry format", status=400, code="bad_request")
        try:
            expires_hours = int(expires_hours)
        except (ValueError, TypeError, OverflowError):
            return error_response("Invalid expiry format", status=400, code="bad_request")
        try:
            expires_hours = share_svc.validate_expires_hours(expires_hours)
        except ValidationError as exc:
            return error_response(exc.message, status=400, code="bad_request")

    max_downloads = body.get("max_downloads")
    if max_downloads is not None:
        if isinstance(max_downloads, bool) or not isinstance(max_downloads, (int, str)):
            return error_response("Invalid max downloads format", status=400, code="bad_request")
        try:
            max_downloads = int(max_downloads)
        except (ValueError, TypeError, OverflowError):
            return error_response("Invalid max downloads format", status=400, code="bad_request")
        try:
            max_downloads = share_svc.validate_max_downloads(max_downloads)
        except ValidationError as exc:
            return error_response(exc.message, status=400, code="bad_request")

    allow_preview = body.get("allow_preview", True)

    try:
        share = share_svc.create_share(
            paths=valid_paths, password=password,
            expires_hours=expires_hours, max_downloads=max_downloads,
            allow_preview=allow_preview,
            created_by=principal.display_name if principal and principal.authenticated else None,
        )
    except ValidationError as exc:
        return error_response(exc.message, status=400, code="bad_request")

    if not share:
        return error_response("Failed to create share link", status=500, code="internal_error")

    ip = await asyncio.to_thread(get_local_ip)
    protocol = getattr(lan, "endpoint_protocol", "http")
    share_url = f"{protocol}://{ip}:{lan._port}/s/{share.id}"

    result = share.to_public_dict()
    result["requires_key"] = bool(lan.access_key_hash)
    result["url"] = share_url
    services = getattr(lan, "services", None)
    activity_log = getattr(services, "activity_log", None)
    if activity_log is not None:
        activity_log.add(principal.display_name if principal else None, "share", "created share link", ip=request.remote or "unknown")

    return web.json_response(result)


async def handle_list_shares(request):
    if not require_permission(request, "manage_links"):
        return error_response("Forbidden", status=403, code="forbidden")

    lan = get_lan(request)
    share_svc = get_share_service(request)
    principal = get_request_principal(request)
    if principal is None:
        return error_response("Unauthorized", status=401, code="unauthorized")

    created_by = None if principal.role == "admin" else principal.display_name
    shares = share_svc.list_shares(created_by=created_by)

    ip = await asyncio.to_thread(get_local_ip)
    protocol = getattr(lan, "endpoint_protocol", "http")
    result = []
    for share in shares:
        info = share.to_public_dict()
        info["url"] = f"{protocol}://{ip}:{lan._port}/s/{share.id}"
        info["requires_key"] = bool(lan.access_key_hash)
        result.append(info)

    return web.json_response({"shares": result})


async def handle_delete_share(request):
    if not require_permission(request, "manage_links"):
        return error_response("Forbidden", status=403, code="forbidden")

    share_svc = get_share_service(request)
    principal = get_request_principal(request)
    share_id = request.match_info.get("id", "")

    share = share_svc.get_share_record(share_id)
    if not share:
        return error_response("Share not found", status=404, code="not_found")
    if share.is_expired():
        return error_response("Share expired", status=410, code="gone")

    if principal and principal.role == "admin":
        pass
    elif share.created_by and principal and share.created_by == principal.display_name:
        pass
    else:
        return error_response("Access denied", status=403, code="forbidden")

    ok = share_svc.delete_share(share_id)
    return web.json_response({"ok": ok})


async def handle_share_page(request):
    from AssetsManager.lan.routes.pages import _spa_response

    return _spa_response()


async def handle_verify_share_password(request):
    share_svc = get_share_service(request)
    lan = request.app.get(LAN_APP_KEY)
    share_id = request.match_info.get("id", "")

    try:
        body = await request.json()
    except Exception:
        return error_response("Invalid request", status=400, code="bad_request")

    password = body.get("password", "")

    share = share_svc.get_share_record(share_id)
    if not share:
        return error_response("Share not found", status=404, code="not_found")
    if share.is_expired():
        return error_response("Share expired", status=410, code="gone")

    if share.has_password:
        # Brute-force guard (in-process per-share counter, see
        # ShareService.password_attempt_blocked).  Both the failure and
        # success paths run the full PBKDF2 verification, so the only
        # timing difference is this explicit rate-limit refusal.
        retry_after = share_svc.password_attempt_blocked(share_id)
        if retry_after:
            return error_response(
                "Too many failed password attempts. Please try again later.",
                status=429,
                code="rate_limited",
                extra={"retry_after": retry_after},
                headers={"Retry-After": str(retry_after)},
            )
        if not share_svc.verify_password(share_id, password):
            share_svc.record_password_failure(share_id)
            return error_response("Invalid password", status=401, code="unauthorized")
        share_svc.reset_password_failures(share_id)

    set_request_principal(request, principal_for_request("share"))
    token = share_svc.generate_token(share_id)
    result = {"share": share.to_public_dict()}
    if request.headers.get("X-AssetsManager-API-Client") == "1":
        result["token"] = token
        return web.json_response(result)
    response = web.json_response(result)
    set_share_cookie(response, share_id, token,
                     secure=getattr(lan, "ssl_active", False) if lan is not None else False)
    return response


async def handle_share_download(request):
    lan = get_lan(request)
    started = perf_counter()
    status = 500
    outcome = "error"
    response_path = None
    try:
        share_svc = get_share_service(request)
        share_id = request.match_info.get("id", "")
        rel_path = request.match_info.get("path", "")  # aiohttp decodes match_info once

        # L3: all semantic admission checks (existence, password token,
        # expiry, download limit, path scope) live in
        # ShareService.validate_access — keep this route's filesystem
        # resolution (_resolve_share_target) as the only inline counterpart.
        share, access_err = share_svc.validate_access(
            share_id, rel_path, token=get_share_token(request)
        )

        if share is None or access_err:
            if access_err == "Unauthorized":
                # 401 is retained: it signals that a password-protected
                # share needs verification (ShareReceivePage posts to
                # /verify; the frontend does not branch on any other code).
                status = 401
                return error_response("Unauthorized", status=status, code="unauthorized")
            # L2: fold every other state (unknown share, expired, download
            # limit reached, path outside scope) into a single 404 so public
            # callers cannot distinguish share existence / expiry / quota
            # state — mirrors the shop get_public_item folding strategy.
            status = 404
            return error_response("Share not found", status=status, code="not_found")

        target = _resolve_share_target(lan, share, rel_path)

        if not target:
            status = 404
            return error_response("Share not found", status=status, code="not_found")

        if not target.is_file():
            status = 400
            return error_response("Not a file", status=status, code="bad_request")

        set_request_principal(request, principal_for_request("share"))
        response = web.FileResponse(
            target,
            headers={"Content-Disposition": _content_disposition_filename(target.name)},
        )

        # M2: count the download only after the response is fully prepared
        # (FileResponse construction verifies the file is readable), so a
        # client that aborts mid-transfer still consumes quota but a failed
        # response never does.  The DB increment is atomic against
        # max_downloads, so concurrent races surface here as 429 instead of
        # an oversold download.
        if not share_svc.increment_download(share_id):
            status = 429
            return error_response(
                "Download limit reached",
                status=status,
                code="rate_limited",
                extra={"retry_after": 0},
                headers={"Retry-After": "0"},
            )

        status = 200
        outcome = "response_ready"
        response_path = target
        return response
    finally:
        _record_share_download_route(lan, started, response_path, outcome, status)


def _record_share_download_route(lan, started: float, response_path, outcome: str, status: int) -> None:
    recorder = getattr(lan, "performance_recorder", None)
    if recorder is None or not recorder.enabled:
        return
    try:
        recorder.record(
            "lan.share_download",
            (perf_counter() - started) * 1000,
            session_token=getattr(lan, "session_token", None),
            path=str(response_path) if response_path is not None else None,
            attributes={
                "outcome": outcome,
                "status": status,
                "phase": "response_ready" if outcome == "response_ready" else "failed",
                "kind": "share_file",
            },
        )
    except Exception:
        # Diagnostics must not alter share admission or response transfer semantics.
        pass


async def handle_share_preview(request):
    lan = get_lan(request)
    share_svc = get_share_service(request)
    share_id = request.match_info.get("id", "")
    rel_path = request.match_info.get("path", "")  # aiohttp decodes match_info once

    share = share_svc.get_share_record(share_id)
    if not share:
        return error_response("Share not found", status=404, code="not_found")
    if share.is_expired():
        return error_response("Share expired", status=410, code="gone")

    if not share.allow_preview:
        return error_response("Preview not allowed", status=403, code="forbidden")

    if share.has_password:
        token = get_share_token(request)
        if not share_svc.verify_token(token, share_id):
            return error_response("Unauthorized", status=401, code="unauthorized")
    target = _resolve_share_target(lan, share, rel_path)

    if not target:
        return error_response("File not found in share", status=404, code="not_found")

    if target.suffix.lower() not in _SAFE_IMAGE_EXTS:
        return error_response("Not an image", status=400, code="bad_request")

    set_request_principal(request, principal_for_request("share"))
    return web.FileResponse(
        target,
        headers={"X-Content-Type-Options": "nosniff"},
    )


async def handle_share_info(request):
    share_svc = get_share_service(request)
    share_id = request.match_info.get("id", "")

    share = share_svc.get_share_record(share_id)
    if not share:
        return error_response("Share not found", status=404, code="not_found")

    if share.has_password:
        token = get_share_token(request)
        if not token or not share_svc.verify_token(token, share_id):
            return web.json_response({
                "id": share.id,
                "has_password": True,
                "expired": share.is_expired(),
                "allow_preview": share.allow_preview,
            })

    set_request_principal(request, principal_for_request("share"))
    return web.json_response(share.to_public_dict())
