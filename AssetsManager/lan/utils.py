"""LAN module shared utilities.

Provides common functions used across multiple lan/ files to reduce code duplication.
"""
import hashlib
import hmac
import logging
import socket
import time

_log = logging.getLogger(__name__)


def get_local_ip() -> str:
    """Get the local LAN IP address.

    Returns the IP address of the network interface that would be used
    to reach the internet (8.8.8.8). Falls back to 127.0.0.1 on failure.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            return ip
        finally:
            s.close()
    except Exception:
        return "127.0.0.1"


def generate_auth_token(token_secret: str) -> str:
    """Generate a simple auth token for API requests.

    This token is used by the Qt client to authenticate with the local
    server. It's a time-based token that expires after 24 hours.

    Args:
        token_secret: The server's token secret for signing

    Returns:
        A token string in format "timestamp.signature"
    """
    ts = str(int(time.time()))
    sig = hmac.new(token_secret.encode(), ts.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{ts}.{sig}"


def get_auth_headers(token_secret: str) -> dict:
    """Get HTTP headers with auth token for API requests.

    Args:
        token_secret: The server's token secret for signing

    Returns:
        Dict with Authorization header
    """
    token = generate_auth_token(token_secret)
    return {"Authorization": f"Bearer {token}"}
