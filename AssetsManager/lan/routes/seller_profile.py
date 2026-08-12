"""Seller-gated HTTP handlers for the per-library seller profile."""
from __future__ import annotations

from typing import Any, cast

from aiohttp import web

from AssetsManager.application.context import ConnectionProvider
from AssetsManager.application.seller_profile_service import SellerProfileService
from AssetsManager.domain.errors import ValidationError
from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.routes._helpers import get_lan
from AssetsManager.lan.routes.commerce_policy import commerce_required, seller_required
from AssetsManager.lan.routes.shop import require_seller


def get_seller_profile_service(request: web.Request) -> SellerProfileService:
    """Resolve the injected service or lazily bind one to this LAN library."""
    lan = get_lan(request)
    existing = getattr(lan, "seller_profile_service", None)
    if existing is not None:
        return existing

    scoped = getattr(lan, "services", None)
    existing = getattr(scoped, "seller_profile_service", None)
    if existing is not None:
        return existing

    provider = getattr(lan, "connection_for", None)
    runtime_services = getattr(scoped, "runtime_services", None)
    session = getattr(runtime_services, "session", None)
    if session is None:
        session = getattr(getattr(lan, "runtime", None), "session", None)
    connection_provider = cast(ConnectionProvider, provider) if callable(provider) else None
    service = SellerProfileService(connection_provider, session)
    try:
        lan.seller_profile_service = service
    except Exception:
        # A read-only LAN adapter can still use the per-request service safely.
        pass
    return service


def _error_response(exc: Exception) -> web.Response:
    """Canonical error contract; unknown failures no longer leak exception
    text (previously re-raised to aiohttp's generic 500)."""
    if isinstance(exc, ValidationError):
        return error_response(exc)
    if isinstance(exc, ValueError):
        return error_response(str(exc), status=400, code="bad_request")
    return error_response(exc)


async def _json_body(request: web.Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:
        raise ValidationError("body", "invalid JSON") from exc
    if not isinstance(body, dict):
        raise ValidationError("body", "must be an object")
    return body


@commerce_required
async def handle_public_seller_profile(request: web.Request) -> web.Response:
    """Return only the public-facing storefront profile fields."""
    try:
        profile = get_seller_profile_service(request).get_profile(get_lan(request).library_root)
        return web.json_response({
            "profile": {
                "store_name": profile["store_name"],
                "description": profile["description"],
                "accept_orders": profile["accept_orders"],
            }
        }, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return _error_response(exc)


@seller_required
async def handle_seller_profile(request: web.Request) -> web.Response:
    """Read or update the single seller profile for the current library."""
    if await require_seller(request) is None:
        return error_response("Seller authentication required", status=403, code="forbidden")
    try:
        lan = get_lan(request)
        service = get_seller_profile_service(request)
        if request.method == "GET":
            profile = service.get_profile(lan.library_root)
        elif request.method == "PUT":
            profile = service.update_profile(lan.library_root, await _json_body(request))
        else:
            return error_response("Method not allowed", status=405, code="method_not_allowed")
        return web.json_response({"profile": profile}, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        return _error_response(exc)


__all__ = ["get_seller_profile_service", "handle_public_seller_profile", "handle_seller_profile"]
