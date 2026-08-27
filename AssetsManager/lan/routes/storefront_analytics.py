"""Public, privacy-preserving storefront visit route."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import secrets
from typing import cast

from aiohttp import web

from AssetsManager.application.context import ConnectionProvider
from AssetsManager.application.storefront_analytics_service import StorefrontAnalyticsService
from AssetsManager.lan.routes._helpers import get_lan
from AssetsManager.lan.routes.commerce_policy import commerce_gate

_LOGGER = logging.getLogger(__name__)
_STORE_VISIT_COOKIE = "shop_store_visit"
_STORE_VISIT_COOKIE_MAX_AGE = 24 * 60 * 60
_COOKIE_VERSION = "v1"
_COOKIE_SIGNATURE_BYTES = 32


def _cookie_signing_secret(lan: object) -> bytes:
    """Delegate to the shared tunnel/quota secret sourcing.

    Same precedence (``local_ui_auth_secret`` -> ``token_secret`` -> per-lan
    random fallback cached on ``_quota_cookie_secret``), so every visitor
    identity module on one lan object derives keys from one place.  The
    cookie itself keeps its own name/format/lifetime.
    """
    from AssetsManager.lan import tunnel_identity

    return tunnel_identity.signing_secret(lan)


def _new_cookie_token(secret: bytes) -> str:
    nonce = secrets.token_urlsafe(32)
    payload = f"{_COOKIE_VERSION}.{nonce}"
    signature = hmac.new(secret, payload.encode("ascii"), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"{payload}.{encoded_signature}"


def _valid_cookie_token(value: object, secret: bytes) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip()
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != _COOKIE_VERSION:
        return None
    _version, nonce, encoded_signature = parts
    if not (24 <= len(token) <= 256) or not nonce or not encoded_signature or not token.isascii():
        return None
    try:
        signature = base64.urlsafe_b64decode(encoded_signature + "=" * (-len(encoded_signature) % 4))
    except (ValueError, UnicodeError):
        return None
    if len(signature) != _COOKIE_SIGNATURE_BYTES:
        return None
    canonical_signature = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    if not hmac.compare_digest(encoded_signature, canonical_signature):
        return None
    payload = f"{_COOKIE_VERSION}.{nonce}".encode("ascii")
    expected = hmac.new(secret, payload, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        return None
    return token


def get_storefront_analytics_service(request: web.Request) -> StorefrontAnalyticsService:
    lan = get_lan(request)
    existing = getattr(lan, "storefront_analytics_service", None)
    if existing is not None:
        return existing
    scoped = getattr(lan, "services", None)
    scoped_service = getattr(scoped, "storefront_analytics_service", None)
    if scoped_service is not None:
        return scoped_service
    provider = getattr(lan, "connection_for", None)
    if not callable(provider):
        raise RuntimeError("Storefront analytics requires a library connection provider")
    session = getattr(getattr(scoped, "runtime_services", None), "session", None)
    connection_provider = cast(ConnectionProvider, provider)
    service = StorefrontAnalyticsService(connection_provider, session)
    lan.storefront_analytics_service = service
    return service


async def handle_storefront_view(request: web.Request) -> web.Response:
    """Record at most one storefront visit per signed browser cookie per UTC day."""
    disabled = commerce_gate()
    if disabled is not None:
        return disabled
    lan = get_lan(request)
    secret = _cookie_signing_secret(lan)
    token = _valid_cookie_token(request.cookies.get(_STORE_VISIT_COOKIE), secret)
    issue_cookie = token is None
    if token is None:
        token = _new_cookie_token(secret)
    try:
        await asyncio.to_thread(
            get_storefront_analytics_service(request).record_storefront_view,
            lan.library_root,
            token,
        )
        response = web.json_response({"ok": True}, headers={"Cache-Control": "no-store"})
        if issue_cookie:
            response.set_cookie(
                _STORE_VISIT_COOKIE,
                token,
                httponly=True,
                secure=bool(request.secure),
                samesite="Lax",
                path="/api/shop",
                max_age=_STORE_VISIT_COOKIE_MAX_AGE,
            )
        return response
    except Exception:
        # Analytics must never make a buyer-facing storefront unusable.  The
        # seller stats route simply reports zero/unavailable until recording recovers.
        _LOGGER.exception("Storefront analytics recording failed")
        return web.json_response({"ok": False}, status=202, headers={"Cache-Control": "no-store"})
