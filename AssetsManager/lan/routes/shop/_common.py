"""Shared Commerce route helpers: services, request parsing, and buyer state."""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from aiohttp import web

from AssetsManager.application.order_service import DEFAULT_RECEIPT_TTL, OrderService
from AssetsManager.application.quota_service import QuotaService
from AssetsManager.application.seller_auth_service import SellerAuthService
from AssetsManager.application.shop_service import ShopService
from AssetsManager.application.shop_buyer_service import ShopBuyerService, new_guest_token, token_hash
from AssetsManager.domain.errors import (
    StoreNotAcceptingOrdersError,
    ValidationError,
)
from AssetsManager.lan.routes._helpers import get_request_principal
from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.routes.commerce_policy import (
    seller_is_enabled,
)


_log = logging.getLogger(__name__)


def _package_function(name: str):
    """Resolve a package-level commerce function, honoring monkeypatches.

    Tests (and embedders) patch attributes on ``AssetsManager.lan.routes.shop``
    the same way they did on the former single module.  Handler modules call
    through this helper so those patches remain observable after the split.
    """
    import sys

    package_name = __package__ or __name__.rpartition(".")[0]
    package = sys.modules.get(package_name)
    if package is None:
        raise RuntimeError("commerce shop package is not imported")
    function = getattr(package, name, None)
    if function is None:
        raise RuntimeError(f"commerce shop package has no {name!r}")
    return function


@dataclass(frozen=True)
class CommerceServices:
    shop: ShopService
    orders: OrderService
    quota: QuotaService
    seller_auth: SellerAuthService
    buyer: ShopBuyerService | None = None


def get_commerce_services(request: web.Request) -> CommerceServices:
    """Resolve injected commerce services or lazily bind them to this LAN instance."""
    lan = _package_function("get_lan")(request)
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
    return _error_response(StoreNotAcceptingOrdersError())


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
    services = _package_function("get_commerce_services")(request)
    return services.seller_auth.authenticate(token)


def _buyer_service(request: web.Request) -> ShopBuyerService:
    services = _package_function("get_commerce_services")(request)
    return services.buyer or ShopBuyerService(getattr(_package_function("get_lan")(request), "connection_for", None), getattr(getattr(_package_function("get_lan")(request), "services", None), "runtime_services", None))

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
