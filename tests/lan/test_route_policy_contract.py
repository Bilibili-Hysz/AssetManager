"""Route policy contract tests.

The per-route auth/rate-limit policy is declared at registration time in
api.py and consumed by the security/auth middlewares. These tests pin the
contract:

1. every registered route declares an explicit policy (no silent default),
2. every policy entry corresponds to a registered route (no orphan keys),
3. the new policy decisions are exactly equivalent to the historical
   hardcoded-list logic (golden equivalence) — the old logic is frozen
   here as the reference implementation.
"""
from __future__ import annotations

import re

import pytest

from aiohttp import web

from AssetsManager.lan.api import setup_routes
from AssetsManager.lan.route_policy import DEFAULT_POLICY, POLICY_KEY, lookup

# ── Frozen historical logic (pre-declaration lists) ────────────────

_OLD_SKIP = frozenset({"/ws", "/api/projects", "/api/tags", "/api/info", "/api/tunnel/status"})
_OLD_SKIP_PREFIX = (
    "/assets", "/api/thumbnails", "/api/gallery", "/api/favorites",
    "/api/quicksearch", "/api/stats", "/api/metadata", "/api/notes",
    "/api/tree",
)
_OLD_SKIP_EXACT = frozenset({
    "/api/home", "/api/search", "/api/quota", "/api/activity",
    "/api/revision", "/api/files/summaries",
})
_OLD_AUTH_ENDPOINTS = frozenset({
    "/api/auth/login", "/api/auth/register", "/api/auth/verify_key",
    "/api/auth/seller-login", "/api/shop/auth/login",
})
_OLD_PUBLIC = frozenset({
    "/api/auth/login", "/api/auth/register", "/api/auth/verify_key",
    "/api/auth/seller-status", "/api/auth/seller-login",
    "/api/auth/seller-logout", "/api/quota", "/login", "/browse",
    "/detail", "/", "/favicon.ico",
})
_OLD_PUBLIC_PREFIXES = ("/assets", "/s", "/storefront", "/store", "/seller", "/app", "/api/shop")


def _matches_prefix(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(f"{prefix}/")


def _old_rate_limit(method: str, path: str) -> str:
    if path in _OLD_AUTH_ENDPOINTS or (
        path.startswith("/api/shares/") and path.endswith("/verify")
    ):
        return "auth_strict"
    if (
        any(_matches_prefix(path, p) for p in _OLD_SKIP_PREFIX)
        or path in _OLD_SKIP
        or path in _OLD_SKIP_EXACT
        or (method == "GET" and path == "/api/files")
    ):
        return "skip"
    return "general"


def _old_auth(method: str, path: str) -> str:
    if path == "/api/info":
        return "public_optional"
    if path in _OLD_PUBLIC:
        return "public"
    for prefix in _OLD_PUBLIC_PREFIXES:
        if _matches_prefix(path, prefix):
            return "public_optional" if prefix == "/api/shop" else "public"
    if path.startswith("/api/shares/"):
        parts = path[len("/api/shares/"):].split("/", 2)
        if len(parts) >= 2 and parts[0]:
            action = parts[1]
            has_tail = len(parts) == 3
            if method == "POST" and action == "verify" and not has_tail:
                return "public"
            if method == "GET" and (
                (action == "info" and not has_tail)
                or (action in {"download", "preview"} and has_tail)
            ):
                return "public"
    return "required"


def _concrete_path(pattern: str) -> str:
    return re.sub(r"\{[^}]*\}", "x", pattern)


def _registered_routes(app: web.Application) -> list[tuple[str, str]]:
    """Return (method, canonical) for every registered route pattern."""
    entries: list[tuple[str, str]] = []
    for route in app.router.routes():
        resource = getattr(route, "resource", None)
        canonical = getattr(resource, "canonical", None)
        if canonical is None:
            continue
        if isinstance(route, web.StaticResource):
            entries.append(("", canonical))
        else:
            method = getattr(route, "method", "")
            if method in {"GET", "HEAD"}:
                entries.append(("GET", canonical))
                entries.append(("HEAD", canonical))
            else:
                entries.append((method, canonical))
    return entries


@pytest.fixture
def app_with_routes():
    app = web.Application()
    setup_routes(app)
    return app


def test_every_registered_route_declares_a_policy(app_with_routes):
    """No registered route may fall back to the silent default policy."""
    table = app_with_routes[POLICY_KEY]
    for method, canonical in _registered_routes(app_with_routes):
        declared = (method, canonical) in table or ("", canonical) in table
        assert declared, f"{method or 'static'} {canonical} has no policy declaration"


def test_every_policy_entry_matches_a_registered_route(app_with_routes):
    """No orphan policy keys (dead entries like the old /api/metadata)."""
    table = app_with_routes[POLICY_KEY]
    registered = {canonical for _method, canonical in _registered_routes(app_with_routes)}
    for (method, canonical) in table:
        assert canonical in registered, f"orphan policy entry for {canonical}"
        if method:
            assert (method, canonical) in _registered_routes(app_with_routes), (
                f"method-scoped policy for unregistered {method} {canonical}"
            )


def test_policy_decisions_match_the_frozen_historical_logic(app_with_routes):
    """Golden equivalence: old hardcoded lists vs the declared policy."""
    for method, canonical in _registered_routes(app_with_routes):
        path = _concrete_path(canonical)
        policy = lookup(app_with_routes, method or "GET", canonical)
        expected_rate = _old_rate_limit(method or "GET", path)
        expected_auth = _old_auth(method or "GET", path)
        assert policy.rate_limit == expected_rate, (
            f"{method or 'GET'} {path}: rate_limit {policy.rate_limit!r} "
            f"!= historical {expected_rate!r}"
        )
        assert policy.auth == expected_auth, (
            f"{method or 'GET'} {path}: auth {policy.auth!r} "
            f"!= historical {expected_auth!r}"
        )


def test_unregistered_paths_keep_the_fail_closed_default(app_with_routes):
    assert lookup(app_with_routes, "GET", None) is DEFAULT_POLICY
    assert lookup(app_with_routes, "GET", "/api/nonexistent") is DEFAULT_POLICY
