"""LAN module shared utilities.

Provides common functions used across multiple lan/ files to reduce code duplication.
"""
import hashlib
import hmac
import logging
import secrets
import socket
import threading
import time

_log = logging.getLogger(__name__)

_VIRTUAL_IFACE_MARKERS = (
    "loopback", "virtual", "vmnet", "vbox", "docker", "wsl", "vether",
    "vpn", "tun", "tap", "tailscale", "zerotier", "hamachi", "wireguard",
    "vmware", "npcap", "bluetooth", "pseudo", "isatap", "ppp",
)


def _is_fake_ip_or_benchmark(ip: str) -> bool:
    """True for RFC 2544 benchmark space 198.18.0.0/15.

    TUN-mode proxy clients (Clash fake-ip) assign addresses from this
    reserved range to their virtual adapter and route the default route
    through it. Such an address is never a reachable LAN address, so it
    must not be reported as the share URL host or the local IP.
    """
    return ip.startswith("198.18.") or ip.startswith("198.19.")


def _is_private_ipv4(ip: str) -> bool:
    if ip.startswith("127.") or ip.startswith("169.254.") or ip.startswith("0."):
        return False
    if _is_fake_ip_or_benchmark(ip):
        return False
    if ip.startswith("10.") or ip.startswith("192.168."):
        return True
    if ip.startswith("172."):
        parts = ip.split(".")
        if len(parts) >= 2 and parts[1].isdigit():
            return 16 <= int(parts[1]) <= 31
    return False


def _is_virtual_interface(name: str) -> bool:
    lowered = name.lower()
    return any(marker in lowered for marker in _VIRTUAL_IFACE_MARKERS)


def _default_route_ip() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            if not ip.startswith("127.") and not _is_fake_ip_or_benchmark(ip):
                return ip
        finally:
            s.close()
    except Exception:
        pass
    return None


def _enumerate_private_ips(timeout: float = 2.0) -> list[tuple[str, str]]:
    """List (name, ip) pairs for interfaces with a private IPv4 address.

    ``socket.gethostbyname`` performs a resolver lookup for each interface
    name, which can block indefinitely on some systems; run it in a
    daemon thread and return whatever completed before the timeout so
    callers (including async route handlers) never hang.
    """
    interfaces: list[tuple[str, str]] = []

    def _run() -> None:
        try:
            for _index, name in socket.if_nameindex():
                try:
                    ip = socket.gethostbyname(name)
                except OSError:
                    continue
                if _is_private_ipv4(ip):
                    interfaces.append((name, ip))
        except Exception:
            pass

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    worker.join(timeout)
    return interfaces


_local_ip_cache: str | None = None


def get_local_ip() -> str:
    """Get the local LAN IP address.

    Prefers the default-route interface when it belongs to a physical
    adapter; otherwise returns the first private address from a
    non-virtual interface. Falls back to loopback only when nothing else
    is available. The result is cached for the process lifetime; callers
    include async route handlers, and interface enumeration can take up
    to the resolve timeout on some systems.
    """
    global _local_ip_cache
    if _local_ip_cache is not None:
        if not _is_fake_ip_or_benchmark(_local_ip_cache):
            return _local_ip_cache
        # A stale fake-ip value may have been cached by an earlier call
        # (pre-fix) or by a TUN adapter flip; re-resolve instead of
        # reporting a virtual address as the LAN IP.
        _local_ip_cache = None

    interfaces = _enumerate_private_ips()

    default_ip = _default_route_ip()
    if default_ip is not None:
        for name, ip in interfaces:
            if ip == default_ip and not _is_virtual_interface(name):
                _local_ip_cache = ip
                return ip
    for name, ip in interfaces:
        if not _is_virtual_interface(name):
            _local_ip_cache = ip
            return ip
    if default_ip is not None:
        _local_ip_cache = default_ip
        return default_ip
    # Loopback is a degraded fallback (e.g. network not ready yet); do not
    # cache it so a later call can still resolve the real interface.
    return "127.0.0.1"


def generate_auth_token(token_secret: str) -> str:
    """Generate a simple auth token for API requests.

    This token is used by the Qt client to authenticate with the local
    server. It's a time-based token that expires after 24 hours and
    carries a random nonce so two tokens minted within the same second
    are never identical.

    Args:
        token_secret: The server's token secret for signing

    Returns:
        A token string in format "timestamp.nonce.signature"
    """
    ts = str(int(time.time()))
    nonce = secrets.token_hex(4)
    message = f"{ts}.{nonce}"
    sig = hmac.new(token_secret.encode(), message.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{ts}.{nonce}.{sig}"


def get_auth_headers(token_secret: str) -> dict:
    """Get HTTP headers with auth token for API requests.

    Args:
        token_secret: The server's token secret for signing

    Returns:
        Dict with Authorization header
    """
    token = generate_auth_token(token_secret)
    return {"Authorization": f"Bearer {token}"}
