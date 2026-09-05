"""Security middleware — rate limiting, IP blacklist, request logging.

Rate limiting is IP-scoped and counts requests up front (brute force must be
throttled before the fact); under NAT, many users sharing one IP share one
budget — an accepted trade-off over failure-count or per-username limiting.

The IP whitelist applies to direct connections: cloudflared tunnel traffic
always originates from the loopback address 127.0.0.1, and while the tunnel
is running loopback sources are allowed automatically, so LAN-subnet
whitelists only constrain direct traffic.

Concurrency contract: RateLimiter, AuthRateLimiter and IPBlacklist are
deliberately unlocked and must only be touched from the server event-loop
thread (the security middleware). Do not add UI-thread or worker-thread
call paths without adding synchronization first.
"""
from typing import cast
import ipaddress
import logging
import math
import time
from collections import OrderedDict, defaultdict, deque
from collections.abc import Callable

from aiohttp import web

from AssetsManager.lan import tunnel_identity
from AssetsManager.lan.route_policy import RoutePolicy, request_policy
from AssetsManager.lan.routes._errors import error_response

_log = logging.getLogger(__name__)

SECURITY_BUCKET_KEY = web.RequestKey("_security_bucket_key", str)


def _request_policy(request: web.Request) -> RoutePolicy:
    """Resolve the declared policy for the matched route (fail-closed)."""
    return request_policy(request)


def _normalize_ip(ip: str) -> str:
    """Normalize an IP string so equivalent textual forms compare equal.

    IPv4-mapped IPv6 addresses (``::ffff:1.2.3.4``) collapse to their IPv4
    form and the IPv6 loopback ``::1`` maps to ``127.0.0.1``.  Values that
    are not parseable IPs (hostnames, malformed input) are returned
    unchanged, keeping the existing blacklist string-matching behavior.
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if addr.version == 6:
        addr_v6 = cast(ipaddress.IPv6Address, addr)
        if addr_v6.ipv4_mapped is not None:
            return str(addr_v6.ipv4_mapped)
        if addr_v6 == ipaddress.ip_address("::1"):
            return "127.0.0.1"
    return str(addr)


class RateLimiter:
    """Per-IP rate limiter using sliding window with LRU eviction."""

    def __init__(self, max_requests: int = 1000, window_seconds: int = 60, max_ips: int = 10000):
        self._max = max_requests
        self._window = window_seconds
        self._max_ips = max_ips
        # Requests are appended in timestamp order.  A deque keeps expiry
        # pruning O(number of expired entries) instead of repeatedly shifting
        # a list with pop(0) under burst traffic.
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._access_order: OrderedDict[str, None] = OrderedDict()

    def is_allowed(self, ip: str) -> bool:
        now = time.time()
        cutoff = now - self._window
        reqs = self._requests[ip]

        # Update LRU order
        self._access_order[ip] = None
        self._access_order.move_to_end(ip)

        # Prune old entries in-place (more efficient than creating new list)
        while reqs and reqs[0] <= cutoff:
            reqs.popleft()
        if len(reqs) >= self._max:
            return False
        reqs.append(now)

        # Evict oldest IPs if we exceed max_ips
        self._evict_if_needed()

        return True

    def _evict_if_needed(self):
        """Evict oldest IPs when we exceed max_ips limit."""
        while len(self._requests) > self._max_ips and self._access_order:
            oldest_ip, _ = self._access_order.popitem(last=False)
            if oldest_ip in self._requests:
                del self._requests[oldest_ip]

    def get_remaining(self, ip: str) -> int:
        now = time.time()
        cutoff = now - self._window
        reqs = self._requests.get(ip)
        if not reqs:
            return self._max
        # Prune expired entries in-place so the active count is exact
        while reqs and reqs[0] <= cutoff:
            reqs.popleft()
        return max(0, self._max - len(reqs))

    def retry_after(self, ip: str) -> int:
        """Seconds until the oldest request leaves the window (min 1)."""
        reqs = self._requests.get(ip)
        if not reqs:
            return 1
        oldest = reqs[0]
        return max(1, math.ceil(oldest + self._window - time.time()))


class AuthRateLimiter(RateLimiter):
    """Stricter rate limiter for authentication endpoints."""

    def __init__(self, max_attempts: int = 10, window_seconds: int = 300, max_ips: int = 5000):
        super().__init__(max_requests=max_attempts, window_seconds=window_seconds, max_ips=max_ips)


class IPBlacklist:
    """Simple IP blacklist loaded from a file."""

    def __init__(self):
        self._blocked: set[str] = set()

    def load_from_settings(self, blocked_list: list[str]):
        # Normalize entries the same way request IPs are normalized, so an
        # IPv6-form entry (::1 / ::ffff:127.0.0.1) still matches the
        # canonical form used by the middleware.
        self._blocked = {_normalize_ip(ip) for ip in blocked_list if ip}

    def is_blocked(self, ip: str) -> bool:
        return ip in self._blocked


# ── Middleware factory ────────────────────────────────────────

def create_security_middleware(
    rate_limiter: RateLimiter,
    ip_blacklist: IPBlacklist,
    auth_rate_limiter: "AuthRateLimiter | None" = None,
    *,
    browse_rate_limiter: "RateLimiter | None" = None,
    skip_auth_rate_limiter: "RateLimiter | None" = None,
    ip_whitelist: list[str] | None = None,
    tunnel_active: "Callable[[], bool] | None" = None,
    tunnel_identity_resolver: "Callable[[web.Request], str | None] | None" = None,
    tunnel_identity_minter: "Callable[[], tuple[str, str] | None] | None" = None,
):
    """Create aiohttp middleware for security checks.

    ``tunnel_identity_resolver`` returns the validated visitor-cookie client
    id for a request (or None); ``tunnel_identity_minter`` returns a fresh
    ``(client_id, cookie_token)`` pair (or None).  Both are consulted only
    while the cloudflared tunnel is active and the peer is loopback: such
    requests key their limiter buckets on ``tunnel:<client_id>`` so one
    visitor's failures cannot lock out every tunneled user.  A request with
    no valid cookie stays in the shared loopback bucket — minting a fresh id
    must never buy an immediate isolated bucket, or attackers could rotate
    identities per request to evade limiting — and the minted cookie is
    attached to successful responses so the *next* request isolates.
    Rejection answers produced by this middleware itself (blacklist/whitelist
    403, rate-limit 429) deliberately omit the freshly minted cookie so a
    denied client cannot farm identities from failed attempts.
    """
    allowed_ips = {_normalize_ip(ip) for ip in (ip_whitelist or []) if ip}
    browse_limiter = browse_rate_limiter or rate_limiter

    @web.middleware
    async def security_middleware(request: web.Request, handler):
        path = request.path
        policy = _request_policy(request)

        # L2 tiering:
        #   auth_strict — tight login budget
        #   browse      — generous budget for heavy public browsing surfaces
        #   general     — everything else
        #   skip        — only media/status polling (image/thumbnails/stats,
        #                 revision cursor, websocket, static assets)
        skip_rate = policy.rate_limit == "skip"

        # Reject requests without a remote address rather than pooling them
        # under a shared "unknown" bucket.
        if not request.remote:
            _log.warning("Rejected request without remote address: %s %s", request.method, path)
            return error_response("Bad Request", status=400, code="bad_request")
        ip = _normalize_ip(request.remote)

        # Tunnel traffic always arrives from loopback; detect it once so both
        # the whitelist bypass and per-client limiter keys share one gate.
        tunnel_source = False
        if callable(tunnel_active):
            try:
                tunnel_on = bool(tunnel_active())
            except Exception:
                tunnel_on = False
            try:
                loopback = bool(ipaddress.ip_address(ip).is_loopback)
            except ValueError:
                loopback = False
            tunnel_source = tunnel_on and loopback

        bucket_key = ip
        identified_client: str | None = None
        if tunnel_source and callable(tunnel_identity_resolver):
            try:
                resolved_client = tunnel_identity_resolver(request)
            except Exception:
                resolved_client = None
            if isinstance(resolved_client, str) and resolved_client:
                identified_client = resolved_client
        if identified_client is not None:
            bucket_key = f"tunnel:{identified_client}"

        request[SECURITY_BUCKET_KEY] = bucket_key

        # Minting is deferred to the successful attach point: rejected
        # requests never consume a fresh identity (see contract above), and
        # the token is minted at most once per request.
        minted_token: list[str | None] = [None]

        def _attach_visitor_cookie(response: web.StreamResponse) -> web.StreamResponse:
            if (
                not tunnel_source
                or identified_client is not None
                or not isinstance(response, web.Response)
            ):
                return response
            # Never clobber an identity the route itself already issued.
            if tunnel_identity.COOKIE_NAME in getattr(response, "cookies", {}):
                return response
            if minted_token[0] is None and callable(tunnel_identity_minter):
                try:
                    candidate = tunnel_identity_minter()
                except Exception:
                    candidate = None
                if (
                    isinstance(candidate, tuple)
                    and len(candidate) == 2
                    and isinstance(candidate[0], str)
                    and candidate[0]
                    and isinstance(candidate[1], str)
                    and candidate[1]
                ):
                    minted_token[0] = candidate[1]
            token = minted_token[0]
            if not token:
                return response
            try:
                tunnel_identity.apply_visitor_cookie(
                    response, token, secure=bool(getattr(request, "secure", False))
                )
            except Exception:
                _log.exception("Failed to attach tunnel identity cookie")
            return response

        # IP blacklist check (always applies).  Security-produced rejections
        # never carry a minted visitor cookie (identity-farming guard).
        if ip_blacklist.is_blocked(ip):
            _log.warning("Blocked request from blacklisted IP: %s", ip)
            return error_response("Forbidden", status=403, code="forbidden")

        if allowed_ips and ip not in allowed_ips:
            # Traffic arriving through the cloudflared tunnel always has a
            # loopback source address.  While the tunnel is running, let
            # loopback sources through so LAN-subnet whitelists only
            # constrain direct connections.
            if not tunnel_source:
                _log.warning("Blocked request from non-whitelisted IP: %s", ip)
                return error_response("Forbidden", status=403, code="forbidden")

        # The limiter whose remaining budget is reported on the response.
        active_limiter = rate_limiter

        # Media/status routes intentionally have no anonymous request budget,
        # but a request carrying a credential still enters the expensive
        # authentication chain (revocation lookup plus PBKDF2).  Apply a
        # separate generous limiter only to credential-bearing skip requests
        # so random-token probing cannot turn those routes into an unlimited
        # CPU/DB oracle while ordinary guest polling remains unaffected.
        if skip_rate and skip_auth_rate_limiter is not None:
            from AssetsManager.lan.routes._helpers import get_auth_token

            if get_auth_token(request):
                active_limiter = skip_auth_rate_limiter
                if not skip_auth_rate_limiter.is_allowed(bucket_key):
                    retry_after = skip_auth_rate_limiter.retry_after(bucket_key)
                    _log.warning("Credential rate limit exceeded for skip route: %s", bucket_key)
                    return error_response(
                        "Credential rate limit exceeded",
                        status=429,
                        code="auth_rate_limited",
                        details={"retry_after": retry_after},
                        extra={"retry_after": retry_after},
                        headers={"Retry-After": str(retry_after)},
                    )

        # Auth endpoint rate limiting (stricter, declared per route)
        if auth_rate_limiter and policy.rate_limit == "auth_strict":
            active_limiter = auth_rate_limiter
            if not auth_rate_limiter.is_allowed(bucket_key):
                retry_after = auth_rate_limiter.retry_after(bucket_key)
                _log.warning("Auth rate limit exceeded for IP: %s", bucket_key)
                return error_response(
                    "Too many login attempts. Please try again later.",
                    status=429,
                    code="auth_rate_limited",
                    details={"retry_after": retry_after},
                    extra={"retry_after": retry_after},
                    headers={"Retry-After": str(retry_after)},
                )

        # Browse rate limit (generous budget for heavy public surfaces)
        elif policy.rate_limit == "browse":
            active_limiter = browse_limiter
            if not browse_limiter.is_allowed(bucket_key):
                retry_after = browse_limiter.retry_after(bucket_key)
                _log.warning("Browse rate limit exceeded for IP: %s", bucket_key)
                return error_response(
                    "Browse rate limit exceeded",
                    status=429,
                    code="browse_rate_limited",
                    details={"retry_after": retry_after},
                    extra={"retry_after": retry_after},
                    headers={"Retry-After": str(retry_after)},
                )

        # General rate limit check (only for non-browsing paths)
        elif not skip_rate:
            if not rate_limiter.is_allowed(bucket_key):
                retry_after = rate_limiter.retry_after(bucket_key)
                _log.warning("Rate limit exceeded for IP: %s", bucket_key)
                return error_response(
                    "Rate limit exceeded",
                    status=429,
                    code="rate_limited",
                    details={"retry_after": retry_after},
                    extra={"retry_after": retry_after},
                    headers={"Retry-After": str(retry_after)},
                )

        # Add rate limit headers
        response = await handler(request)
        if isinstance(response, web.Response):
            remaining = active_limiter.get_remaining(bucket_key)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
        return _attach_visitor_cookie(response)

    return security_middleware
