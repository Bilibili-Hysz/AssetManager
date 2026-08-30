"""System info routes: /api/info, /api/tunnel/status, /api/stats."""
import asyncio
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast

from aiohttp import web

from AssetsManager.application import ProjectDepthConfig
from AssetsManager.core.constants import DEFAULT_LAN_THEME_COLOR
from AssetsManager.core.format_utils import format_size
from AssetsManager.core.settings import AppSettings
from AssetsManager.lan.dto import RuntimeCursorResponse, StatsResponse
from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.routes._helpers import (
    get_lan,
    get_auth_service,
    get_metadata_service,
    get_project_service,
    get_request_principal,
    require_admin,
)

# /api/info is public, so an unauthenticated client could force the
# full-library project count walk on every landing/storefront refresh.  The
# count is cached per library root (30s TTL) and the walk itself runs off the
# event loop; together they turn the endpoint into a cheap cache read instead
# of a 0.5-3s per-request directory traversal.
_INFO_COUNT_CACHE: dict[str, tuple[float, int]] = {}
_INFO_COUNT_TTL = 30.0


def _owner_theme_name() -> str:
    """Display name of the owner's current desktop theme (fail-open).

    Lets the WebUI mirror the library owner's visual identity: /api/info is
    already public, and a theme display name leaks nothing.  The LAN package
    is intentionally Qt-free, so ``core.themes`` (which reaches PySide6
    through ThemeLoader) is imported lazily per call; the theme subsystem is
    already initialized in the desktop process that hosts the LAN server.
    Any failure (headless server without Qt, missing/unreadable themes,
    unexpected return type) degrades to an empty string so the response shape
    stays intact and clients keep their fallback palette.
    """
    try:
        from AssetsManager.core import themes

        name = themes.name()
    except Exception:  # noqa: BLE001 - fail-open is the contract here
        return ""
    return name if isinstance(name, str) else ""


def _cached_project_count(project_service, root, depth_config) -> int:
    key = str(Path(root).resolve())
    now = time.time()
    cached = _INFO_COUNT_CACHE.get(key)
    if cached is not None and now - cached[0] < _INFO_COUNT_TTL:
        return cached[1]
    total = project_service.count_projects(root, depth_config=depth_config)
    if len(_INFO_COUNT_CACHE) > 8:
        # Different sessions re-root the library; keep the map bounded.
        _INFO_COUNT_CACHE.clear()
    _INFO_COUNT_CACHE[key] = (now, total)
    return total


async def handle_info(request):
    # NOTE: The full /api/info payload (auth_mode, share_name, library_stats,
    # footer_text, feature_flags, ...) is intentionally served to
    # unauthenticated requests.  The frontend login page needs auth_mode to
    # decide which credential form to render (key / user / password, see
    # webui/src/pages/LoginPage.tsx), and the public landing page renders
    # share_name / library_stats / footer_text (webui/src/pages/LandingPage.tsx).
    # No secrets or per-user data are included; the principal-specific keys
    # below are only appended for authenticated principals.
    lan = get_lan(request)
    s = AppSettings.instance()

    auth_status = cast(
        Callable[[], tuple[bool, str]] | None, getattr(lan, "auth_status", None)
    )
    if callable(auth_status):
        auth_enabled, auth_mode = auth_status()
    else:
        has_key = lan.access_key_hash is not None
        has_password = lan.password_hash is not None
        has_users = get_auth_service(request).has_active_users()
        auth_enabled = has_key or has_password or has_users
        if has_key:
            auth_mode = "key"
        elif has_users:
            auth_mode = "user"
        elif has_password:
            auth_mode = "password"
        else:
            auth_mode = "none"

    depth_config = ProjectDepthConfig.from_dict(s.get("sidebar_depth_cfg"))
    total_projects = await asyncio.to_thread(
        _cached_project_count,
        get_project_service(request),
        lan.library_root,
        depth_config,
    )
    total_size = get_metadata_service(request).get_library_total_size(lan.library_root)

    principal = get_request_principal(request)
    runtime = getattr(lan, "runtime", None)
    thumbnail_cache_namespace = getattr(runtime, "epoch", None)
    result = {
        "version": "1.0",
        "share_name": lan.share_name,
        "library_root": lan.library_root.name,
        "thumbnail_cache_namespace": thumbnail_cache_namespace,
        "auth_enabled": auth_enabled,
        "auth_mode": auth_mode,
        "theme_color": s.get("lan_theme_color", DEFAULT_LAN_THEME_COLOR),
        "theme_name": _owner_theme_name(),
        "welcome_msg": s.get("lan_welcome_msg", ""),
        "footer_text": s.get("lan_footer_text", ""),
        "feature_flags": {
            "quota": bool(s.get("lan_quota_enabled", False)),
        },
        "library_stats": {
            "total_projects": total_projects,
            "total_size": total_size,
            "total_size_fmt": format_size(total_size),
        },
    }
    if principal is not None:
        result["principal"] = principal.to_dict()
        result["capabilities"] = principal.capabilities.to_dict()
    return web.json_response(result)


async def handle_tunnel_status(request):
    if not require_admin(request):
        return error_response("Admin access required", status=403, code="forbidden")
    lan = get_lan(request)
    tunnel = getattr(lan, "_tunnel", None)
    public_url = tunnel.public_url if tunnel and tunnel.is_running else None
    return web.json_response({
        "active": public_url is not None,
        "public_url": public_url,
    })


async def handle_stats(request):
    # Defense in depth: the route also declares the admin-backed "settings"
    # capability at registration time (api.py), so the middleware already
    # rejected non-admin principals before this handler runs.
    if not require_admin(request):
        return error_response("Admin access required", status=403, code="forbidden")
    lan = get_lan(request)
    status = lan.status()
    return web.json_response(StatsResponse.from_record({
        "connections": status.get("connections", 0),
        "requests": status.get("requests", 0),
        "bytes_transferred": status.get("bytes_transferred"),
        "bytes_transferred_fmt": format_size(status["bytes_transferred"]) if status.get("bytes_transferred") is not None else None,
        "uptime": status.get("uptime", 0),
    }).to_dict())


async def handle_revision(request):
    principal = get_request_principal(request)
    if principal is None or not principal.capabilities.realtime:
        return error_response("Realtime access required", status=403, code="forbidden")
    runtime = getattr(get_lan(request), "runtime", None)
    if runtime is None:
        return error_response("Runtime unavailable", status=503, code="service_unavailable")
    return web.json_response(RuntimeCursorResponse(runtime.epoch, runtime.revision).to_dict())
