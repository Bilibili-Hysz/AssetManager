"""Canonical LAN error response contract.

Every route-level JSON error response should eventually go through
:func:`error_response` so the WebUI has exactly one payload shape to parse:

    {"error": str, "code": str, "details": dict}     + optional field/extras

Semantics:

- A plain ``str`` keeps that exact human-readable message; ``code`` and
  ``status`` are explicit keyword arguments.
- A domain exception is mapped to a machine-readable ``code`` and HTTP
  status; the mapping is the single source of truth previously duplicated
  across ``routes/shop.py``, ``routes/favorites.py`` and
  ``routes/seller_profile.py``.
- Unknown failures are logged server-side and never leak exception text to
  clients (buyers, sellers, or browsers).
"""
from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from AssetsManager.application.gallery_service import GalleryTraversalLimitError
from AssetsManager.application.shop_authorization import (
    ShopAuthorizationConfigError,
    UnauthorizedShopPathError,
)
from AssetsManager.domain.errors import (
    DeliveryPreparationError,
    MissingPathError,
    NotFoundError,
    OperationNotPermitted,
    PathEscapeError,
    PriceChangedError,
    StoreNotAcceptingOrdersError,
    ValidationError,
    VersionConflictError,
    WishlistLimitError,
)

_log = logging.getLogger(__name__)


def error_response(
    message_or_exc: str | Exception,
    *,
    status: int | None = None,
    code: str | None = None,
    field: str | None = None,
    details: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> web.Response:
    """Serialize one error into the stable JSON contract.

    ``message_or_exc`` is either a human-readable message (``code`` and
    ``status`` are then required call-site choices) or a domain exception
    mapped to its machine-readable contract below.
    """
    if isinstance(message_or_exc, str):
        return _plain(message_or_exc, status, code, field, details, extra, headers)
    return _mapped(message_or_exc, status, code, field, details, extra, headers)


def _plain(
    message: str,
    status: int | None,
    code: str | None,
    field: str | None,
    details: dict[str, Any] | None,
    extra: dict[str, Any] | None,
    headers: dict[str, str] | None,
) -> web.Response:
    payload: dict[str, Any] = {
        "error": message,
        "code": code or "internal_error",
        "details": {} if details is None else details,
    }
    if field is not None:
        payload["field"] = field
    if extra:
        payload.update(extra)
    if status is None:
        status = 500
    if status >= 500:
        headers = {"Cache-Control": "no-store"}
    return web.json_response(payload, status=status, headers=headers)


def _mapped(
    exc: Exception,
    status: int | None,
    code: str | None,
    field: str | None,
    details: dict[str, Any] | None,
    extra: dict[str, Any] | None,
    headers: dict[str, str] | None,
) -> web.Response:
    # Explicit call-site overrides keep the factory usable for route-specific
    # messages while the mapping below stays the shared default.
    if status is not None or code is not None:
        message = str(exc)
        return _plain(message, status, code, field, details, extra, headers)

    if isinstance(exc, StoreNotAcceptingOrdersError):
        return web.json_response(
            {
                "error": "This store is not accepting new orders",
                "code": "store_not_accepting_orders",
            },
            status=503,
            headers={"Cache-Control": "no-store"},
        )
    if isinstance(exc, DeliveryPreparationError):
        return web.json_response(
            {"error": str(exc), "code": exc.code, "details": {}},
            status=500,
            headers={"Cache-Control": "no-store"},
        )

    payload: dict[str, Any] = {"error": str(exc), "code": "internal_error", "details": {}}
    status = 500
    headers = {"Cache-Control": "private, no-store"}

    if isinstance(exc, ValidationError):
        payload["code"] = "validation_error"
        if exc.field:
            payload["field"] = exc.field
        status = 400
    elif isinstance(exc, PathEscapeError):
        payload = {
            "error": "Path escape detected",
            "code": "path_escape_detected",
            "field": "path",
            "details": {},
        }
        status = 400
    elif isinstance(exc, UnauthorizedShopPathError):
        payload = {
            "error": str(exc),
            "code": "shop_path_not_authorized",
            "details": {},
        }
        status = 403
    if isinstance(exc, ShopAuthorizationConfigError):
        # 503 with a specific code, exempt from the 500+ no-leak rewrite so
        # the seller UI can surface the configuration problem. The historical
        # shop.py mapping set these fields and then overwrote them in the
        # final status >= 500 block, which looked unintentional.
        return web.json_response(
            {
                "error": "Shop authorization configuration is invalid",
                "code": "shop_authorization_config_invalid",
                "details": {},
            },
            status=503,
            headers={"Cache-Control": "no-store"},
        )
    if isinstance(exc, GalleryTraversalLimitError):
        payload["code"] = "gallery_traversal_limit"
        status = exc.status
    elif isinstance(exc, (MissingPathError, NotFoundError)):
        payload["code"] = "not_found"
        status = 404
        if isinstance(exc, NotFoundError):
            entity = str(getattr(exc, "entity", "")).strip().lower()
            if entity == "cart line":
                payload["code"] = "cart_line_not_found"
                payload["field"] = "line_id"
            elif entity == "order receipt":
                payload["code"] = "receipt_not_found"
                payload["field"] = "order_id"
            elif entity == "delivery":
                payload["code"] = "delivery_not_found"
                payload["field"] = "token"
    elif isinstance(exc, PriceChangedError):
        payload["code"] = "price_changed"
        payload["field"] = "item_id"
        payload["item_id"] = exc.item_id
        status = 409
    elif isinstance(exc, VersionConflictError):
        payload["code"] = "cart_version_conflict"
        payload["field"] = "version"
        status = 409
    elif isinstance(exc, WishlistLimitError):
        payload["code"] = "wishlist_limit"
        payload["field"] = "items"
        payload["limit"] = exc.limit
        status = 409
    elif isinstance(exc, OperationNotPermitted):
        message = str(exc)
        lowered = message.lower()
        if "receipt" in lowered and "expired" in lowered:
            payload["code"] = "receipt_expired"
            status = 410
        elif "download limit" in lowered or "quota exceeded" in lowered:
            payload["code"] = "delivery_quota_exhausted"
            status = 410
        elif "delivery token" in lowered and ("expired" in lowered or "revoked" in lowered):
            payload["code"] = "delivery_unavailable"
            status = 410
        else:
            payload["code"] = getattr(exc, "code", "operation_not_permitted")
            status = 409

    if status >= 500:
        _log.error(
            "Unhandled LAN route error",
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        payload["error"] = "Internal server error"
        payload["code"] = "internal_error"
        headers = {"Cache-Control": "no-store"}
    return web.json_response(payload, status=status, headers=headers)
