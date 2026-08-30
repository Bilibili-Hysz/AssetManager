"""Declarative capability enforcement for LAN routes (L1).

``RoutePolicy.capabilities`` turns authorization from per-handler conventions
into a middleware-checked contract. This module resolves each declared
capability against the request principal and returns
a 403 response for the first missing capability, so a handler that forgets
its own guard can no longer create a fail-open write path.

Handlers keep their existing guards as defense in depth; feature-policy
gates (features disabled) deliberately run before capability checks
to preserve their historical 404 ``feature_disabled`` contract.
"""
from __future__ import annotations

from aiohttp import web

from AssetsManager.lan.route_policy import (
    GUEST_ALLOWED_CAPABILITIES,
    RoutePolicy,
)
from AssetsManager.lan.routes._errors import error_response
from AssetsManager.lan.routes._helpers import (
    get_request_principal,
    require_admin,
    require_user_write,
)

_PRINCIPAL_CAPABILITIES = frozenset({
    "browse", "preview", "download", "manage_links", "manage_users",
    "settings", "realtime",
})


def _has_principal_capability(request: web.Request, capability: str) -> bool:
    principal = get_request_principal(request)
    if principal is None:
        return False
    return bool(getattr(principal.capabilities, capability, False))


async def enforce_capabilities(
    request: web.Request,
    policy: RoutePolicy,
) -> web.Response | None:
    """Return a 403/feature-disabled response when a capability is missing.

    ``None`` means the request may proceed to its handler. An empty
    capability tuple (reads, or legacy third-party registrations) is a no-op.
    """
    if not policy.capabilities:
        return None
    for capability in policy.capabilities:
        if capability in GUEST_ALLOWED_CAPABILITIES:
            continue
        if capability in _PRINCIPAL_CAPABILITIES:
            if _has_principal_capability(request, capability):
                continue
            return error_response("Forbidden", status=403, code="forbidden")
        if capability in {"write_notes", "write_tags"}:
            if require_user_write(request) is not None:
                continue
            return error_response("Write access required", status=403, code="forbidden")
        if capability in {"admin_tags", "admin_users"}:
            if require_admin(request) is not None:
                continue
            return error_response("Admin access required", status=403, code="forbidden")
        # Unknown names are rejected by RoutePolicy at declaration time.
        return error_response("Forbidden", status=403, code="forbidden")
    return None
