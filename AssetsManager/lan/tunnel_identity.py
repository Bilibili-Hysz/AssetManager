"""Signed anonymous visitor identity for tunnel-mode rate limiting.

Mirrors the quota module's ``am_quota_id`` cookie primitives (same name,
token format ``v1.<32 hex>.<HMAC>``, and secret precedence) so cookies
issued by either module verify in both.  This is a dependency-free leaf:
stdlib only, no aiohttp/route imports, safe for security-middleware use.

Trust model: the token proves possession of a server-minted identity; it is
never derived from client-controlled forwarded headers.  Direct LAN clients
are unaffected because callers gate on "tunnel active AND loopback peer".
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

COOKIE_NAME = "am_quota_id"
COOKIE_MAX_AGE = 30 * 24 * 60 * 60  # 30 days
_TOKEN_VERSION = "v1"
_TOKEN_ID_CHARS = 32


def signing_secret(lan: object) -> bytes:
    """Resolve the HMAC secret with the same precedence as the quota cookie.

    ``local_ui_auth_secret`` first, then ``token_secret``, then a per-LAN
    random key cached on the shared ``_quota_cookie_secret`` attribute —
    reusing that attribute keeps the fallback secret identical to the one
    the quota module mints, so both cookies stay mutually verifiable.
    """
    configured = getattr(lan, "local_ui_auth_secret", None) or getattr(
        lan, "token_secret", None
    )
    if isinstance(configured, bytes) and configured:
        return configured
    if isinstance(configured, str) and configured:
        return configured.encode("utf-8")

    cached = getattr(lan, "_quota_cookie_secret", None)
    if not isinstance(cached, bytes) or not cached:
        cached = secrets.token_bytes(32)
        setattr(lan, "_quota_cookie_secret", cached)
    return cached


def new_token(secret: bytes) -> str:
    """Mint ``v1.<32 hex>.<urlsafe HMAC-SHA256>``."""
    cookie_id = secrets.token_hex(16)
    payload = f"{_TOKEN_VERSION}.{cookie_id}"
    signature = hmac.new(secret, payload.encode("ascii"), hashlib.sha256).digest()
    encoded = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"{payload}.{encoded}"


def token_client_id(token: str) -> str:
    """Return the random identity portion of a validated token."""
    return token.split(".", 2)[1]


def valid_token(value: object, secret: bytes) -> str | None:
    """Return the token when its HMAC signature verifies, else None."""
    if not isinstance(value, str):
        return None
    token = value.strip()
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != _TOKEN_VERSION:
        return None
    _version, cookie_id, encoded_signature = parts
    if len(cookie_id) != _TOKEN_ID_CHARS:
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
    payload = f"{_TOKEN_VERSION}.{cookie_id}".encode("ascii")
    expected = hmac.new(secret, payload, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        return None
    return token


def apply_visitor_cookie(response, token: str, *, secure: bool = False) -> None:
    """Attach the visitor identity cookie using the quota route's attributes.

    ``secure`` mirrors the request's own scheme so HTTPS-terminated tunnel
    edges get a Secure cookie while plain loopback HTTP keeps working.
    """
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="Lax",
        path="/",
        secure=secure,
    )
