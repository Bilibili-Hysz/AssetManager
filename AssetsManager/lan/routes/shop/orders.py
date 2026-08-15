"""Seller order lifecycle: create, confirm, fulfill, revoke, stats, export."""
from __future__ import annotations

from aiohttp import web

from AssetsManager.lan.routes.commerce_policy import (
    seller_gate,
    seller_required,
)
from AssetsManager.lan.routes.shop._common import (
    _buyer_response,
    _error_response,
    _get_order_receipt,
    _order_limit,
    _package_function,
    _set_order_receipt_cookie,
    _store_not_accepting_orders_response,
)


async def handle_shop_order(request: web.Request) -> web.Response:
    order_id = request.match_info.get("order_id") or request.query.get(
        "id", request.query.get("order_id", "")
    )
    disabled = _package_function("commerce_gate")() if request.method == "POST" or order_id else seller_gate()
    if disabled is not None:
        return disabled
    try:
        lan = _package_function("get_lan")(request)
        if request.method == "POST":
            # Seller profile is the authoritative store availability setting.
            # Import lazily to avoid the seller-profile route's seller-auth helper
            # creating an import cycle while this module is initialized.
            from AssetsManager.lan.routes.seller_profile import get_seller_profile_service

            profile_service = get_seller_profile_service(request)

            def store_is_paused() -> bool:
                return not bool(profile_service.get_profile(lan.library_root)["accept_orders"])

            # Fail fast for already-paused stores, before accepting a potentially
            # slow request body.  Recheck after parsing so a pause that occurs
            # while the body is arriving cannot create an order from stale state.
            if store_is_paused():
                return _store_not_accepting_orders_response()
            body = await _package_function("_json_body")(request)
            owner, uid, guest, cookie_response = _package_function("_buyer_owner")(request)
            if store_is_paused():
                return _store_not_accepting_orders_response()
            # The receipt plaintext only reaches the HttpOnly cookie below.
            # Delivery quota is still enforced atomically by OrderService.
            order, receipt = _package_function("get_commerce_services")(request).orders.create_order_with_receipt(
                lan.library_root,
                body,
                require_accepting_orders=True,
                buyer_owner_type=owner,
                buyer_owner_key=str(uid) if owner == "user" else guest,
            )
            response = _buyer_response(
                {"order": order}, status=201, cookie=cookie_response, request=request
            )
            response.headers["Cache-Control"] = "no-store"
            _set_order_receipt_cookie(response, request, order["id"], receipt)
            return response
        if not order_id:
            # Do not resolve any Commerce service before seller authorization;
            # unauthenticated order listings must stay a cheap 403.
            if await _package_function("require_seller")(request) is None:
                return _error_response("Seller authentication required", status=403, code="forbidden")
            status = request.query.get("status")
            limit = _order_limit(request)
            orders = _package_function("get_commerce_services")(request).orders
            return web.json_response({"orders": orders.list_seller_orders(
                lan.library_root, status=status, limit=limit
            )})

        # A seller may inspect the seller DTO. Everyone else must possess the
        # receipt scoped to this exact order; missing/wrong receipts resolve as
        # 404 so numeric order identifiers cannot be enumerated.
        orders = _package_function("get_commerce_services")(request).orders
        if await _package_function("require_seller")(request) is not None:
            order = orders.get_seller_order(lan.library_root, order_id)
        else:
            order = orders.get_order_by_receipt(
                lan.library_root, order_id, _get_order_receipt(request, order_id)
            )
        return web.json_response({"order": order}, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return _error_response(exc)


async def _order_action(request: web.Request, action: str) -> web.Response:
    # Buyer confirmation is explicitly receipt-authorized. Fulfillment and
    # revocation remain seller-only mutations.
    disabled = _package_function("commerce_gate")() if action == "confirm" else seller_gate()
    if disabled is not None:
        return disabled
    if action != "confirm" and await _package_function("require_seller")(request) is None:
        return _error_response("Seller authentication required", status=403, code="forbidden")
    lan = _package_function("get_lan")(request)
    service = _package_function("get_commerce_services")(request).orders
    order_id = request.match_info["order_id"]
    try:
        if action == "confirm":
            order = service.confirm_by_receipt(
                lan.library_root, order_id, _get_order_receipt(request, order_id)
            )
            return web.json_response({"order": order}, headers={"Cache-Control": "no-store"})
        if action == "revoke":
            order = service.revoke(lan.library_root, order_id)
            return web.json_response({"order": order})
        body = await _package_function("_json_body")(request) if (request.can_read_body and (request.content_length or 0) > 0) else {}
        order, token, share_claim = service.fulfill(
            lan.library_root,
            order_id,
            max_downloads=body.get("max_downloads", 3),
            expires_in=body.get("expires_in", 7 * 24 * 60 * 60),
        )
        return web.json_response({
            "order": order,
            "delivery_token": token,
            "share_claim": share_claim,
            "delivery_url": f"/api/shop/delivery/{order_id}",
        })
    except Exception as exc:
        return _error_response(exc)


async def handle_order_confirm(request: web.Request) -> web.Response:
    return await _order_action(request, "confirm")


async def handle_order_fulfill(request: web.Request) -> web.Response:
    return await _order_action(request, "fulfill")


async def handle_order_revoke(request: web.Request) -> web.Response:
    return await _order_action(request, "revoke")


@seller_required
async def handle_order_stats(request: web.Request) -> web.Response:
    if await _package_function("require_seller")(request) is None:
        return _error_response("Seller authentication required", status=403, code="forbidden")
    try:
        lan = _package_function("get_lan")(request)
        stats = _package_function("get_commerce_services")(request).orders.stats(lan.library_root)
        # Analytics is additive to the established order stats contract.  A
        # temporary analytics failure must not hide valid seller revenue data.
        try:
            from AssetsManager.lan.routes.storefront_analytics import get_storefront_analytics_service

            stats.update(get_storefront_analytics_service(request).stats(lan.library_root))
        except Exception:
            pass
        return web.json_response({"stats": stats})
    except Exception as exc:
        return _error_response(exc)


@seller_required
async def handle_order_export(request: web.Request) -> web.Response:
    if await _package_function("require_seller")(request) is None:
        return _error_response("Seller authentication required", status=403, code="forbidden")
    try:
        content = _package_function("get_commerce_services")(request).orders.export_csv(_package_function("get_lan")(request).library_root)
        return web.Response(
            text=content,
            content_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="orders.csv"', "Cache-Control": "no-store"},
        )
    except Exception as exc:
        return _error_response(exc)
