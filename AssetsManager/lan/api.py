"""REST API routes for the LAN sharing server.

This module is the entry point for route registration. All handler
implementations live in ``lan/routes/`` submodules grouped by domain.
"""
import asyncio
import logging
import threading

from aiohttp import web

from AssetsManager.lan.route_policy import RoutePolicy, declare

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
    handle_gallery_page,
    handle_gallery_collection_page,
    handle_gallery_favorites_page,
    handle_gallery_collection,
    handle_gallery_home,
    handle_gallery_resolve,
    handle_add_favorite,
    handle_favorites,
    handle_remove_favorite,
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
    handle_remove_tag,
    handle_collections,
    handle_create_collection,
    handle_update_collection,
    handle_delete_collection,
    handle_collection_members,
    handle_add_collection_members,
    handle_remove_collection_members,
    handle_collection_evaluate,
    handle_search,
    handle_meta,
    handle_save_notes,
    handle_save_rating,
    handle_info,
    handle_login,
    handle_register,
    handle_verify_key,
    handle_logout,
    handle_me,
    handle_users,
    handle_toggle_user,
    handle_update_user,
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
    handle_free_quota,
)
from AssetsManager.lan.routes.image import handle_image
from AssetsManager.lan.routes.quicksearch import handle_quicksearch
from AssetsManager.lan.routes.sequence import handle_sequence_neighbors
from AssetsManager.lan.routes.system import handle_revision
from AssetsManager.lan.mcp_server import handle_mcp_post

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
    """Register all routes on the application.

    Every route declares its security policy (auth + rate-limit class) at
    registration time; the security and auth middlewares read it back via
    route_policy.lookup instead of hardcoded path lists.
    """
    _DEFAULT = RoutePolicy()
    _PUBLIC = RoutePolicy(auth="public")
    _PUBLIC_OPTIONAL = RoutePolicy(auth="public_optional")
    _SKIP = RoutePolicy(rate_limit="skip")
    _PUBLIC_SKIP = RoutePolicy(auth="public", rate_limit="skip")
    _OPTIONAL_SKIP = RoutePolicy(auth="public_optional", rate_limit="skip")
    _AUTH_STRICT = RoutePolicy(rate_limit="auth_strict")
    _PUBLIC_AUTH_STRICT = RoutePolicy(auth="public", rate_limit="auth_strict")
    _OPTIONAL_AUTH_STRICT = RoutePolicy(auth="public_optional", rate_limit="auth_strict")

    # ── L1 declarative capabilities ──────────────────────────────
    # Every write route names the capability it requires. Enforcement runs
    # in _auth_middleware via lan/authorization.py; handlers keep their own
    # guards as defense in depth.
    _BROWSE = ("browse",)
    _PREVIEW = ("preview",)
    _DOWNLOAD = ("download",)
    _MANAGE_LINKS = ("manage_links",)
    _WRITE_NOTES = ("write_notes",)
    _WRITE_TAGS = ("write_tags",)
    _ADMIN_TAGS = ("admin_tags",)
    _ADMIN_USERS = ("admin_users",)
    _PUBLIC_AUTH = ("public_auth",)
    _SHARE_VERIFY = ("share_verify",)
    # Server operational metrics are admin-level: they leak connection /
    # request volumes and uptime to any principal that can read them.
    _SETTINGS = ("settings",)
    # Sensitive read surfaces name the capability their data plane requires
    # so the middleware enforces what the handler-level admin guards already
    # do (defense in depth): the user / invite / activity / online-users
    # listings expose account and operator data, and tunnel status leaks the
    # operator's public URL. Rate-limit tiers are unchanged (golden contract).
    _SETTINGS_BROWSE = RoutePolicy(rate_limit="browse", capabilities=_SETTINGS)
    _ADMIN_USER_BROWSE = RoutePolicy(rate_limit="browse", capabilities=_ADMIN_USERS)

    _PREVIEW_WRITE_SKIP = RoutePolicy(rate_limit="skip", capabilities=_PREVIEW)
    _DOWNLOAD_WRITE = RoutePolicy(capabilities=_DOWNLOAD)
    _ADMIN_TAG = RoutePolicy(capabilities=_ADMIN_TAGS)
    _ADMIN_USER = RoutePolicy(capabilities=_ADMIN_USERS)
    _LINK_WRITE = RoutePolicy(capabilities=_MANAGE_LINKS)
    _AUTH_BOOTSTRAP = RoutePolicy(capabilities=_PUBLIC_AUTH)
    _PUBLIC_AUTH_STRICT_CAP = RoutePolicy(
        auth="public", rate_limit="auth_strict", capabilities=_PUBLIC_AUTH
    )
    _PUBLIC_BOOTSTRAP = RoutePolicy(auth="public", capabilities=_PUBLIC_AUTH)
    _SHARE_VERIFY_PUBLIC = RoutePolicy(
        auth="public", rate_limit="auth_strict", capabilities=_SHARE_VERIFY
    )

    # ── L2 browse tier ──────────────────────────────────────────
    # Heavy public browsing surfaces share a generous dedicated budget.
    _BROWSE_RATE = RoutePolicy(rate_limit="browse")
    _PUBLIC_BROWSE = RoutePolicy(auth="public", rate_limit="browse")
    _OPTIONAL_BROWSE = RoutePolicy(auth="public_optional", rate_limit="browse")
    _BROWSE_WRITE = RoutePolicy(rate_limit="browse", capabilities=_BROWSE)
    _WRITE_NOTES_BROWSE = RoutePolicy(rate_limit="browse", capabilities=_WRITE_NOTES)
    _WRITE_TAG_BROWSE = RoutePolicy(rate_limit="browse", capabilities=_WRITE_TAGS)

    _declared_patterns: set[str] = set()

    def _add(app, method, path, handler, *, policy=_DEFAULT, policy_method=None, **kwargs):
        add = {
            "GET": app.router.add_get,
            "POST": app.router.add_post,
            "PUT": app.router.add_put,
            "PATCH": app.router.add_patch,
            "DELETE": app.router.add_delete,
        }[method]
        add(path, handler, **kwargs)
        # Every method keeps its own policy entry; the first registration of
        # a pattern also seeds the pattern-level fallback (used by HEAD and
        # any method aiohttp derives from the resource). Later methods with
        # different policies therefore cannot overwrite the fallback.
        if path not in _declared_patterns:
            _declared_patterns.add(path)
            declare(app, path, policy, method=policy_method or "")
        declare(app, path, policy, method=method)

    _add(app, "GET", "/", handle_index, policy=_PUBLIC)
    _add(app, "GET", "/browse", handle_browse_page, policy=_PUBLIC)
    _add(app, "GET", "/detail", handle_detail_page, policy=_PUBLIC)
    _add(app, "GET", "/login", handle_login_page, policy=_PUBLIC)
    # Gallery pages are public SPA shells like /browse: the page loads for
    # anonymous visitors and its /api/gallery calls still enforce auth and
    # guest capabilities (fixes the /browse vs /gallery asymmetry).
    _add(app, "GET", "/gallery", handle_gallery_page, policy=_PUBLIC)
    _add(app, "GET", "/gallery/collection", handle_gallery_collection_page, policy=_PUBLIC)
    _add(app, "GET", "/gallery/favorites", handle_gallery_favorites_page, policy=_PUBLIC)
    # Keep deep links from the reference WebUI serving the SPA as well. The
    # React router performs the canonical redirect; these server routes only
    # prevent a direct browser refresh from falling through to a 404.
    _add(app, "GET", "/api/gallery/home", handle_gallery_home, policy=_BROWSE_RATE)
    _add(app, "GET", "/api/gallery/collection", handle_gallery_collection, policy=_BROWSE_RATE)
    _add(app, "GET", "/api/gallery/resolve", handle_gallery_resolve, policy=_BROWSE_RATE)
    _add(app, "GET", "/api/image", handle_image, policy=_SKIP)
    _add(app, "GET", "/api/favorites", handle_favorites, policy=_BROWSE_RATE)
    _add(app, "POST", "/api/favorites", handle_add_favorite, policy=_BROWSE_WRITE)
    _add(app, "POST", "/api/favorites/remove", handle_remove_favorite, policy=_BROWSE_WRITE)
    _add(app, "DELETE", "/api/favorites", handle_remove_favorite, policy=_BROWSE_WRITE)
    # /api/files is browse-scoped to GET; every other method keeps the
    # declared pattern-level general default.
    _add(app, "GET", "/api/files", handle_files, policy=_DEFAULT)
    declare(app, "/api/files", _BROWSE_RATE, method="GET")
    _add(app, "POST", "/api/files/summaries", handle_directory_summaries, policy=_BROWSE_WRITE)
    _add(app, "GET", "/api/thumbnails/{path:.*}", handle_thumbnail, policy=_SKIP)
    _add(app, "POST", "/api/thumbnails/batch", handle_thumbnail_batch, policy=_PREVIEW_WRITE_SKIP)
    _add(app, "GET", "/api/download/{path:.*}", handle_download)
    _add(app, "POST", "/api/download/batch", handle_batch_download, policy=_DOWNLOAD_WRITE)
    _add(app, "GET", "/api/projects", handle_projects, policy=_BROWSE_RATE)
    _add(app, "GET", "/api/projects/{path:.*}", handle_project_detail)
    _add(app, "GET", "/api/tree", handle_tree, policy=_BROWSE_RATE)
    _add(app, "GET", "/api/home", handle_home, policy=_BROWSE_RATE)
    _add(app, "GET", "/api/tags", handle_tags, policy=_BROWSE_RATE)
    _add(app, "POST", "/api/tags", handle_create_tag, policy=_WRITE_TAG_BROWSE)
    _add(app, "PUT", "/api/tags/{name}", handle_rename_tag, policy=_ADMIN_TAG)
    _add(app, "DELETE", "/api/tags/{name}", handle_delete_tag, policy=_ADMIN_TAG)
    _add(app, "POST", "/api/tags/remove", handle_remove_tag, policy=_ADMIN_TAG)
    # User collections (manual reference sets + smart query views): reads
    # declare the browse capability, writes reuse the write_tags capability
    # (user metadata writes) — no new capability bit. Rate limits stay on
    # the general tier, matching the frozen golden policy contract.
    # Read-only MCP surface (H2-d2): registered always, answers 404 while
    # lan_mcp_token is empty (fail-closed, invisible by default).  Bearer
    # auth lives in the handler — the LAN session layer sees it as public.
    _add(app, "POST", "/mcp", handle_mcp_post,
         policy=RoutePolicy(auth="public", capabilities=_BROWSE))
    _add(app, "GET", "/api/collections", handle_collections, policy=RoutePolicy(capabilities=_BROWSE))
    _add(app, "POST", "/api/collections", handle_create_collection, policy=RoutePolicy(capabilities=_WRITE_TAGS))
    _add(app, "PATCH", "/api/collections/{id}", handle_update_collection, policy=RoutePolicy(capabilities=_WRITE_TAGS))
    _add(app, "DELETE", "/api/collections/{id}", handle_delete_collection, policy=RoutePolicy(capabilities=_WRITE_TAGS))
    _add(app, "GET", "/api/collections/{id}/members", handle_collection_members, policy=RoutePolicy(capabilities=_BROWSE))
    _add(app, "POST", "/api/collections/{id}/members", handle_add_collection_members, policy=RoutePolicy(capabilities=_WRITE_TAGS))
    _add(app, "DELETE", "/api/collections/{id}/members", handle_remove_collection_members, policy=RoutePolicy(capabilities=_WRITE_TAGS))
    _add(app, "GET", "/api/collections/{id}/evaluate", handle_collection_evaluate, policy=RoutePolicy(capabilities=_BROWSE))
    _add(app, "GET", "/api/search", handle_search, policy=_BROWSE_RATE)
    _add(app, "GET", "/api/quicksearch", handle_quicksearch, policy=_BROWSE_RATE)
    _add(app, "GET", "/api/meta/{path:.*}", handle_meta)
    # Frame-sequence neighbor lookup: read-only, PathGuard-confined, browse
    # capability like the other read surfaces (rate limit stays on the
    # general tier, matching the frozen golden policy contract).
    _add(app, "GET", "/api/sequence/neighbors", handle_sequence_neighbors,
         policy=RoutePolicy(capabilities=_BROWSE))
    _add(app, "PUT", "/api/notes/{path:.*}", handle_save_notes, policy=_WRITE_NOTES_BROWSE)
    _add(app, "PUT", "/api/rating/{path:.*}", handle_save_rating, policy=_WRITE_NOTES_BROWSE)
    _add(app, "GET", "/api/info", handle_info, policy=_OPTIONAL_BROWSE)
    _add(app, "GET", "/api/revision", handle_revision, policy=_SKIP)
    _add(app, "POST", "/api/auth/login", handle_login, policy=_PUBLIC_AUTH_STRICT_CAP)
    _add(app, "POST", "/api/auth/register", handle_register, policy=_PUBLIC_AUTH_STRICT_CAP)
    _add(app, "POST", "/api/auth/verify_key", handle_verify_key, policy=_PUBLIC_AUTH_STRICT_CAP)
    _add(app, "POST", "/api/auth/logout", handle_logout, policy=_AUTH_BOOTSTRAP)
    _add(app, "GET", "/api/auth/me", handle_me)
    _add(app, "GET", "/api/users", handle_users, policy=_ADMIN_USER)
    _add(app, "POST", "/api/users/{id}/toggle", handle_toggle_user, policy=_ADMIN_USER)
    _add(app, "PATCH", "/api/users/{username}", handle_update_user, policy=_ADMIN_USER)
    _add(app, "GET", "/api/invites", handle_invites, policy=_ADMIN_USER)
    _add(app, "POST", "/api/invites", handle_create_invite, policy=_ADMIN_USER)
    _add(app, "POST", "/api/invites/{code}/revoke", handle_revoke_invite, policy=_ADMIN_USER)
    _add(app, "GET", "/api/activity", handle_activity, policy=_ADMIN_USER_BROWSE)
    _add(app, "GET", "/api/online-users", handle_online_users, policy=_ADMIN_USER)
    _add(app, "GET", "/api/tunnel/status", handle_tunnel_status, policy=_SETTINGS_BROWSE)
    _add(app, "GET", "/api/stats", handle_stats, policy=RoutePolicy(rate_limit="skip", capabilities=_SETTINGS))
    _add(app, "POST", "/api/shares", handle_create_share, policy=_LINK_WRITE)
    _add(app, "GET", "/api/shares", handle_list_shares)
    _add(app, "DELETE", "/api/shares/{id}", handle_delete_share, policy=_LINK_WRITE)
    _add(app, "GET", "/s/{id}", handle_share_page, policy=_PUBLIC)
    # Share endpoints are method-scoped to match the historical shape logic:
    # the pattern stays auth_strict/required for any other method (HEAD, 405).
    _add(app, "POST", "/api/shares/{id}/verify", handle_verify_share_password, policy=_AUTH_STRICT)
    declare(app, "/api/shares/{id}/verify", _SHARE_VERIFY_PUBLIC, method="POST")
    _add(app, "GET", "/api/shares/{id}/download/{path:.*}", handle_share_download)
    declare(app, "/api/shares/{id}/download/{path:.*}", _PUBLIC, method="GET")
    _add(app, "GET", "/api/shares/{id}/preview/{path:.*}", handle_share_preview)
    declare(app, "/api/shares/{id}/preview/{path:.*}", _PUBLIC, method="GET")
    _add(app, "GET", "/api/shares/{id}/info", handle_share_info)
    declare(app, "/api/shares/{id}/info", _PUBLIC, method="GET")
    _add(app, "GET", "/api/quota", handle_free_quota, policy=_PUBLIC_BROWSE)
    _add(app, "GET", "/ws", handle_websocket, policy=_SKIP)

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
        declare(app, "/assets", _PUBLIC_SKIP)
