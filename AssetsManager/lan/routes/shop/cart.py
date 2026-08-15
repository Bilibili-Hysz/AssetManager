"""Buyer-facing cart, wishlist, and order-history HTTP routes."""
from __future__ import annotations

from aiohttp import web

from AssetsManager.application.shop_buyer_service import token_hash
from AssetsManager.domain.errors import NotFoundError, ValidationError
from AssetsManager.lan.routes._helpers import get_request_principal
from AssetsManager.lan.routes.commerce_policy import commerce_required
from AssetsManager.lan.routes.shop._common import (
    _buyer_response,
    _buyer_service,
    _error_response,
    _order_limit,
    _package_function,
    _set_order_receipt_cookie,
)


@commerce_required
async def handle_shop_buyer_orders(request: web.Request) -> web.Response:
    """Return history for the current buyer owner only."""
    try:
        owner, uid, guest, cookie_response = _package_function("_buyer_owner")(request)
        orders, next_cursor = _package_function("get_commerce_services")(request).orders.list_buyer_orders(
            _package_function("get_lan")(request).library_root,
            owner_type=owner,
            owner_key=str(uid) if owner == "user" else str(guest),
            status=request.query.get("status"),
            limit=_order_limit(request),
            cursor=request.query.get("cursor"),
        )
        payload: dict[str, object] = {"orders": orders}
        if next_cursor is not None:
            payload["next_cursor"] = next_cursor
        return _buyer_response(payload, cookie=cookie_response, request=request)
    except Exception as exc:
        return _error_response(exc)

@commerce_required
async def handle_order_receipt_recover(request: web.Request) -> web.Response:
    """Restore an order receipt cookie without returning the credential in JSON."""
    order_id = request.match_info["order_id"]
    try:
        owner, uid, guest, _cookie_response = _package_function("_buyer_owner")(request)
        owner_key = str(uid) if owner == "user" else str(guest or "")
        if owner == "anonymous" and not guest:
            raise NotFoundError("order receipt", str(order_id))
        token = _package_function("get_commerce_services")(request).orders.recover_receipt_for_owner(
            _package_function("get_lan")(request).library_root,
            order_id,
            owner_type=owner,
            owner_key=owner_key,
        )
        response = _buyer_response(
            {"ok": True, "order_id": int(order_id)},
            request=request,
        )
        _set_order_receipt_cookie(response, request, order_id, token)
        return response
    except Exception as exc:
        return _error_response(exc)


@commerce_required
async def handle_shop_buyer_merge(request: web.Request) -> web.Response:
    """Merge the current guest browser state into the authenticated buyer."""
    principal = get_request_principal(request)
    profile = getattr(principal, "user_profile", None) if principal is not None else None
    if (
        principal is None
        or getattr(principal, "kind", None) != "user"
        or not getattr(principal, "authenticated", False)
        or not isinstance(profile, dict)
    ):
        return _error_response(
            "authenticated user required",
            status=403,
            code="authentication_required",
            headers={"Cache-Control": "private, no-store"},
        )
    try:
        user_id = int(profile.get("id", 0))
    except (TypeError, ValueError):
        user_id = 0
    if user_id <= 0:
        return _error_response(
            "authenticated user required",
            status=403,
            code="authentication_required",
            headers={"Cache-Control": "private, no-store"},
        )
    try:
        result = _buyer_service(request).merge_guest_into_user(
            _package_function("get_lan")(request).library_root,
            user_id=user_id,
            guest_cart_token_hash=(
                token_hash(request.cookies["shop_cart_token"])
                if request.cookies.get("shop_cart_token")
                else None
            ),
            guest_wishlist_token_hash=(
                token_hash(request.cookies["shop_wishlist_token"])
                if request.cookies.get("shop_wishlist_token")
                else None
            ),
        )
        return _buyer_response(result, request=request)
    except Exception as exc:
        return _error_response(exc)

@commerce_required
async def handle_shop_cart(request: web.Request) -> web.Response:
    try:
        owner, uid, guest, cookie_response = _package_function("_buyer_owner")(request)
        service = _buyer_service(request)
        lan = _package_function("get_lan")(request)
        if request.method == "GET":
            # A cart read is side-effect free: it must not materialize a
            # cart row, nor mint/issue a new guest token cookie.
            return _buyer_response(
                {
                    "cart": service.cart(
                        lan.library_root,
                        owner_kind=owner,
                        user_id=uid,
                        guest_token_hash=guest,
                    )
                },
                request=request,
            )
        body = await _package_function("_json_body")(request)
        if request.method == "POST":
            result = service.add_cart_item(
                lan.library_root,
                body.get("item_id", body.get("id")),
                body.get("quantity", 1),
                owner_kind=owner,
                user_id=uid,
                guest_token_hash=guest,
                expected_version=body.get("version"),
            )
            return _buyer_response(
                {"cart": result},
                status=201,
                cookie=cookie_response,
                request=request,
            )
        if request.method == "PATCH":
            result = service.update_cart_item(
                lan.library_root,
                request.match_info["line_id"],
                body.get("quantity"),
                owner_kind=owner,
                user_id=uid,
                guest_token_hash=guest,
                expected_version=body.get("version"),
            )
            return _buyer_response(
                {"cart": result}, cookie=cookie_response, request=request
            )
        if request.method == "DELETE":
            result = service.remove_cart_item(
                lan.library_root,
                owner_kind=owner,
                user_id=uid,
                guest_token_hash=guest,
                line_id=request.match_info.get("line_id"),
                item_id=body.get("item_id"),
                expected_version=body.get("version"),
            )
            return _buyer_response(
                {"cart": result}, cookie=cookie_response, request=request
            )
        raise ValidationError("method","unsupported")
    except Exception as exc:
        return _error_response(exc)

@commerce_required
async def handle_shop_cart_checkout(request: web.Request) -> web.Response:
    try:
        body = await _package_function("_json_body")(request)
        owner, uid, guest, cookie_response = _package_function("_buyer_owner")(request)
        header_key = request.headers.get("Idempotency-Key")
        body_key = body.get("idempotency_key")
        if header_key is not None and body_key is not None and str(header_key) != str(body_key):
            raise ValidationError("idempotency_key", "header and body values must match")
        key = header_key or body_key
        result = _buyer_service(request).checkout(
            _package_function("get_lan")(request).library_root,
            owner_kind=owner,
            user_id=uid,
            guest_token_hash=guest,
            request_key=str(key or ""),
            accept_price_changes=body.get("accept_price_changes", False) is True,
            buyer_name=body.get("buyer_name"),
            buyer_email=body.get("buyer_email"),
        )
        receipt_tokens = result.pop("receipt_tokens", {})
        response = _buyer_response(
            result,
            status=201,
            cookie=cookie_response,
            request=request,
        )
        if isinstance(receipt_tokens, dict):
            for order_id, receipt in receipt_tokens.items():
                try:
                    _set_order_receipt_cookie(response, request, order_id, receipt)
                except (TypeError, ValueError):
                    continue
        return response
    except Exception as exc:
        return _error_response(exc)

@commerce_required
async def handle_shop_cart_checkout_group(request: web.Request) -> web.Response:
    try:
        owner, uid, guest, cookie_response = _package_function("_buyer_owner")(request)
        result = _buyer_service(request).checkout_group(
            _package_function("get_lan")(request).library_root,
            request.match_info["checkout_group_id"],
            owner_kind=owner,
            user_id=uid,
            guest_token_hash=guest,
        )
        return _buyer_response(
            result,
            cookie=cookie_response,
            request=request,
        )
    except Exception as exc:
        return _error_response(exc)

@commerce_required
async def handle_shop_wishlist(request: web.Request) -> web.Response:
    try:
        owner, uid, guest, cookie_response = _package_function("_buyer_owner")(request, wishlist=True)
        service = _buyer_service(request)
        root = _package_function("get_lan")(request).library_root
        if request.method == "GET":
            # A wishlist read must not mint/issue a new guest token cookie.
            cookie_response = None
            result = service.wishlist(
                root,
                owner_kind=owner,
                user_id=uid,
                guest_token_hash=guest,
            )
        elif request.method == "PUT":
            result = service.wishlist_put(
                root,
                request.match_info["item_id"],
                owner_kind=owner,
                user_id=uid,
                guest_token_hash=guest,
            )
        elif request.method == "DELETE":
            result = service.wishlist_delete(
                root,
                request.match_info.get("item_id"),
                owner_kind=owner,
                user_id=uid,
                guest_token_hash=guest,
            )
        else:
            raise ValidationError("method", "unsupported")
        return _buyer_response(
            {"items": result},
            status=201 if request.method == "PUT" else 200,
            cookie=cookie_response,
            request=request,
        )
    except Exception as exc:
        return _error_response(exc)
