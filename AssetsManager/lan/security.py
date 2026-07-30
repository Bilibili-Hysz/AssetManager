"""Security middleware — rate limiting, IP blacklist, request logging."""
import logging
import time
from collections import OrderedDict, defaultdict

from aiohttp import web

_log = logging.getLogger(__name__)


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
        reqs = self._requests.get(ip, [])
        active = sum(1 for t in reqs if t > cutoff)
        return max(0, self._max - active)


class AuthRateLimiter(RateLimiter):
    """Stricter rate limiter for authentication endpoints."""

    def __init__(self, max_attempts: int = 10, window_seconds: int = 300, max_ips: int = 5000):
        super().__init__(max_requests=max_attempts, window_seconds=window_seconds, max_ips=max_ips)


class IPBlacklist:
    """Simple IP blacklist loaded from a file."""

    def __init__(self):
        self._blocked: set[str] = set()

    def load_from_settings(self, blocked_list: list[str]):
        self._blocked = set(blocked_list)

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
):
    """Create aiohttp middleware for security checks."""
    allowed_ips = set(ip_whitelist or [])

    # Paths that don't count toward rate limits (read-only browsing)
    _RATE_LIMIT_SKIP = (
        "/ws",
        "/api/thumbnails/",
        "/api/files",
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
    )

    @web.middleware
    async def security_middleware(request: web.Request, handler):
        path = request.path

        # Skip rate limiting for browsing/thumbnail paths
        skip_rate = (
            any(_path_matches_prefix(path, p) for p in _RATE_LIMIT_SKIP_PREFIX)
            or path in _RATE_LIMIT_SKIP
            or path.startswith("/api/thumbnails/")
        )

        # Get client IP
        ip = request.remote or "unknown"

        # IP blacklist check (always applies)
        if ip_blacklist.is_blocked(ip):
            _log.warning("Blocked request from blacklisted IP: %s", ip)
            return web.json_response({"error": "Forbidden"}, status=403)

        if allowed_ips and ip not in allowed_ips:
            _log.warning("Blocked request from non-whitelisted IP: %s", ip)
            return web.json_response({"error": "Forbidden"}, status=403)

        # Auth endpoint rate limiting (stricter)
        is_auth_endpoint = path in _AUTH_ENDPOINTS or (
            path.startswith("/api/shares/") and path.endswith("/verify")
        )
        if auth_rate_limiter and is_auth_endpoint:
            if not auth_rate_limiter.is_allowed(ip):
                remaining = auth_rate_limiter.get_remaining(ip)
                _log.warning("Auth rate limit exceeded for IP: %s", ip)
                return web.json_response(
                    {"error": "Too many login attempts. Please try again later.", "retry_after": 300},
                    status=429,
                    headers={"Retry-After": "300"}
                )

        # General rate limit check (only for non-browsing paths)
        elif not skip_rate:
            if not rate_limiter.is_allowed(ip):
                remaining = rate_limiter.get_remaining(ip)
                _log.warning("Rate limit exceeded for IP: %s", ip)
                return web.json_response(
                    {"error": "Rate limit exceeded", "retry_after": 5},
                    status=429,
                    headers={"Retry-After": "5"}
                )

        # Add rate limit headers
        response = await handler(request)
        if isinstance(response, web.Response):
            remaining = rate_limiter.get_remaining(ip)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response

    return security_middleware
