"""Route-level security policy declarations.

Authentication and rate-limit behavior used to live in hardcoded path
lists inside security.py and server.py that had to be kept in sync with
the registrations in api.py by hand (a drift-prone, two-source-of-truth
arrangement). Routes now declare their policy at registration time; the
middlewares read it back through this module.

Unknown patterns (404s, unregistered paths) get the fail-closed default:
auth required plus the general rate-limit budget.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from aiohttp import web

POLICY_KEY = web.AppKey("route_policy", dict[tuple[str, str], "RoutePolicy"])

AuthMode = Literal["required", "public", "public_optional"]
RateLimitClass = Literal["general", "skip", "auth_strict"]

# Declarative authorization capabilities (L1). Each write route names the
# ability it requires instead of relying on a handler remembering to check.
# Principal-backed names mirror ``principal.Capabilities`` fields; the rest
# are checked by ``lan/authorization.py`` (some against seller/buyer state).
KNOWN_CAPABILITIES = frozenset({
    # Principal capabilities (checked against principal.capabilities).
    "browse", "preview", "download", "manage_links", "manage_users",
    "settings", "realtime",
    # Helper-backed write gates.
    "write_notes", "write_tags", "admin_tags", "admin_users",
    # Commerce gates (seller session / guest buyer tokens).
    "seller", "buyer_cart", "buyer_wishlist", "buyer_orders", "buyer_claim",
    # Intentional anonymous entry points: identity bootstrap, share-password
    # verification, and public analytics signals.
    "public_auth", "public_signal", "share_verify",
})

# These capabilities are satisfied by any resolved principal (including
# guests). They still must be declared so the static gate cannot miss a
# public write; their safety comes from handler-owned state (buyer tokens,
# receipts, invite codes, rate-limited login attempts).
GUEST_ALLOWED_CAPABILITIES = frozenset({
    "buyer_cart", "buyer_wishlist", "buyer_orders", "buyer_claim",
    "public_auth", "public_signal", "share_verify",
})

# aiohttp normalizes "{name:regex}" to "{name}" in a resource's canonical
# pattern; declarations are normalized the same way so lookups always hit.
_FORMAT_RE = re.compile(r"\{([^{}]*):[^}]*\}")


@dataclass(frozen=True)
class RoutePolicy:
    auth: AuthMode = "required"
    rate_limit: RateLimitClass = "general"
    capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.auth not in ("required", "public", "public_optional"):
            raise ValueError(f"unknown auth mode: {self.auth!r}")
        if self.rate_limit not in ("general", "skip", "auth_strict"):
            raise ValueError(f"unknown rate_limit class: {self.rate_limit!r}")
        unknown = [c for c in self.capabilities if c not in KNOWN_CAPABILITIES]
        if unknown:
            raise ValueError(
                f"unknown route capabilities: {', '.join(sorted(unknown))}"
            )


DEFAULT_POLICY = RoutePolicy()


def declare(
    app: web.Application,
    path: str,
    policy: RoutePolicy,
    *,
    method: str = "",
) -> None:
    """Record the policy for one registered route pattern.

    ``method`` scopes the entry to a single HTTP method (only used for the
    rare method-conditional case); omitted, the policy applies to the
    pattern regardless of method. The table lives on the app so server
    restarts and parallel test apps never share policy state.
    """
    canonical = _FORMAT_RE.sub(r"{\1}", path)
    table = app.setdefault(POLICY_KEY, {})
    table[(method, canonical)] = policy


def lookup(app: web.Application, method: str, canonical: str | None) -> RoutePolicy:
    """Return the policy for a resolved request, or the fail-closed default.

    Method-scoped entries win over pattern-level entries. Non-Application
    mappings (mocked requests in tests) and unresolved paths keep the
    default.
    """
    table = app.get(POLICY_KEY) if isinstance(app, web.Application) else None
    if not table or canonical is None:
        return DEFAULT_POLICY
    return table.get((method, canonical)) or table.get(("", canonical)) or DEFAULT_POLICY


def request_policy(request) -> RoutePolicy:
    """Resolve the declared policy for a request's matched route (fail-closed).

    Reads the canonical pattern off ``request.match_info.route``, which is
    available inside aiohttp middlewares (resolution happens before the
    middleware chain). Unknown patterns (404s) and mocked requests keep the
    default.
    """
    route = getattr(request.match_info, "route", None)
    resource = getattr(route, "resource", None)
    canonical = getattr(resource, "canonical", None)
    try:
        return lookup(request.app, request.method, canonical)
    except Exception:
        return DEFAULT_POLICY
