"""System info routes: /api/info, /api/tunnel/status, /api/stats."""
from aiohttp import web

from AssetsManager.application import ProjectDepthConfig
from AssetsManager.core.format_utils import format_size
from AssetsManager.core.settings import AppSettings
from AssetsManager.lan.dto import RuntimeCursorResponse, StatsResponse
from AssetsManager.lan.routes._helpers import (
    get_lan,
    get_auth_service,
    get_metadata_service,
    get_project_service,
    get_request_principal,
    require_admin,
)


async def handle_info(request):
    lan = get_lan(request)
    s = AppSettings.instance()

    auth_status = getattr(lan, "auth_status", None)
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
    total_projects = get_project_service(request).count_projects(lan.library_root, depth_config=depth_config)
    total_size = get_metadata_service(request).get_library_total_size(lan.library_root)

    principal = get_request_principal(request)
    result = {
        "version": "1.0",
        "share_name": lan.share_name,
        "library_root": lan.library_root.name,
        "auth_enabled": auth_enabled,
        "auth_mode": auth_mode,
        "theme_color": s.get("lan_theme_color", "#5b7ff5"),
        "welcome_msg": s.get("lan_welcome_msg", ""),
        "footer_text": s.get("lan_footer_text", ""),
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
        return web.json_response({"error": "Admin access required"}, status=403)
    lan = get_lan(request)
    tunnel = getattr(lan, "_tunnel", None)
    public_url = tunnel.public_url if tunnel and tunnel.is_running else None
    return web.json_response({
        "active": public_url is not None,
        "public_url": public_url,
    })


async def handle_stats(request):
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
        return web.json_response({"error": "Realtime access required"}, status=403)
    runtime = getattr(get_lan(request), "runtime", None)
    if runtime is None:
        return web.json_response({"error": "Runtime unavailable"}, status=503)
    return web.json_response(RuntimeCursorResponse(runtime.epoch, runtime.revision).to_dict())
