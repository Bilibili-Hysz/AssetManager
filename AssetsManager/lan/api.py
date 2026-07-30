"""REST API routes for the LAN sharing server.

This module is the entry point for route registration. All handler
implementations live in ``lan/routes/`` submodules grouped by domain.
"""
import asyncio
import logging
import threading

from aiohttp import web

from AssetsManager.lan.routes._helpers import (
    get_auth_token as _get_auth_token,
    validate_path as _validate_path,
    validated_existing_key as _validated_existing_key,
    LAN_APP_KEY,
)
from AssetsManager.lan.routes import (
    handle_index,
    handle_detail_page,
    handle_login_page,
    handle_browse_page,
    handle_files,
    handle_directory_summaries,
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
from AssetsManager.lan.routes.system import handle_revision

_log = logging.getLogger(__name__)

__all__ = [
    "setup_routes",
    "stop_runtime_realtime",
    "_get_auth_token",
    "_validate_path",
    "_validated_existing_key",
]


def stop_runtime_realtime(lan):
    """Stop runtime invalidation dispatching before closing its subscription."""
    realtime_gate = getattr(lan, "_realtime_gate", None)
    if realtime_gate is None:
        return
    with realtime_gate:
        subscription = getattr(lan, "_runtime_subscription", None)
        lan._runtime_subscription = None
        lan._realtime_active = False
        while lan._realtime_dispatching:
            realtime_gate.wait()
        lan._realtime_loop = None
    if subscription is not None:
        try:
            subscription.close()
        except Exception:
            _log.debug("Runtime realtime unsubscribe skipped", exc_info=True)


def setup_routes(app: web.Application):
    """Register all routes on the application."""
    app.router.add_get("/", handle_index)
    app.router.add_get("/browse", handle_browse_page)
    app.router.add_get("/detail", handle_detail_page)
    app.router.add_get("/login", handle_login_page)
    app.router.add_get("/api/files", handle_files)
    app.router.add_post("/api/files/summaries", handle_directory_summaries)
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
    app.router.add_get("/api/revision", handle_revision)
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

    async def runtime_startup(started_app):
        lan = started_app[LAN_APP_KEY]
        runtime = getattr(lan, "runtime", None)
        if runtime is None or getattr(lan, "_runtime_subscription", None) is not None:
            return
        loop = asyncio.get_running_loop()
        realtime_gate = threading.Condition()
        lan._realtime_loop = loop
        lan._realtime_active = True
        lan._realtime_gate = realtime_gate
        lan._realtime_dispatching = 0

        def on_invalidation(event):
            from AssetsManager.lan.dto import ProjectionInvalidationResponse
            payload = ProjectionInvalidationResponse(
                event.epoch, event.revision,
                tuple(str(domain) for domain in event.domains),
                tuple(event.paths),
            ).to_dict()
            try:
                with realtime_gate:
                    if not lan._realtime_active:
                        return
                if loop.is_closed() or not loop.is_running():
                    return
                with realtime_gate:
                    if not lan._realtime_active:
                        return
                    lan._realtime_dispatching += 1
                    try:
                        broadcast_coro = lan.ws_manager.broadcast(
                            "projection_invalidated", payload,
                        )
                        try:
                            future = asyncio.run_coroutine_threadsafe(broadcast_coro, loop)
                        except Exception:
                            broadcast_coro.close()
                            raise
                    finally:
                        lan._realtime_dispatching -= 1
                        realtime_gate.notify_all()
                def observe_broadcast(done):
                    try:
                        done.result()
                    except asyncio.CancelledError:
                        _log.debug("Runtime realtime broadcast cancelled")
                    except Exception:
                        _log.debug("Runtime realtime broadcast failed", exc_info=True)
                    except BaseException:
                        _log.debug("Runtime realtime broadcast failed with base exception", exc_info=True)
                future.add_done_callback(observe_broadcast)
            except Exception:
                _log.debug("Runtime realtime broadcast skipped", exc_info=True)

        lan._runtime_subscription = runtime.event_router.subscribe(on_invalidation)

    async def runtime_cleanup(cleanup_app):
        lan = cleanup_app[LAN_APP_KEY]
        stop_runtime_realtime(lan)

    app.on_startup.append(runtime_startup)
    app.on_cleanup.append(runtime_cleanup)

    # SPA static assets (Vite build output)
    from AssetsManager.lan.routes.pages import SPA_DIR
    spa_assets = SPA_DIR / "assets"
    if spa_assets.exists():
        app.router.add_static("/assets", spa_assets, show_index=False)
