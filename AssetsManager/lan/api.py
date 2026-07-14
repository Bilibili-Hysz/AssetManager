"""REST API routes for the LAN sharing server.

This module is the entry point for route registration. All handler
implementations live in ``lan/routes/`` submodules grouped by domain.
"""
from pathlib import Path

from aiohttp import web

from AssetsManager.lan.routes import (
    handle_index,
    handle_detail_page,
    handle_login_page,
    handle_browse_page,
    handle_files,
    handle_thumbnail,
    handle_thumbnail_batch,
    handle_download,
    handle_batch_download,
    handle_projects,
    handle_project_detail,
    handle_tree,
    handle_home,
    handle_tags,
    handle_create_tag,
    handle_rename_tag,
    handle_delete_tag,
    handle_search,
    handle_meta,
    handle_info,
    handle_login,
    handle_register,
    handle_verify_key,
    handle_logout,
    handle_me,
    handle_users,
    handle_toggle_user,
    handle_invites,
    handle_create_invite,
    handle_revoke_invite,
    handle_activity,
    handle_online_users,
    handle_tunnel_status,
    handle_stats,
    handle_create_share,
    handle_list_shares,
    handle_delete_share,
    handle_share_page,
    handle_verify_share_password,
    handle_share_download,
    handle_share_preview,
    handle_share_info,
    handle_websocket,
)

# Backward-compatible re-exports used by tests
from AssetsManager.lan.routes._helpers import validate_path as _validate_path
from AssetsManager.lan.routes._helpers import validated_existing_key as _validated_existing_key
from AssetsManager.lan.routes._helpers import get_auth_token as _get_auth_token

__all__ = [
    "setup_routes",
    "_get_auth_token",
    "_validate_path",
    "_validated_existing_key",
]


def setup_routes(app: web.Application, static_dir: Path):
    """Register all routes on the application."""
    app.router.add_get("/", handle_index)
    app.router.add_get("/browse", handle_browse_page)
    app.router.add_get("/detail", handle_detail_page)
    app.router.add_get("/login", handle_login_page)
    app.router.add_get("/api/files", handle_files)
    app.router.add_get("/api/thumbnails/{path:.*}", handle_thumbnail)
    app.router.add_post("/api/thumbnails/batch", handle_thumbnail_batch)
    app.router.add_get("/api/download/{path:.*}", handle_download)
    app.router.add_post("/api/download/batch", handle_batch_download)
    app.router.add_get("/api/projects", handle_projects)
    app.router.add_get("/api/projects/{path:.*}", handle_project_detail)
    app.router.add_get("/api/tree", handle_tree)
    app.router.add_get("/api/home", handle_home)
    app.router.add_get("/api/tags", handle_tags)
    app.router.add_post("/api/tags", handle_create_tag)
    app.router.add_put("/api/tags/{name}", handle_rename_tag)
    app.router.add_delete("/api/tags/{name}", handle_delete_tag)
    app.router.add_get("/api/search", handle_search)
    app.router.add_get("/api/meta/{path:.*}", handle_meta)
    app.router.add_get("/api/info", handle_info)
    app.router.add_post("/api/auth/login", handle_login)
    app.router.add_post("/api/auth/register", handle_register)
    app.router.add_post("/api/auth/verify_key", handle_verify_key)
    app.router.add_post("/api/auth/logout", handle_logout)
    app.router.add_get("/api/auth/me", handle_me)
    app.router.add_get("/api/users", handle_users)
    app.router.add_post("/api/users/{id}/toggle", handle_toggle_user)
    app.router.add_get("/api/invites", handle_invites)
    app.router.add_post("/api/invites", handle_create_invite)
    app.router.add_post("/api/invites/{code}/revoke", handle_revoke_invite)
    app.router.add_get("/api/activity", handle_activity)
    app.router.add_get("/api/online-users", handle_online_users)
    app.router.add_get("/api/tunnel/status", handle_tunnel_status)
    app.router.add_get("/api/stats", handle_stats)
    app.router.add_post("/api/shares", handle_create_share)
    app.router.add_get("/api/shares", handle_list_shares)
    app.router.add_delete("/api/shares/{id}", handle_delete_share)
    app.router.add_get("/s/{id}", handle_share_page)
    app.router.add_post("/api/shares/{id}/verify", handle_verify_share_password)
    app.router.add_get("/api/shares/{id}/download/{path:.*}", handle_share_download)
    app.router.add_get("/api/shares/{id}/preview/{path:.*}", handle_share_preview)
    app.router.add_get("/api/shares/{id}/info", handle_share_info)
    app.router.add_get("/ws", handle_websocket)

    # SPA static assets (Vite build output)
    spa_assets = Path(__file__).parent.parent.parent / "webui" / "dist" / "assets"
    if spa_assets.exists():
        app.router.add_static("/assets", spa_assets, show_index=False)

    # Legacy static files
    app.router.add_static("/static", static_dir, show_index=False)
