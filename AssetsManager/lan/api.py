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
    handle_gallery_page,
    handle_gallery_collection_page,
    handle_gallery_favorites_page,
    handle_storefront_page,
    handle_seller_page,
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
    handle_search,
    handle_meta,
    handle_save_notes,
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
    handle_public_shop_item,
    handle_public_shop_catalog,
    handle_public_shop_item_by_path,
    handle_public_shop_item_media,
    handle_shop_items,
    handle_shop_order,
    handle_shop_buyer_orders,
    handle_shop_buyer_merge,
    handle_order_receipt_recover,
    handle_shop_cart,
    handle_shop_cart_checkout,
    handle_shop_cart_checkout_group,
    handle_shop_wishlist,
    handle_order_confirm,
    handle_order_fulfill,
    handle_order_delivery_rotate,
    handle_order_delivery_revoke,
    handle_order_revoke,
    handle_order_stats,
    handle_order_export,
    handle_delivery,
    handle_order_delivery,
    handle_delivery_download,
    handle_shop_claim_delivery,
    handle_delivery_quota,
    handle_free_quota,
    handle_seller_status,
    handle_seller_login,
    handle_seller_logout,
)
from AssetsManager.lan.routes.image import handle_image
from AssetsManager.lan.routes.quicksearch import handle_quicksearch
from AssetsManager.lan.routes.seller_profile import handle_public_seller_profile, handle_seller_profile
from AssetsManager.lan.routes.storefront_analytics import handle_storefront_view
from AssetsManager.lan.routes.commerce_policy import seller_required
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
    app.router.add_get("/gallery", handle_gallery_page)
    app.router.add_get("/gallery/collection", handle_gallery_collection_page)
    app.router.add_get("/gallery/favorites", handle_gallery_favorites_page)
    app.router.add_get("/storefront", handle_storefront_page)
    app.router.add_get("/storefront/products", handle_storefront_page)
    app.router.add_get("/storefront/cart", handle_storefront_page)
    app.router.add_get("/storefront/orders", handle_storefront_page)
    app.router.add_get("/storefront/wishlist", handle_storefront_page)
    app.router.add_get("/storefront/product/{id}", handle_storefront_page)
    app.router.add_get("/storefront/product/path/{item_path:.*}", handle_storefront_page)
    app.router.add_get("/storefront/checkout/group", handle_storefront_page)
    app.router.add_get("/storefront/checkout/{order_id}", handle_storefront_page)
    app.router.add_get("/storefront/delivery/{token}", handle_storefront_page)
    app.router.add_get("/seller", handle_seller_page)
    app.router.add_get("/seller/products", handle_seller_page)
    app.router.add_get("/seller/products/{id}", handle_seller_page)
    app.router.add_get("/seller/orders", handle_seller_page)
    app.router.add_get("/seller/settings", handle_seller_page)
    # Keep deep links from the reference WebUI serving the SPA as well. The
    # React router performs the canonical redirect; these server routes only
    # prevent a direct browser refresh from falling through to a 404.
    app.router.add_get("/store", handle_storefront_page)
    app.router.add_get("/store/gallery/{tag}", handle_storefront_page)
    app.router.add_get("/store/checkout", handle_storefront_page)
    app.router.add_get("/store/delivery/{token}", handle_storefront_page)
    app.router.add_get("/store/{item_path:.*}", handle_storefront_page)
    app.router.add_get("/app", handle_seller_page)
    app.router.add_get("/app/items", handle_seller_page)
    app.router.add_get("/app/orders", handle_seller_page)
    app.router.add_get("/api/gallery/home", handle_gallery_home)
    app.router.add_get("/api/gallery/collection", handle_gallery_collection)
    app.router.add_get("/api/gallery/resolve", handle_gallery_resolve)
    app.router.add_get("/api/image", handle_image)
    app.router.add_get("/api/favorites", handle_favorites)
    app.router.add_post("/api/favorites", handle_add_favorite)
    app.router.add_post("/api/favorites/remove", handle_remove_favorite)
    app.router.add_delete("/api/favorites", handle_remove_favorite)
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
    app.router.add_post("/api/tags/remove", handle_remove_tag)
    app.router.add_get("/api/search", handle_search)
    app.router.add_get("/api/quicksearch", handle_quicksearch)
    app.router.add_get("/api/meta/{path:.*}", handle_meta)
    app.router.add_put("/api/notes/{path:.*}", handle_save_notes)
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
    # Commerce contract endpoints (keep legacy singular aliases below).
    app.router.add_get("/api/shop/cart", handle_shop_cart)
    app.router.add_post("/api/shop/cart/items", handle_shop_cart)
    app.router.add_patch("/api/shop/cart/items/{line_id}", handle_shop_cart)
    app.router.add_delete("/api/shop/cart/items/{line_id}", handle_shop_cart)
    app.router.add_delete("/api/shop/cart/items", handle_shop_cart)
    app.router.add_post("/api/shop/cart/checkout", handle_shop_cart_checkout)
    app.router.add_get(
        "/api/shop/cart/checkout/{checkout_group_id}",
        handle_shop_cart_checkout_group,
    )
    app.router.add_get("/api/shop/wishlist", handle_shop_wishlist)
    app.router.add_put("/api/shop/wishlist/items/{item_id}", handle_shop_wishlist)
    app.router.add_delete("/api/shop/wishlist/items/{item_id}", handle_shop_wishlist)
    app.router.add_delete("/api/shop/wishlist", handle_shop_wishlist)
    app.router.add_get("/api/shop/catalog", handle_public_shop_catalog)
    app.router.add_get("/api/shop/items", handle_shop_items)
    app.router.add_get("/api/shop/items/by-path", handle_public_shop_item_by_path)
    app.router.add_get("/api/shop/items/{item_id}/media/{slot}", handle_public_shop_item_media)
    app.router.add_get("/api/shop/items/{item_id}", handle_public_shop_item)
    app.router.add_get("/api/shop/profile", handle_public_seller_profile)
    app.router.add_get("/api/shop/seller-profile", handle_seller_profile)
    app.router.add_put("/api/shop/seller-profile", handle_seller_profile)
    app.router.add_post("/api/shop/analytics/store-view", handle_storefront_view)
    app.router.add_post("/api/shop/items", handle_shop_items)
    app.router.add_put("/api/shop/items", handle_shop_items)
    app.router.add_delete("/api/shop/items", handle_shop_items)
    app.router.add_get("/api/shop/orders/order", handle_shop_order)
    app.router.add_post("/api/shop/orders/order", handle_shop_order)
    app.router.add_post("/api/shop/orders/order/{order_id}/confirm", handle_order_confirm)
    app.router.add_post("/api/shop/orders/order/{order_id}/fulfill", handle_order_fulfill)
    app.router.add_post("/api/shop/orders/order/{order_id}/revoke", handle_order_revoke)
    app.router.add_post(
        "/api/shop/orders/order/{order_id}/delivery/revoke",
        handle_order_delivery_revoke,
    )
    app.router.add_get("/api/shop/orders/stats", handle_order_stats)
    app.router.add_get("/api/shop/quota", seller_required(handle_delivery_quota))
    app.router.add_get("/api/shop/auth/seller-status", handle_seller_status)
    app.router.add_post("/api/shop/auth/login", handle_seller_login)
    app.router.add_post("/api/shop/auth/logout", handle_seller_logout)
    app.router.add_put("/api/shop/items/{item_id}", handle_shop_items)
    app.router.add_delete("/api/shop/items/{item_id}", handle_shop_items)
    app.router.add_post("/api/shop/order", handle_shop_order)
    app.router.add_get("/api/shop/order/{order_id}/delivery", handle_order_delivery, allow_head=False)
    app.router.add_get("/api/shop/order/{order_id}", handle_shop_order)
    app.router.add_get("/api/shop/orders", handle_shop_order)
    app.router.add_get("/api/shop/buyer/orders", handle_shop_buyer_orders)
    app.router.add_post("/api/shop/buyer/merge", handle_shop_buyer_merge)
    app.router.add_post("/api/shop/order/{order_id}/receipt/recover", handle_order_receipt_recover)
    app.router.add_post("/api/shop/order/{order_id}/confirm", handle_order_confirm)
    app.router.add_post("/api/shop/order/{order_id}/fulfill", handle_order_fulfill)
    app.router.add_post("/api/shop/order/{order_id}/delivery/rotate", handle_order_delivery_rotate)
    app.router.add_post("/api/shop/order/{order_id}/delivery/revoke", handle_order_delivery_revoke)
    app.router.add_post("/api/shop/order/{order_id}/revoke", handle_order_revoke)
    app.router.add_get("/api/shop/stats", handle_order_stats)
    app.router.add_get("/api/shop/orders/export", handle_order_export)
    app.router.add_get("/api/shop/delivery/{token}", handle_delivery)
    app.router.add_get("/api/shop/delivery/{token}/download", handle_delivery_download, allow_head=False)
    app.router.add_post("/api/shop/delivery/{order_id}/claim", handle_shop_claim_delivery)
    app.router.add_get("/api/auth/seller-status", handle_seller_status)
    app.router.add_post("/api/auth/seller-login", handle_seller_login)
    app.router.add_post("/api/auth/seller-logout", handle_seller_logout)
    app.router.add_get("/api/quota", handle_free_quota)
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
