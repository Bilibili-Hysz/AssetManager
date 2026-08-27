"""Ordinary download quota and Commerce delivery-quota HTTP routes."""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import math
import secrets
import time
from typing import Any

from aiohttp import web

from AssetsManager.application.free_download_quota_service import (
    FreeDownloadQuotaConfig,
    FreeDownloadQuotaService,
)
from AssetsManager.core.settings import AppSettings
from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.routes._helpers import (
    get_lan,
    get_request_principal,
)
from AssetsManager.lan.routes.shop import get_commerce_services, require_seller

_log = logging.getLogger(__name__)


class QuotaUnavailableError(RuntimeError):
    """Raised when the quota store cannot safely decide a download."""


def _as_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"0", "false", "no", "off", "disabled"}:
            return False
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True
    return bool(value)


def get_free_download_quota_config() -> FreeDownloadQuotaConfig:
    settings = AppSettings.instance()
    return FreeDownloadQuotaConfig(
        enabled=_as_bool(settings.get("lan_quota_enabled", False)),
        period=str(settings.get("lan_quota_period", "daily")),
        limit=settings.get("lan_quota_limit", 20),
        min_interval_seconds=settings.get("lan_quota_min_interval_seconds", 5),
    ).normalized()


def _disabled_info(config: FreeDownloadQuotaConfig) -> dict[str, Any]:
    cfg = config.normalized()
    return {
        "enabled": False,
        "period": cfg.period,
        "limit": 0,
        "used": 0,
        "remaining": None,
        "reset_at": None,
        "min_interval_seconds": 0,
    }


_QUOTA_ID_COOKIE = "am_quota_id"
_QUOTA_ID_COOKIE_MAX_AGE = 30 * 24 * 60 * 60  # 30 days
_QUOTA_ID_COOKIE_VERSION = "v1"
_QUOTA_ID_COOKIE_ID_CHARS = 32
_QUOTA_IDENTITY_REQUEST_KEY = web.RequestKey("_quota_identity_resolved", object)


def _quota_cookie_signing_secret(lan: object) -> bytes:
    """Resolve the signing key through the shared tunnel_identity source.

    Same precedence as the tunnel limiter and the storefront analytics
    visitor cookie (``local_ui_auth_secret`` preferred, then ``token_secret``),
    with the per-lan random fallback cached on ``_quota_cookie_secret`` so
    every module on one lan object derives keys from one place.
    """
    from AssetsManager.lan import tunnel_identity

    return tunnel_identity.signing_secret(lan)


def _new_quota_cookie_token(secret: bytes) -> str:
    """Mint a high-entropy anonymous identity cookie: ``v1.<32 hex>.<HMAC>``."""
    cookie_id = secrets.token_hex(16)  # 32 hex chars
    payload = f"{_QUOTA_ID_COOKIE_VERSION}.{cookie_id}"
    signature = hmac.new(secret, payload.encode("ascii"), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"{payload}.{encoded_signature}"


def _quota_cookie_id(token: str) -> str:
    """Return the random identity portion of a validated cookie token."""
    return token.split(".", 2)[1]


def _valid_quota_cookie_token(value: object, secret: bytes) -> str | None:
    """Return the token when its HMAC signature verifies, else None."""
    if not isinstance(value, str):
        return None
    token = value.strip()
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != _QUOTA_ID_COOKIE_VERSION:
        return None
    _version, cookie_id, encoded_signature = parts
    if len(cookie_id) != _QUOTA_ID_COOKIE_ID_CHARS:
        return None
    if not cookie_id.isascii() or not all(c in "0123456789abcdef" for c in cookie_id):
        return None
    if not token.isascii() or not (24 <= len(token) <= 256):
        return None
    try:
        signature = base64.urlsafe_b64decode(
            encoded_signature + "=" * (-len(encoded_signature) % 4)
        )
    except (ValueError, UnicodeError):
        return None
    if len(signature) != 32:
        return None
    payload = f"{_QUOTA_ID_COOKIE_VERSION}.{cookie_id}".encode("ascii")
    expected = hmac.new(secret, payload, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        return None
    return token


def resolve_free_download_quota_identity(request: web.Request) -> tuple[str, str | None]:
    """Resolve the quota identity plus any newly issued anonymous cookie.

    Returns ``(identity_key, issued_token)`` where ``issued_token`` is
    non-None only when an anonymous request had no valid signed cookie and a
    fresh one was minted (callers attach it via
    :func:`apply_free_quota_identity_cookie`).  Authenticated principals and
    returning anonymous visitors are stable without reissuing.  The peer
    address is a pure last-resort fallback so a reverse proxy (cloudflared)
    cannot collapse every visitor into one shared bucket.

    The result is cached on the request so repeated lookups within one
    request lifecycle (e.g. an info read plus a consume) share one identity.
    """
    cached = request.get(_QUOTA_IDENTITY_REQUEST_KEY)
    if cached is not None:
        return cached
    principal = get_request_principal(request)
    if principal is not None and principal.authenticated:
        profile = principal.user_profile or {}
        user_id = profile.get("id")
        if user_id is not None:
            result = (f"user:{user_id}", None)
        else:
            result = (f"principal:{principal.kind}:{principal.display_name}", None)
    else:
        lan = get_lan(request)
        try:
            secret = _quota_cookie_signing_secret(lan)
            token = _valid_quota_cookie_token(
                request.cookies.get(_QUOTA_ID_COOKIE), secret
            )
        except Exception:
            result = (f"ip:{request.remote or 'unknown'}", None)
        else:
            if token is not None:
                result = (f"anon:{_quota_cookie_id(token)}", None)
            else:
                try:
                    token = _new_quota_cookie_token(secret)
                except Exception:
                    result = (f"ip:{request.remote or 'unknown'}", None)
                else:
                    result = (f"anon:{_quota_cookie_id(token)}", token)
    request[_QUOTA_IDENTITY_REQUEST_KEY] = result
    return result


def free_download_quota_identity(request: web.Request) -> str:
    """Return a stable, non-secret identity without trusting arbitrary XFF.

    Authenticated database users are isolated by user id; password/access-key
    principals are isolated by their explicit auth kind.  Unauthenticated
    visitors are isolated by a signed high-entropy browser cookie
    (``am_quota_id``) issued on first contact; the peer address is only a
    fallback for clients that cannot carry cookies.
    """
    identity, _issued = resolve_free_download_quota_identity(request)
    return identity


def apply_free_quota_identity_cookie(response: web.StreamResponse, request: web.Request) -> None:
    """Attach a newly issued anonymous quota cookie to a response."""
    resolved = request.get(_QUOTA_IDENTITY_REQUEST_KEY)
    if resolved is None:
        return
    _identity, token = resolved
    if not token:
        return
    response.set_cookie(
        _QUOTA_ID_COOKIE,
        token,
        httponly=True,
        secure=bool(getattr(request, "secure", False)),
        samesite="Lax",
        max_age=_QUOTA_ID_COOKIE_MAX_AGE,
        path="/",
    )


def get_free_download_quota_service(request: web.Request) -> FreeDownloadQuotaService:
    """Resolve one library-bound service and reuse it for the LAN lifetime."""
    lan = get_lan(request)
    existing = getattr(lan, "free_download_quota_service", None)
    if existing is not None:
        maintain_free_download_quota_service(existing, get_free_download_quota_config())
        return existing
    scoped = getattr(lan, "services", None)
    provider = getattr(lan, "connection_for", None)
    session = getattr(getattr(scoped, "runtime_services", None), "session", None)
    if not callable(provider):
        raise RuntimeError("Free download quota requires a library connection provider")
    connection = provider(lan.library_root)
    service = FreeDownloadQuotaService.for_connection(
        connection,
        library_root=lan.library_root,
        session=session,
    )
    lan.free_download_quota_service = service
    maintain_free_download_quota_service(service, get_free_download_quota_config())
    return service


def maintain_free_download_quota_service(
    service: FreeDownloadQuotaService,
    config: FreeDownloadQuotaConfig,
) -> None:
    """Run due maintenance without making the quota decision fail open."""
    try:
        removed = service.maybe_prune_stale_windows(config)
    except Exception as exc:
        _log.warning("Free-download quota window prune failed; will retry: %s", exc)
        return
    if removed:
        _log.info("Pruned %d expired free-download quota windows", removed)


def get_free_download_quota_info(request: web.Request) -> dict[str, Any]:
    config = get_free_download_quota_config()
    if not config.enabled:
        return _disabled_info(config)
    return get_free_download_quota_service(request).info(
        free_download_quota_identity(request), config
    )


def consume_free_download_quota(request: web.Request) -> dict[str, Any]:
    config = get_free_download_quota_config()
    if not config.enabled:
        return {"allowed": True, "reason": None, "info": _disabled_info(config), "retry_after_seconds": 0}
    try:
        return get_free_download_quota_service(request).consume(
            free_download_quota_identity(request), config
        )
    except Exception as exc:
        raise QuotaUnavailableError("Free download quota store is unavailable") from exc


def apply_free_quota_headers(headers: dict[str, str], info: dict[str, Any]) -> None:
    if not info.get("enabled"):
        return
    remaining = info.get("remaining")
    reset_at = info.get("reset_at")
    headers.update({
        "X-Quota-Remaining": str(remaining),
        "X-Quota-Limit": str(info.get("limit", 0)),
        "X-Quota-Period": str(info.get("period", "daily")),
        "X-Quota-Reset": str(reset_at),
    })


async def handle_free_quota(request: web.Request) -> web.Response:
    try:
        info = get_free_download_quota_info(request)
        response = web.json_response(info, headers={"Cache-Control": "no-store"})
        apply_free_quota_identity_cookie(response, request)
        return response
    except Exception:
        # Status is an optional UX endpoint; an unavailable quota store must
        # not turn the library landing page into a blank error screen.
        return error_response("Quota unavailable", status=503, code="service_unavailable")


async def handle_delivery_quota(request: web.Request) -> web.Response:
    """Return the existing aggregate quota for seller delivery tokens."""
    if await require_seller(request) is None:
        return error_response("Seller authentication required", status=403, code="forbidden")
    quota = get_commerce_services(request).quota.get_quota(get_lan(request).library_root)
    return web.json_response({"quota": quota}, headers={"Cache-Control": "no-store"})


# Compatibility export retained for callers that imported the old delivery
# handler directly.  The public /api/quota route is registered to
# handle_free_quota; /api/shop/quota retains the old seller-only meaning.
handle_quota = handle_delivery_quota


def quota_retry_after_seconds(info: dict[str, Any], result: dict[str, Any]) -> int:
    retry = int(result.get("retry_after_seconds", 0) or 0)
    if result.get("reason") == "exhausted" and retry <= 0:
        reset_at = info.get("reset_at")
        if reset_at is not None:
            retry = max(0, math.ceil(float(reset_at) - time.time()))
    return retry
