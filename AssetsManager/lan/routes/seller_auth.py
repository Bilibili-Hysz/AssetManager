"""Seller authentication HTTP routes."""
from __future__ import annotations

import json
import logging

from aiohttp import web

from AssetsManager.domain.errors import OperationNotPermitted, ValidationError
from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.routes.commerce_policy import (
    seller_logout_endpoint,
    seller_required,
    seller_status_endpoint,
)
from AssetsManager.lan.routes.shop import get_commerce_services, require_seller

SELLER_COOKIE = "seller_session"

_log = logging.getLogger(__name__)


def _set_seller_cookie(response: web.Response, token: str, max_age: int = 12 * 60 * 60,
                       *, secure: bool = False) -> None:
    response.set_cookie(
        SELLER_COOKIE,
        token,
        httponly=True,
        samesite="Lax",
        path="/",
        max_age=max_age,
        secure=secure,
    )


@seller_status_endpoint
async def handle_seller_status(request: web.Request) -> web.Response:
    services = get_commerce_services(request)
    seller = await require_seller(request)
    return web.json_response({
        "enabled": services.seller_auth.is_enabled(),
        "authenticated": seller is not None,
        "seller": seller,
    })


@seller_required
async def handle_seller_login(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValidationError("body", "must be an object")
        seller, token = get_commerce_services(request).seller_auth.login(
            str(body.get("username", "admin")),
            body.get("password", ""),
        )
        response = web.json_response({"ok": True, "authenticated": True, "seller": seller})
        _set_seller_cookie(response, token, secure=getattr(request, "secure", False))
        return response
    except ValidationError as exc:
        # Body-shape failures are expected client errors.
        return error_response(exc)
    except OperationNotPermitted as exc:
        # Credential failures are expected client errors.
        return error_response(str(exc), status=401, code="unauthorized")
    except (json.JSONDecodeError, UnicodeDecodeError):
        # Malformed request bodies are client errors, not server faults.
        return error_response("Invalid request", status=400, code="bad_request")
    except Exception:
        # Unanticipated failures (e.g. database faults behind authentication)
        # must stay distinguishable from bad credentials for operators.
        _log.exception("Seller login failed unexpectedly")
        return error_response("Internal server error", status=500, code="internal_error")


@seller_logout_endpoint
async def handle_seller_logout(request: web.Request) -> web.Response:
    token = request.cookies.get(SELLER_COOKIE, "")
    if token:
        get_commerce_services(request).seller_auth.logout(token)
    response = web.json_response({"ok": True, "authenticated": False})
    response.del_cookie(SELLER_COOKIE, path="/")
    return response



