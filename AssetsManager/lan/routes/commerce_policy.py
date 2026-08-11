"""Per-request Commerce and Seller feature policy for LAN HTTP routes.

The settings are deliberately read for every request.  Only the literal boolean
``True`` enables a feature; missing values, truthy strings/integers, and settings
errors all fail closed.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, cast

from aiohttp import web

from AssetsManager.core.settings import AppSettings

COMMERCE_DISABLED_BODY = {
    "error": "Commerce is disabled",
    "code": "feature_disabled",
}
SELLER_DISABLED_BODY = {
    "error": "Seller is disabled",
    "code": "feature_disabled",
}
SELLER_COOKIE = "seller_session"


@dataclass(frozen=True)
class CommercePolicy:
    commerce_enabled: bool
    seller_enabled: bool


def get_commerce_policy() -> CommercePolicy:
    """Return the current fail-closed feature policy snapshot."""
    try:
        settings = AppSettings.instance()
        commerce_enabled = settings.get("lan_commerce_enabled", False) is True
        seller_configured = settings.get("lan_seller_enabled", False) is True
    except Exception:
        return CommercePolicy(commerce_enabled=False, seller_enabled=False)
    return CommercePolicy(
        commerce_enabled=commerce_enabled,
        seller_enabled=commerce_enabled and seller_configured,
    )


def commerce_is_enabled() -> bool:
    return get_commerce_policy().commerce_enabled


def seller_is_enabled() -> bool:
    return get_commerce_policy().seller_enabled


def commerce_disabled_response() -> web.Response:
    return web.json_response(COMMERCE_DISABLED_BODY, status=404)


def seller_disabled_response() -> web.Response:
    return web.json_response(SELLER_DISABLED_BODY, status=404)


def _cached_seller_auths(request: web.Request) -> tuple[Any, ...]:
    """Return all already-created SellerAuthService holders.

    Feature-disabled endpoints must not construct Commerce services, but they
    still need to revoke sessions held by every cache/bundle alias.
    """
    try:
        from AssetsManager.lan.routes._helpers import LAN_APP_KEY

        lan = request.app[LAN_APP_KEY]
    except (AttributeError, KeyError, TypeError):
        return ()

    holders = (
        getattr(lan, "commerce_services", None),
        getattr(lan, "_commerce_services", None),
        getattr(lan, "services", None),
        getattr(lan, "_services", None),
        getattr(lan, "_injected_services", None),
    )
    result = []
    seen: set[int] = set()
    for holder in holders:
        if holder is None:
            continue
        for name in ("seller_auth", "seller_auth_service"):
            seller_auth = getattr(holder, name, None)
            if seller_auth is not None and id(seller_auth) not in seen:
                seen.add(id(seller_auth))
                result.append(seller_auth)
    return tuple(result)


def _cached_seller_auth(request: web.Request):
    """Return the first cached SellerAuthService without constructing services."""
    return next(iter(_cached_seller_auths(request)), None)


def _revoke_cached_seller_sessions(request: web.Request) -> int:
    """Revoke cached Seller sessions without resolving Commerce services."""
    total_revoked = 0
    token = request.cookies.get(SELLER_COOKIE, "")
    for seller_auth in _cached_seller_auths(request):
        revoke_all = getattr(seller_auth, "revoke_all", None)
        if callable(revoke_all):
            try:
                total_revoked += int(cast(Any, revoke_all()) or 0)
            except Exception:
                continue
            continue
        logout = getattr(seller_auth, "logout", None)
        if token and callable(logout):
            try:
                total_revoked += 1 if logout(token) else 0
            except Exception:
                continue
    return total_revoked


def commerce_gate() -> web.Response | None:
    if not commerce_is_enabled():
        return commerce_disabled_response()
    return None


def seller_gate() -> web.Response | None:
    policy = get_commerce_policy()
    if not policy.commerce_enabled:
        return commerce_disabled_response()
    if not policy.seller_enabled:
        return seller_disabled_response()
    return None


async def _call_handler(handler: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    result = handler(*args, **kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


def commerce_required(handler: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a sync or async handler with the public Commerce feature gate."""
    @wraps(handler)
    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        disabled = commerce_gate()
        if disabled is not None:
            return disabled
        return await _call_handler(handler, *args, **kwargs)

    return wrapped


def seller_required(handler: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a sync or async handler with the effective Seller feature gate."""
    @wraps(handler)
    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        disabled = seller_gate()
        if disabled is not None:
            return disabled
        return await _call_handler(handler, *args, **kwargs)

    return wrapped


def seller_status_endpoint(handler: Callable[..., Any]) -> Callable[..., Any]:
    """Return a safe disabled status without resolving auth or services."""
    @wraps(handler)
    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        if not seller_is_enabled():
            _revoke_cached_seller_sessions(args[0])
            return web.json_response({
                "enabled": False,
                "authenticated": False,
                "seller": None,
            })
        return await _call_handler(handler, *args, **kwargs)

    return wrapped


def seller_logout_endpoint(handler: Callable[..., Any]) -> Callable[..., Any]:
    """Clear stale seller cookies even while Commerce/Seller is disabled."""
    @wraps(handler)
    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        if not seller_is_enabled():
            _revoke_cached_seller_sessions(args[0])
            response = web.json_response({"ok": True, "authenticated": False})
            response.del_cookie(SELLER_COOKIE, path="/")
            return response
        return await _call_handler(handler, *args, **kwargs)

    return wrapped


__all__ = [
    "COMMERCE_DISABLED_BODY",
    "SELLER_DISABLED_BODY",
    "CommercePolicy",
    "commerce_gate",
    "commerce_is_enabled",
    "commerce_required",
    "get_commerce_policy",
    "seller_gate",
    "seller_is_enabled",
    "seller_logout_endpoint",
    "seller_required",
    "seller_status_endpoint",
]
