"""Share link routes: /api/shares/*, /s/{id}."""
import logging
from pathlib import Path
from time import perf_counter

from urllib.parse import quote, unquote

from aiohttp import web

from AssetsManager.domain.share import ShareLink
from AssetsManager.domain.asset import IMAGE_EXTS
from AssetsManager.lan.routes._helpers import get_share_service, get_lan, get_request_user, get_share_token, require_permission, sanitize_filename, set_share_cookie, validate_path
from AssetsManager.lan.routes.pages import _spa_index
from AssetsManager.lan.utils import get_local_ip

_log = logging.getLogger(__name__)


def _content_disposition_filename(name: str) -> str:
    clean = sanitize_filename(name)
    ascii_name = clean.encode("ascii", "ignore").decode("ascii") or "download"
    header = f'attachment; filename="{ascii_name}"'
    if clean != ascii_name:
        header += f"; filename*=UTF-8''{quote(clean, safe='')}"
    return header


def _resolve_share_target(lan, share: ShareLink, rel_path: str) -> Path | None:
    """Resolve a path within a share's scope, with path traversal protection.

    Uses canonical path containment (``Path.is_relative_to``) instead of
    string prefix checks so that ``..`` segments and other tricks cannot
    escape the share scope.
    """
    library_root = lan.library_root.resolve()
    try:
        candidate = (library_root / rel_path).resolve()
    except (ValueError, OSError):
        return None
    if not candidate.is_relative_to(library_root):
        return None
    for sp in share.paths:
        try:
            full = (library_root / sp).resolve()
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
        return web.json_response({"error": "Forbidden"}, status=403)

    lan = get_lan(request)
    share_svc = get_share_service(request)
    user = get_request_user(request)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid request body"}, status=400)

    paths = body.get("paths", [])
    if not paths:
        return web.json_response({"error": "No paths provided"}, status=400)
    if len(paths) > 100:
        return web.json_response({"error": "Too many paths (max 100)"}, status=400)

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
        return web.json_response({"error": "No valid paths"}, status=400)

    password = body.get("password")
    if password is not None:
        if not isinstance(password, str):
            return web.json_response({"error": "Invalid password format"}, status=400)
        if len(password) > 0 and len(password) < 4:
            return web.json_response({"error": "Password must be at least 4 characters"}, status=400)
        if len(password) > 128:
            return web.json_response({"error": "Password must be less than 128 characters"}, status=400)

    expires_hours = body.get("expires_hours")
    if expires_hours is not None:
        try:
            expires_hours = int(expires_hours)
            if expires_hours < 1 or expires_hours > 8760:
                return web.json_response({"error": "Expiry must be between 1 and 8760 hours"}, status=400)
        except (ValueError, TypeError):
            return web.json_response({"error": "Invalid expiry format"}, status=400)

    max_downloads = body.get("max_downloads")
    if max_downloads is not None:
        try:
            max_downloads = int(max_downloads)
            if max_downloads < 1 or max_downloads > 10000:
                return web.json_response({"error": "Max downloads must be between 1 and 10000"}, status=400)
        except (ValueError, TypeError):
            return web.json_response({"error": "Invalid max downloads format"}, status=400)

    allow_preview = body.get("allow_preview", True)

    share = share_svc.create_share(
        paths=valid_paths, password=password,
        expires_hours=expires_hours, max_downloads=max_downloads,
        allow_preview=allow_preview,
        created_by=user.get("username") if user else None,
    )

    if not share:
        return web.json_response({"error": "Failed to create share link"}, status=500)

    ip = get_local_ip()
    protocol = "https" if lan._ssl_cert and lan._ssl_key else "http"
    share_url = f"{protocol}://{ip}:{lan._port}/s/{share.id}"

    result = share.to_public_dict()
    result["requires_key"] = bool(lan.access_key_hash)
    result["url"] = share_url

    return web.json_response(result)


async def handle_list_shares(request):
    if not require_permission(request, "manage_links"):
        return web.json_response({"error": "Forbidden"}, status=403)

    lan = get_lan(request)
    share_svc = get_share_service(request)
    user = get_request_user(request)
    if user is None:
        return web.json_response({"error": "Unauthorized"}, status=401)

    created_by = None if user.get("role") == "admin" else user.get("username")
    shares = share_svc.list_shares(created_by=created_by)

    ip = get_local_ip()
    protocol = "https" if lan._ssl_cert and lan._ssl_key else "http"
    result = []
    for share in shares:
        info = share.to_public_dict()
        info["url"] = f"{protocol}://{ip}:{lan._port}/s/{share.id}"
        info["requires_key"] = bool(lan.access_key_hash)
        result.append(info)

    return web.json_response({"shares": result})


async def handle_delete_share(request):
    if not require_permission(request, "manage_links"):
        return web.json_response({"error": "Forbidden"}, status=403)

    share_svc = get_share_service(request)
    user = get_request_user(request)
    share_id = request.match_info.get("id", "")

    share = share_svc.get_share_record(share_id)
    if not share:
        return web.json_response({"error": "Share not found"}, status=404)
    if share.is_expired():
        return web.json_response({"error": "Share expired"}, status=410)

    if user and user.get("role") == "admin":
        pass
    elif share.created_by and user and share.created_by == user.get("username"):
        pass
    else:
        return web.json_response({"error": "Access denied"}, status=403)

    ok = share_svc.delete_share(share_id)
    return web.json_response({"ok": ok})


async def handle_share_page(request):
    spa_index = _spa_index()
    if spa_index:
        return web.FileResponse(spa_index)
    # Fallback to old share page
    static_dir = Path(__file__).parent.parent / "static"
    share_file = static_dir / "share.html"
    if share_file.exists():
        return web.FileResponse(share_file)
    return web.Response(text="Share page not found", status=404)


async def handle_verify_share_password(request):
    share_svc = get_share_service(request)
    share_id = request.match_info.get("id", "")

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid request"}, status=400)

    password = body.get("password", "")

    share = share_svc.get_share_record(share_id)
    if not share:
        return web.json_response({"error": "Share not found"}, status=404)
    if share.is_expired():
        return web.json_response({"error": "Share expired"}, status=410)

    if not share.has_password or share_svc.verify_password(share_id, password):
        token = share_svc.generate_token(share_id)
        result = {"share": share.to_public_dict()}
        if request.headers.get("X-AssetsManager-API-Client") == "1":
            result["token"] = token
            return web.json_response(result)
        response = web.json_response(result)
        set_share_cookie(response, share_id, token)
        return response

    return web.json_response({"error": "Invalid password"}, status=401)


async def handle_share_download(request):
    lan = get_lan(request)
    started = perf_counter()
    status = 500
    outcome = "error"
    response_path = None
    try:
        share_svc = get_share_service(request)
        share_id = request.match_info.get("id", "")
        rel_path = unquote(request.match_info.get("path", ""))

        share = share_svc.get_share_record(share_id)
        if not share:
            status = 404
            return web.json_response({"error": "Share not found"}, status=status)

        token = get_share_token(request) if share.has_password else None
        if share.has_password and not share_svc.verify_token(token or "", share_id):
            status = 401
            return web.json_response({"error": "Unauthorized"}, status=status)

        if share.is_download_limit_reached():
            status = 403
            return web.json_response({"error": "Download limit reached"}, status=status)

        if share.is_expired():
            status = 410
            return web.json_response({"error": "Share expired"}, status=status)

        target = _resolve_share_target(lan, share, rel_path)

        if not target:
            library_root = lan.library_root.resolve()
            candidate = (library_root / rel_path).resolve()
            status = 403 if candidate.exists() and candidate.is_relative_to(library_root) else 404
            return web.json_response(
                {"error": "File not in share scope" if status == 403 else "File not found in share"}, status=status
            )

        if not target.is_file():
            status = 400
            return web.json_response({"error": "Not a file"}, status=status)
        if not share_svc.increment_download(share_id):
            status = 403
            return web.json_response({"error": "Download limit reached"}, status=status)
        status = 200
        outcome = "response_ready"
        response_path = target
        return web.FileResponse(
            target,
            headers={"Content-Disposition": _content_disposition_filename(target.name)},
        )
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
    rel_path = unquote(request.match_info.get("path", ""))

    share = share_svc.get_share_record(share_id)
    if not share:
        return web.json_response({"error": "Share not found"}, status=404)
    if share.is_expired():
        return web.json_response({"error": "Share expired"}, status=410)

    if not share.allow_preview:
        return web.json_response({"error": "Preview not allowed"}, status=403)

    if share.has_password:
        token = get_share_token(request)
        if not share_svc.verify_token(token, share_id):
            return web.json_response({"error": "Unauthorized"}, status=401)

    target = _resolve_share_target(lan, share, rel_path)

    if not target:
        return web.json_response({"error": "File not found in share"}, status=404)

    if target.suffix.lower() not in IMAGE_EXTS:
        return web.json_response({"error": "Not an image"}, status=400)

    return web.FileResponse(target)


async def handle_share_info(request):
    share_svc = get_share_service(request)
    share_id = request.match_info.get("id", "")

    share = share_svc.get_share_record(share_id)
    if not share:
        return web.json_response({"error": "Share not found"}, status=404)

    if share.has_password:
        token = get_share_token(request)
        if not token or not share_svc.verify_token(token, share_id):
            return web.json_response({
                "id": share.id,
                "has_password": True,
                "expired": share.is_expired(),
                "allow_preview": share.allow_preview,
            })

    return web.json_response(share.to_public_dict())
