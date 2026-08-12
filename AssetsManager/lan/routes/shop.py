"""Commerce catalog and order HTTP routes."""
from __future__ import annotations

from dataclasses import dataclass
import logging
import math
from pathlib import Path
import time
from typing import Any, Callable

from aiohttp import web

from AssetsManager.application.order_service import DEFAULT_RECEIPT_TTL, OrderService
from AssetsManager.application.quota_service import QuotaService
from AssetsManager.application.seller_auth_service import SellerAuthService
from AssetsManager.application.shop_authorization import (
    UnauthorizedShopPathError,
)
from AssetsManager.application.shop_service import ShopService
from AssetsManager.application.shop_buyer_service import ShopBuyerService, new_guest_token, token_hash
from AssetsManager.domain.errors import (
    DeliveryPreparationError,
    MissingPathError,
    NotFoundError,
    OperationNotPermitted,
    PathEscapeError,
    ValidationError,
)
from AssetsManager.lan.routes._helpers import get_lan, get_request_principal
from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.routes.image import serve_verified_image
from AssetsManager.lan.routes.commerce_policy import (
    commerce_gate,
    commerce_required,
    seller_gate,
    seller_is_enabled,
    seller_required,
)


_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommerceServices:
    shop: ShopService
    orders: OrderService
    quota: QuotaService
    seller_auth: SellerAuthService
    buyer: ShopBuyerService | None = None


def get_commerce_services(request: web.Request) -> CommerceServices:
    """Resolve injected commerce services or lazily bind them to this LAN instance."""
    lan = get_lan(request)
    existing = getattr(lan, "commerce_services", None)
    if existing is not None:
        return existing
    scoped = getattr(lan, "services", None)
    if scoped is not None and all(
        getattr(scoped, name, None) is not None
        for name in ("shop_service", "order_service", "quota_service", "seller_auth_service")
    ):
        return CommerceServices(
            scoped.shop_service,
            scoped.order_service,
            scoped.quota_service,
            scoped.seller_auth_service,
            getattr(scoped, "shop_buyer_service", None),
        )
    provider = getattr(lan, "connection_for", None)
    session = getattr(getattr(scoped, "runtime_services", None), "session", None)
    auth_service = getattr(scoped, "auth_service", None)
    if auth_service is None:
        auth_service = getattr(lan, "_auth_service", None)
    if auth_service is None:
        raise RuntimeError("Commerce seller authentication requires AuthService")
    services = CommerceServices(
        ShopService(provider, session),
        OrderService(provider, session),
        QuotaService(provider, session),
        SellerAuthService(auth_service),
        ShopBuyerService(provider, session),
    )
    # LAN instances are mutable lifecycle adapters; caching avoids constructing
    # four service wrappers for every request without changing frozen snapshots.
    lan.commerce_services = services
    return services


def _store_not_accepting_orders_response() -> web.Response:
    return web.json_response(
        {
            "error": "This store is not accepting new orders",
            "code": "store_not_accepting_orders",
        },
        status=503,
        headers={"Cache-Control": "no-store"},
    )


def _catalog_query_value(request: web.Request, field: str, default: str | None = None) -> str | None:
    values = request.query.getall(field, [])
    if len(values) > 1:
        raise ValidationError(field, "must be provided once")
    return values[0] if values else default


# Canonical Commerce error contract lives in routes/_errors.py; the local
# name is kept for this module's 25 call sites and the contract tests.
_error_response = error_response


async def _json_body(request: web.Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:
        raise ValidationError("body", "invalid JSON") from exc
    if not isinstance(body, dict):
        raise ValidationError("body", "must be an object")
    return body


def _item_id(request: web.Request, body: dict[str, Any] | None = None) -> int:
    value = (body or {}).get("id", (body or {}).get("item_id"))
    if value is None:
        value = request.match_info.get("item_id")
    if value is None:
        value = request.query.get("id", request.query.get("item_id"))
    if value is None:
        raise ValidationError("item_id", "must be an integer")
    try:
        item_id = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("item_id", "must be an integer") from exc
    if item_id <= 0:
        raise ValidationError("item_id", "must be positive")
    return item_id


def _order_limit(request: web.Request) -> int:
    raw_limit = request.query.get("limit", "200")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError) as exc:
        raise ValidationError("limit", "must be an integer between 1 and 1000") from exc
    if limit < 1 or limit > 1000:
        raise ValidationError("limit", "must be an integer between 1 and 1000")
    return limit


ORDER_RECEIPT_COOKIE_PREFIX = "shop_order_receipt_"


def _receipt_cookie_name(order_id: int | str) -> str:
    """Return a path-safe receipt cookie name for a positive order ID."""
    try:
        parsed = int(order_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("order_id must be a positive integer") from exc
    if parsed <= 0:
        raise ValueError("order_id must be a positive integer")
    return f"{ORDER_RECEIPT_COOKIE_PREFIX}{parsed}"


def _get_order_receipt(request: web.Request, order_id: int | str) -> str:
    try:
        cookie_name = _receipt_cookie_name(order_id)
    except ValueError:
        return ""
    return request.cookies.get(cookie_name, "")


def _delivery_request_key(request: web.Request) -> str | None:
    """Read the optional request-level idempotency key for a download."""
    if "Idempotency-Key" not in request.headers:
        return None
    value = request.headers.get("Idempotency-Key", "").strip()
    if not value or len(value) > 200:
        raise ValidationError("idempotency_key", "must be 1-200 characters")
    return value


def _set_order_receipt_cookie(
    response: web.Response,
    request: web.Request,
    order_id: int | str,
    receipt: str,
) -> None:
    """Store an order-scoped receipt without exposing it in JSON or URLs."""
    parsed_order_id = int(order_id)
    if parsed_order_id <= 0:
        raise ValueError("order_id must be a positive integer")
    response.set_cookie(
        _receipt_cookie_name(parsed_order_id),
        receipt,
        httponly=True,
        secure=bool(request.secure),
        samesite="Lax",
        # The receipt is still named per order; the shared path is required so
        # both the legacy singular and new plural WebUI routes receive it.
        path="/api/shop",
        max_age=DEFAULT_RECEIPT_TTL,
    )


def _principal_can_manage(request: web.Request) -> bool:
    principal = get_request_principal(request)
    if principal is None or not principal.authenticated:
        return False
    capabilities = principal.capabilities
    return bool(capabilities.settings or capabilities.manage_links)


async def require_seller(request: web.Request) -> dict[str, Any] | None:
    # Feature policy is authoritative over both stale LAN principals and stale
    # seller-session cookies, and must be checked before either is inspected.
    if not seller_is_enabled():
        return None
    if _principal_can_manage(request):
        principal = get_request_principal(request)
        if principal is None:
            return None
        return {"kind": "principal", "name": principal.display_name}
    token = request.cookies.get("seller_session", "")
    if not token:
        return None
    services = get_commerce_services(request)
    return services.seller_auth.authenticate(token)


async def handle_shop_items(request: web.Request) -> web.Response:
    disabled = commerce_gate() if request.method == "GET" else seller_gate()
    if disabled is not None:
        return disabled
    lan = get_lan(request)
    services = get_commerce_services(request)
    try:
        if request.method == "GET":
            seller = await require_seller(request)
            requested_status = request.query.get("status")
            if requested_status is not None:
                requested_status = requested_status.strip().lower()
                if requested_status not in {"active", "draft", "archived"}:
                    raise ValidationError("status", "must be active, archived, or draft")
            # Public catalog responses are always active. Sellers retain the
            # legacy include_disabled gate for non-active catalog states.
            include_disabled = seller is not None and request.query.get("include_disabled") in {"1", "true"}
            list_kwargs = {
                "include_disabled": include_disabled,
                "status": requested_status if seller is not None else "active",
            }
            return web.json_response({"items": services.shop.list_items(
                lan.library_root, **list_kwargs
            )})
        seller = await require_seller(request)
        if seller is None:
            return web.json_response({"error": "Seller authentication required"}, status=403)
        body = await _json_body(request) if (request.can_read_body and (request.content_length or 0) > 0) else {}
        if request.method == "POST":
            item = services.shop.create_item(lan.library_root, body)
            return web.json_response({"item": item}, status=201)
        item_id = _item_id(request, body)
        if request.method == "PUT":
            item = services.shop.update_item(lan.library_root, item_id, body)
            return web.json_response({"item": item})
        deleted = services.shop.delete_item(lan.library_root, item_id)
        return web.json_response({"ok": deleted})
    except Exception as exc:
        return _error_response(exc)


async def handle_public_shop_catalog(request: web.Request) -> web.Response:
    """Serve a paginated public Commerce catalog without seller authentication."""
    disabled = commerce_gate()
    if disabled is not None:
        return disabled
    try:
        lan = get_lan(request)
        services = get_commerce_services(request)
        q = _catalog_query_value(request, "q")
        raw_page = _catalog_query_value(request, "page", "1")
        raw_page_size = _catalog_query_value(request, "page_size", "24")
        sort = _catalog_query_value(request, "sort", "newest")
        try:
            page = int(raw_page if raw_page is not None else "1")
        except (TypeError, ValueError) as exc:
            raise ValidationError("page", "must be an integer") from exc
        try:
            page_size = int(raw_page_size if raw_page_size is not None else "24")
        except (TypeError, ValueError) as exc:
            raise ValidationError("page_size", "must be an integer") from exc
        catalog = services.shop.list_catalog(
            lan.library_root,
            q=q,
            page=page,
            page_size=page_size,
            sort=sort,
        )
        return web.json_response(catalog)
    except Exception as exc:
        return _error_response(exc)

async def handle_public_shop_item(request: web.Request) -> web.Response:
    """Serve one active Commerce item without requiring seller authentication."""
    disabled = commerce_gate()
    if disabled is not None:
        return disabled
    try:
        lan = get_lan(request)
        services = get_commerce_services(request)
        item = services.shop.get_public_item(lan.library_root, _item_id(request))
        return web.json_response({"item": item})
    except Exception as exc:
        return _error_response(exc)


async def handle_public_shop_item_by_path(request: web.Request) -> web.Response:
    """Serve one active Commerce item addressed by its relative library path."""
    disabled = commerce_gate()
    if disabled is not None:
        return disabled
    try:
        lan = get_lan(request)
        services = get_commerce_services(request)
        item = services.shop.get_public_item_by_path(
            lan.library_root, request.query.get("path")
        )
        return web.json_response({"item": item})
    except Exception as exc:
        return _error_response(exc)


async def handle_public_shop_item_media(request: web.Request) -> web.StreamResponse:
    """Serve only the selected media slot of an active public Commerce item."""
    disabled = commerce_gate()
    if disabled is not None:
        return disabled
    try:
        lan = get_lan(request)
        services = get_commerce_services(request)
        item_id = _item_id(request)
        slot = request.match_info.get("slot", "")
        relative = services.shop.get_public_item_media_path(lan.library_root, item_id, slot)
        try:
            size = min(max(int(request.query.get("size", "512")), 16), 2048)
        except (TypeError, ValueError):
            size = 512
        root = Path(lan.library_root).resolve()
        target = (root / relative).resolve()
        if not target.is_relative_to(root):
            return web.Response(status=404)
        return await serve_verified_image(request, target, max_size=size, public=True)
    except Exception as exc:
        if isinstance(exc, (NotFoundError, MissingPathError, UnauthorizedShopPathError, ValueError, LookupError)):
            return web.Response(status=404)
        _log.exception("Public Commerce media delivery failed")
        return web.Response(status=404)


async def handle_shop_order(request: web.Request) -> web.Response:
    order_id = request.match_info.get("order_id") or request.query.get(
        "id", request.query.get("order_id", "")
    )
    disabled = commerce_gate() if request.method == "POST" or order_id else seller_gate()
    if disabled is not None:
        return disabled
    try:
        lan = get_lan(request)
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
            body = await _json_body(request)
            owner, uid, guest, cookie_response = _buyer_owner(request)
            if store_is_paused():
                return _store_not_accepting_orders_response()
            # The receipt plaintext only reaches the HttpOnly cookie below.
            # Delivery quota is still enforced atomically by OrderService.
            order, receipt = get_commerce_services(request).orders.create_order_with_receipt(
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
            if await require_seller(request) is None:
                return web.json_response({"error": "Seller authentication required"}, status=403)
            status = request.query.get("status")
            limit = _order_limit(request)
            orders = get_commerce_services(request).orders
            return web.json_response({"orders": orders.list_seller_orders(
                lan.library_root, status=status, limit=limit
            )})

        # A seller may inspect the seller DTO. Everyone else must possess the
        # receipt scoped to this exact order; missing/wrong receipts resolve as
        # 404 so numeric order identifiers cannot be enumerated.
        orders = get_commerce_services(request).orders
        if await require_seller(request) is not None:
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
    disabled = commerce_gate() if action == "confirm" else seller_gate()
    if disabled is not None:
        return disabled
    if action != "confirm" and await require_seller(request) is None:
        return web.json_response({"error": "Seller authentication required"}, status=403)
    lan = get_lan(request)
    service = get_commerce_services(request).orders
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
        body = await _json_body(request) if (request.can_read_body and (request.content_length or 0) > 0) else {}
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


async def handle_order_delivery_rotate(request: web.Request) -> web.Response:
    """Recover a lost seller delivery response without revoking old links."""
    disabled = seller_gate()
    if disabled is not None:
        return disabled
    if await require_seller(request) is None:
        return web.json_response({"error": "Seller authentication required"}, status=403)
    try:
        body = (
            await _json_body(request)
            if request.can_read_body and (request.content_length or 0) > 0
            else {}
        )
        order, token, share_claim = get_commerce_services(request).orders.rotate_delivery(
            get_lan(request).library_root,
            request.match_info["order_id"],
            max_downloads=body.get("max_downloads"),
            expires_in=body.get("expires_in"),
        )
        return web.json_response(
            {
                "order": order,
                "delivery_token": token,
                "share_claim": share_claim,
                "delivery_url": f"/api/shop/delivery/{request.match_info['order_id']}",
                "rotated": True,
            },
            headers={"Cache-Control": "no-store"},
        )
    except Exception as exc:
        return _error_response(exc)


# ── Share-claim delivery redemption ────────────────────────────
# The claim POST is bearer-free (the code itself is the credential), so it
# gets the same stricter per-IP failure throttling the security middleware
# applies to auth endpoints (10 failures / 5 minutes -> 429).  State is
# in-process only, matching the LAN middleware's memory-scoped limiters.
_CLAIM_MAX_FAILURES = 10
_CLAIM_WINDOW_SECONDS = 300

_claim_failures: dict[str, list[float]] = {}


def _claim_request_remote(request: web.Request) -> str:
    """Resolve the per-IP key used for share-claim brute-force limiting."""
    return str(getattr(request, "remote", "") or "")


def _claim_failures_for(remote: str, now: float) -> list[float]:
    """Return the recent failed-claim timestamps for one IP (pruning stale)."""
    recent = [
        ts for ts in _claim_failures.get(remote, []) if now - ts < _CLAIM_WINDOW_SECONDS
    ]
    if recent:
        _claim_failures[remote] = recent
    else:
        _claim_failures.pop(remote, None)
    return recent


def _claim_brute_force_allowed(remote: str, now: float) -> bool:
    return len(_claim_failures_for(remote, now)) < _CLAIM_MAX_FAILURES


def _claim_retry_after(remote: str, now: float) -> int:
    """Seconds until the oldest failure leaves the window (min 1)."""
    failures = _claim_failures_for(remote, now)
    if not failures:
        return _CLAIM_WINDOW_SECONDS
    return max(1, int(math.ceil(_CLAIM_WINDOW_SECONDS - (now - min(failures)))))


def _record_claim_failure(remote: str, now: float) -> None:
    _claim_failures_for(remote, now)  # prune stale entries first
    _claim_failures.setdefault(remote, []).append(now)


@commerce_required
async def handle_shop_claim_delivery(request: web.Request) -> web.Response:
    """Redeem a one-time share claim and bind the buyer receipt cookie.

    The claim is delivered over the credential-less delivery link
    (``delivery_url`` in the fulfill/rotate responses).  Every failure —
    unknown, already-used, revoked, or expired claim — answers a uniform 404
    so attackers cannot tell them apart; the redeemable credential itself
    only ever reaches the HttpOnly receipt cookie.
    """
    order_id = request.match_info["order_id"]
    remote = _claim_request_remote(request)
    now = time.time()
    if not _claim_brute_force_allowed(remote, now):
        retry_after = _claim_retry_after(remote, now)
        return web.json_response(
            {
                "error": "Too many claim attempts. Please try again later.",
                "retry_after": retry_after,
            },
            status=429,
            headers={"Retry-After": str(retry_after)},
        )
    try:
        body = await _json_body(request)
        claim = str(body.get("claim") or "").strip()
        if not claim:
            raise ValidationError("claim", "must not be empty")
        result = get_commerce_services(request).orders.claim_share_delivery(
            get_lan(request).library_root, order_id, claim
        )
        if result is None:
            _record_claim_failure(remote, time.time())
            raise NotFoundError("delivery", "claim")
        _claim_failures.pop(remote, None)
        _order, receipt = result
        response = _buyer_response({"ok": True}, request=request)
        _set_order_receipt_cookie(response, request, order_id, receipt)
        return response
    except Exception as exc:
        return _error_response(exc)


async def handle_order_delivery_revoke(request: web.Request) -> web.Response:
    """Revoke every delivery token of a fulfilled order (seller-only)."""
    disabled = seller_gate()
    if disabled is not None:
        return disabled
    seller = await require_seller(request)
    if seller is None:
        return web.json_response({"error": "Seller authentication required"}, status=403)
    try:
        order = get_commerce_services(request).orders.revoke_delivery(
            get_lan(request).library_root,
            request.match_info["order_id"],
            seller=seller,
        )
        return web.json_response(
            {"order": order, "revoked": True},
            headers={"Cache-Control": "no-store"},
        )
    except Exception as exc:
        return _error_response(exc)


async def handle_order_revoke(request: web.Request) -> web.Response:
    return await _order_action(request, "revoke")



def _buyer_service(request: web.Request) -> ShopBuyerService:
    services = get_commerce_services(request)
    return services.buyer or ShopBuyerService(getattr(get_lan(request), "connection_for", None), getattr(getattr(get_lan(request), "services", None), "runtime_services", None))

def _buyer_owner(
    request: web.Request,
    *,
    wishlist: bool = False,
) -> tuple[str, int | None, str | None, tuple[str, str] | None]:
    principal = get_request_principal(request)
    profile = getattr(principal, "user_profile", None) if principal is not None else None
    if (
        principal is not None
        and getattr(principal, "kind", None) == "user"
        and isinstance(profile, dict)
    ):
        return "user", int(profile.get("id", 0)), None, None
    cookie = "shop_wishlist_token" if wishlist else "shop_cart_token"
    token = request.cookies.get(cookie)
    if not token:
        token = new_guest_token()
        return "anonymous", None, token_hash(token), (cookie, token)
    return "anonymous", None, token_hash(token), None

def _buyer_response(
    payload: dict[str, Any],
    *,
    status: int = 200,
    cookie: tuple[str, str] | None = None,
    request: web.Request | None = None,
) -> web.Response:
    response = web.json_response(
        payload,
        status=status,
        headers={"Cache-Control": "private, no-store"},
    )
    if cookie is not None:
        name, value = cookie
        response.set_cookie(
            name,
            value,
            httponly=True,
            secure=bool(request.secure) if request is not None else False,
            samesite="Lax",
            # Use the root path so reverse-proxy/API base-path deployments
            # continue to send the token to the mounted API routes.
            path="/",
            max_age=60 * 60 * 24 * 365,
        )
    return response

@commerce_required
async def handle_shop_buyer_orders(request: web.Request) -> web.Response:
    """Return history for the current buyer owner only."""
    try:
        owner, uid, guest, cookie_response = _buyer_owner(request)
        orders, next_cursor = get_commerce_services(request).orders.list_buyer_orders(
            get_lan(request).library_root,
            owner_type=owner,
            owner_key=str(uid) if owner == "user" else str(guest),
            status=request.query.get("status"),
            limit=_order_limit(request),
            cursor=request.query.get("cursor"),
        )
        payload = {"orders": orders}
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
        owner, uid, guest, _cookie_response = _buyer_owner(request)
        owner_key = str(uid) if owner == "user" else str(guest or "")
        if owner == "anonymous" and not guest:
            raise NotFoundError("order receipt", str(order_id))
        token = get_commerce_services(request).orders.recover_receipt_for_owner(
            get_lan(request).library_root,
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
        return web.json_response(
            {"error": "authenticated user required", "code": "authentication_required"},
            status=403,
            headers={"Cache-Control": "private, no-store"},
        )
    try:
        user_id = int(profile.get("id", 0))
    except (TypeError, ValueError):
        user_id = 0
    if user_id <= 0:
        return web.json_response(
            {"error": "authenticated user required", "code": "authentication_required"},
            status=403,
            headers={"Cache-Control": "private, no-store"},
        )
    try:
        result = _buyer_service(request).merge_guest_into_user(
            get_lan(request).library_root,
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
        owner, uid, guest, cookie_response = _buyer_owner(request)
        service = _buyer_service(request)
        lan = get_lan(request)
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
        body = await _json_body(request)
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
        body = await _json_body(request)
        owner, uid, guest, cookie_response = _buyer_owner(request)
        header_key = request.headers.get("Idempotency-Key")
        body_key = body.get("idempotency_key")
        if header_key is not None and body_key is not None and str(header_key) != str(body_key):
            raise ValidationError("idempotency_key", "header and body values must match")
        key = header_key or body_key
        result = _buyer_service(request).checkout(
            get_lan(request).library_root,
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
        owner, uid, guest, cookie_response = _buyer_owner(request)
        result = _buyer_service(request).checkout_group(
            get_lan(request).library_root,
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
        owner, uid, guest, cookie_response = _buyer_owner(request, wishlist=True)
        service = _buyer_service(request)
        root = get_lan(request).library_root
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

@seller_required
async def handle_order_stats(request: web.Request) -> web.Response:
    if await require_seller(request) is None:
        return web.json_response({"error": "Seller authentication required"}, status=403)
    try:
        lan = get_lan(request)
        stats = get_commerce_services(request).orders.stats(lan.library_root)
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
    if await require_seller(request) is None:
        return web.json_response({"error": "Seller authentication required"}, status=403)
    try:
        content = get_commerce_services(request).orders.export_csv(get_lan(request).library_root)
        return web.Response(
            text=content,
            content_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="orders.csv"', "Cache-Control": "no-store"},
        )
    except Exception as exc:
        return _error_response(exc)


@commerce_required
async def handle_delivery(request: web.Request) -> web.Response:
    try:
        order, target = get_commerce_services(request).orders.resolve_delivery(
            get_lan(request).library_root, request.match_info["token"], consume=False
        )
        return web.json_response({
            "order": order,
            "filename": target.name,
            "is_directory": target.is_dir(),
            "download_url": f"/api/shop/delivery/{request.match_info['token']}/download",
        }, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return _error_response(exc)

async def _delivery_file_response(
    target: Path,
    *,
    consume: Callable[[], object] | None = None,
    fail: Callable[[], object] | None = None,
) -> web.StreamResponse:
    """Prepare a file/ZIP and consume delivery quota only after preparation."""
    import os
    import tempfile

    from AssetsManager.lan.routes._helpers import build_zip_async, sanitize_filename
    from AssetsManager.lan.routes.downloads import _file_response_with_cleanup

    def mark_failed() -> None:
        if fail is None:
            return
        try:
            fail()
        except Exception:
            _log.exception("Could not persist failed delivery attempt")

    if target.is_file():
        try:
            response = web.FileResponse(
                target,
                headers={
                    "Content-Disposition": f'attachment; filename="{sanitize_filename(target.name)}"',
                    "Cache-Control": "private, no-store",
                },
            )
        except Exception:
            mark_failed()
            return _error_response(DeliveryPreparationError())
        if consume is not None:
            consume()
        return response
    fd, zip_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    try:
        result = await build_zip_async([(target, None)], zip_path)
    except Exception:
        mark_failed()
        try:
            os.unlink(zip_path)
        except OSError:
            pass
        return _error_response(DeliveryPreparationError())
    if result is None:
        mark_failed()
        try:
            os.unlink(zip_path)
        except OSError:
            pass
        return _error_response(DeliveryPreparationError())
    try:
        if consume is not None:
            consume()
    except BaseException:
        try:
            os.unlink(zip_path)
        except OSError:
            pass
        raise
    return _file_response_with_cleanup(
        zip_path, filename=sanitize_filename(f"{target.name}.zip")
    )


@commerce_required
async def handle_order_delivery(request: web.Request) -> web.StreamResponse:
    """Consume delivery quota through the order-scoped HttpOnly receipt."""
    order_id = request.match_info["order_id"]
    try:
        orders = get_commerce_services(request).orders
        root = get_lan(request).library_root
        receipt = _get_order_receipt(request, order_id)
        request_key = _delivery_request_key(request)
        resolve_kwargs: dict[str, Any] = {"consume": False}
        if request_key is not None:
            resolve_kwargs["request_key"] = request_key
        _, target = orders.resolve_delivery_by_receipt(
            root, order_id, receipt, **resolve_kwargs
        )
        consume_kwargs: dict[str, Any] = {"consume": True}
        if request_key is not None:
            consume_kwargs["request_key"] = request_key
        fail = None if request_key is None else lambda: orders.fail_delivery_attempt_by_receipt(
            root, order_id, receipt, request_key=request_key
        )
        return await _delivery_file_response(
            target,
            consume=lambda: orders.resolve_delivery_by_receipt(
                root, order_id, receipt, **consume_kwargs
            ),
            fail=fail,
        )
    except (ValidationError, NotFoundError, PathEscapeError, OperationNotPermitted) as exc:
        return _error_response(exc)


@commerce_required
async def handle_delivery_download(request: web.Request) -> web.StreamResponse:
    """Consume one slot, then reuse the existing guarded file/ZIP delivery."""
    try:
        orders = get_commerce_services(request).orders
        root = get_lan(request).library_root
        token = request.match_info["token"]
        request_key = _delivery_request_key(request)
        resolve_kwargs: dict[str, Any] = {"consume": False}
        if request_key is not None:
            resolve_kwargs["request_key"] = request_key
        _, target = orders.resolve_delivery(root, token, **resolve_kwargs)
        consume_kwargs: dict[str, Any] = {"consume": True}
        if request_key is not None:
            consume_kwargs["request_key"] = request_key
        fail = None if request_key is None else lambda: orders.fail_delivery_attempt(
            root, token, request_key=request_key
        )
        return await _delivery_file_response(
            target,
            consume=lambda: orders.resolve_delivery(
                root, token, **consume_kwargs
            ),
            fail=fail,
        )
    except (ValidationError, NotFoundError, PathEscapeError, OperationNotPermitted) as exc:
        return _error_response(exc)

