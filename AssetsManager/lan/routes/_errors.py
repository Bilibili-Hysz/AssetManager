"""Canonical LAN error response contract.

Every route-level JSON error response should eventually go through
:func:`error_response` so the WebUI has exactly one payload shape to parse:

    {"error": str, "code": str, "details": dict}     + optional field/extras

Semantics:

- A plain ``str`` keeps that exact human-readable message; ``code`` and
  ``status`` are explicit keyword arguments.
- A domain exception is mapped to a machine-readable ``code`` and HTTP
  status; the mapping is the single source of truth previously duplicated
  across route modules.
- Unknown failures are logged server-side and never leak exception text to
  clients.
"""
from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from AssetsManager.application.gallery_service import GalleryTraversalLimitError
from AssetsManager.domain.errors import (
    DuplicateError,
    MissingPathError,
    NotFoundError,
    OperationNotPermitted,
    PathEscapeError,
    ValidationError,
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
        # Merge, don't replace: callers may pass security headers
        # (X-Content-Type-Options etc.) that must survive the no-store
        # default.
        headers = {"Cache-Control": "no-store", **(headers or {})}
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
    if isinstance(exc, GalleryTraversalLimitError):
        payload["code"] = "gallery_traversal_limit"
        status = exc.status
    elif isinstance(exc, (MissingPathError, NotFoundError)):
        payload["code"] = "not_found"
        status = 404
    elif isinstance(exc, DuplicateError):
        payload["code"] = "conflict"
        status = 409
    elif isinstance(exc, OperationNotPermitted):
        payload["code"] = getattr(exc, "code", "operation_not_permitted")
        status = 409

    if status >= 500:
        _log.error(
            "Unhandled LAN route error",
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        payload["error"] = "Internal server error"
        payload["code"] = "internal_error"
        headers = {"Cache-Control": "no-store", **(headers or {})}
    return web.json_response(payload, status=status, headers=headers)


# Codes for bare aiohttp HTTPExceptions re-wrapped by the middleware below.
# Status and message stay authoritative; the code only gives the WebUI a
# stable machine-readable key for the common statuses this codebase raises.
_HTTP_ERROR_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    410: "gone",
    413: "payload_too_large",
    415: "unsupported_media_type",
    416: "range_not_satisfiable",
    429: "rate_limited",
    503: "service_unavailable",
}


@web.middleware
async def error_contract_middleware(request, handler):
    """Catch-all that keeps every LAN error inside the JSON error contract.

    Placement is the innermost server middleware (after security, metrics and
    auth, immediately around the handler). Rationale:

    - The security middleware owns its own failure handling and must stay
      outside this layer; auth denials are already JSON ``error_response``
      payloads produced before the handler runs.
    - This layer therefore only needs to normalize what escapes a route
      handler, which is exactly what an innermost position sees.

    Three escape shapes exist:

    - Domain exceptions are re-serialized through :func:`error_response`, so
      propagated ``PathEscapeError`` / ``MissingPathError`` / ... keep their
      mapped 4xx contract while unknown failures collapse into the no-leak
      500 ``internal_error`` contract (logged server-side by the mapping).
    - Bare aiohttp HTTPExceptions (router 404/405, ``validate_path`` 400s)
      keep their status and headers but are re-wrapped from aiohttp's default
      ``text/plain`` body into the JSON contract. Redirects (3xx) and bodies
      that already carry JSON pass through untouched.
    """
    try:
        return await handler(request)
    except web.HTTPException as exc:
        if exc.status < 400:
            # Redirects and other non-error HTTP signals keep aiohttp's own
            # handling (re-raised, not returned, per aiohttp guidance).
            raise
        content_type = getattr(exc, "content_type", "") or ""
        if "json" in content_type:
            return exc
        headers = {
            key: value
            for key, value in (exc.headers or {}).items()
            if key.lower() != "content-type"
        }
        # validate_path raises a bare 400 for the same escape condition the
        # domain mapping covers; keep the canonical code so the WebUI sees
        # one contract for one condition regardless of the raise site.
        if exc.status == 400 and exc.reason == "Path escape detected":
            code = "path_escape_detected"
        else:
            code = _HTTP_ERROR_CODES.get(exc.status, f"http_error_{exc.status}")
        return error_response(
            exc.reason or f"HTTP {exc.status}",
            status=exc.status,
            code=code,
            headers=headers or None,
        )
    except Exception as exc:
        # Domain errors keep their own mapped shape; anything unexpected is
        # logged inside error_response and answered with the generic no-leak
        # 500 contract.
        return error_response(exc)
