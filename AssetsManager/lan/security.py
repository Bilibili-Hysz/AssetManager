"""Security middleware — rate limiting, IP blacklist, request logging.

Rate limiting is IP-scoped and counts requests up front (brute force must be
throttled before the fact); under NAT, many users sharing one IP share one
budget — an accepted trade-off over failure-count or per-username limiting.

The IP whitelist applies to direct connections: cloudflared tunnel traffic
always originates from the loopback address 127.0.0.1, and while the tunnel
is running loopback sources are allowed automatically, so LAN-subnet
whitelists only constrain direct traffic.
"""
import ipaddress
import logging
import math
import time
from collections import OrderedDict, defaultdict
from collections.abc import Callable

from aiohttp import web

_log = logging.getLogger(__name__)


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
    if addr.version == 6 and addr.ipv4_mapped is not None:
        return str(addr.ipv4_mapped)
    if addr.version == 6 and addr == ipaddress.ip_address("::1"):
        return "127.0.0.1"
    return str(addr)


def _path_matches_prefix(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(f"{prefix}/")


class RateLimiter:
    """Per-IP rate limiter using sliding window with LRU eviction."""

    def __init__(self, max_requests: int = 1000, window_seconds: int = 60, max_ips: int = 10000):
        self._max = max_requests
        self._window = window_seconds
        self._max_ips = max_ips
        self._requests: dict[str, list[float]] = defaultdict(list)
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
            reqs.pop(0)
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
            reqs.pop(0)
        return max(0, self._max - len(reqs))

    def retry_after(self, ip: str) -> int:
        """Seconds until the oldest request leaves the window (min 1)."""
        reqs = self._requests.get(ip)
        if not reqs:
            return 1
        oldest = min(reqs)
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

    def block(self, ip: str):
        self._blocked.add(ip)

    def unblock(self, ip: str):
        self._blocked.discard(ip)

    @property
    def blocked_ips(self) -> list[str]:
        return list(self._blocked)


# ── Middleware factory ────────────────────────────────────────

def create_security_middleware(
    rate_limiter: RateLimiter,
    ip_blacklist: IPBlacklist,
    auth_rate_limiter: "AuthRateLimiter | None" = None,
    *,
    ip_whitelist: list[str] | None = None,
    tunnel_active: "Callable[[], bool] | None" = None,
):
    """Create aiohttp middleware for security checks."""
    allowed_ips = {_normalize_ip(ip) for ip in (ip_whitelist or []) if ip}

    # Paths that don't count toward rate limits (read-only browsing)
    _RATE_LIMIT_SKIP = (
        "/ws",
        "/api/thumbnails/",
        "/api/projects",
        "/api/tags",
        "/api/info",
        "/api/tunnel/status",
        "/assets",
    )
    _RATE_LIMIT_SKIP_PREFIX = ("/assets",)

    # Auth endpoints that need stricter rate limiting
    _AUTH_ENDPOINTS = (
        "/api/auth/login",
        "/api/auth/register",
        "/api/auth/verify_key",
        "/api/auth/seller-login",
        "/api/shop/auth/login",
    )

    @web.middleware
    async def security_middleware(request: web.Request, handler):
        path = request.path

        # Skip rate limiting for browsing/thumbnail paths
        skip_rate = (
            any(_path_matches_prefix(path, p) for p in _RATE_LIMIT_SKIP_PREFIX)
            or path in _RATE_LIMIT_SKIP
            or (request.method == "GET" and path.startswith("/api/thumbnails/"))
            or (request.method == "GET" and path == "/api/files")
        )

        # Reject requests without a remote address rather than pooling them
        # under a shared "unknown" bucket.
        if not request.remote:
            _log.warning("Rejected request without remote address: %s %s", request.method, path)
            return web.json_response({"error": "Bad Request"}, status=400)
        ip = _normalize_ip(request.remote)

        # IP blacklist check (always applies)
        if ip_blacklist.is_blocked(ip):
            _log.warning("Blocked request from blacklisted IP: %s", ip)
            return web.json_response({"error": "Forbidden"}, status=403)

        if allowed_ips and ip not in allowed_ips:
            # Traffic arriving through the cloudflared tunnel always has a
            # loopback source address.  While the tunnel is running, let
            # loopback sources through so LAN-subnet whitelists only
            # constrain direct connections.
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
            if not tunnel_source:
                _log.warning("Blocked request from non-whitelisted IP: %s", ip)
                return web.json_response({"error": "Forbidden"}, status=403)

        # Auth endpoint rate limiting (stricter)
        is_auth_endpoint = path in _AUTH_ENDPOINTS or (
            path.startswith("/api/shares/") and path.endswith("/verify")
        )
        if auth_rate_limiter and is_auth_endpoint:
            if not auth_rate_limiter.is_allowed(ip):
                retry_after = auth_rate_limiter.retry_after(ip)
                _log.warning("Auth rate limit exceeded for IP: %s", ip)
                return web.json_response(
                    {"error": "Too many login attempts. Please try again later.",
                     "retry_after": retry_after},
                    status=429,
                    headers={"Retry-After": str(retry_after)}
                )

        # General rate limit check (only for non-browsing paths)
        elif not skip_rate:
            if not rate_limiter.is_allowed(ip):
                retry_after = rate_limiter.retry_after(ip)
                _log.warning("Rate limit exceeded for IP: %s", ip)
                return web.json_response(
                    {"error": "Rate limit exceeded", "retry_after": retry_after},
                    status=429,
                    headers={"Retry-After": str(retry_after)}
                )

        # Add rate limit headers
        response = await handler(request)
        if isinstance(response, web.Response):
            remaining = rate_limiter.get_remaining(ip)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response

    return security_middleware
