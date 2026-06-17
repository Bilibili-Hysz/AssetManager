"""Auth domain — pure cryptographic utilities.

These functions have no infrastructure dependencies (no SQLite, no file I/O).
They are the single source of truth for password hashing, key hashing, and
token generation/verification used by both the application layer and the LAN
layer.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time


# ── Key-based auth ────────────────────────────────────────────

def generate_access_key() -> str:
    """Generate a random 32-character access key (128 bits of entropy)."""
    return os.urandom(16).hex()


def hash_key(key: str) -> str:
    """Hash an access key for storage."""
    salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", key.encode(), salt, 50_000)
    return salt.hex() + ":" + h.hex()


def verify_key(key: str, stored_hash: str) -> bool:
    """Verify an access key against stored hash."""
    try:
        salt_hex, h_hex = stored_hash.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(h_hex)
        actual = hashlib.pbkdf2_hmac("sha256", key.encode(), salt, 50_000)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


# ── Password hashing ──────────────────────────────────────────

def hash_password(password: str) -> str:
    """Hash a password with PBKDF2-SHA256. Returns 'salt_hex:key_hex'."""
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return salt.hex() + ":" + key.hex()


def is_password_hash(value: str) -> bool:
    """Return True if *value* looks like a PBKDF2 hash (hex_salt:hex_key)."""
    parts = value.split(":")
    if len(parts) != 2:
        return False
    salt_hex, key_hex = parts
    if len(salt_hex) != 64 or len(key_hex) != 64:
        return False
    try:
        bytes.fromhex(salt_hex)
        bytes.fromhex(key_hex)
        return True
    except ValueError:
        return False


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored hash."""
    try:
        salt_hex, key_hex = stored_hash.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(key_hex)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


# ── Simple token (for single-password mode) ───────────────────

def generate_token(password_hash: str) -> str:
    """Generate a simple time-based token. Valid for 24 hours."""
    ts = str(int(time.time()))
    sig = hmac.new(password_hash.encode(), ts.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{ts}.{sig}"


def verify_token(token: str, password_hash: str) -> bool:
    """Verify a token is valid and not expired."""
    try:
        ts_str, sig = token.split(".", 1)
        ts = int(ts_str)
        if time.time() - ts > 86400:
            return False
        expected = hmac.new(password_hash.encode(), ts_str.encode(), hashlib.sha256).hexdigest()[:32]
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


def verify_auth_token(token: str, secret: str) -> bool:
    """Verify a local UI API token signed with token_secret.

    Token format: "timestamp.hmac-sha256(timestamp,secret)[:32]"
    Valid for 24 hours.
    """
    try:
        ts_str, sig = token.split(".", 1)
        ts = int(ts_str)
        if time.time() - ts > 86400:
            return False
        expected = hmac.new(secret.encode(), ts_str.encode(), hashlib.sha256).hexdigest()[:32]
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


# ── User token ────────────────────────────────────────────────

def generate_user_token(user_id: int, username: str, role: str, secret: str) -> str:
    """Generate a signed user token. Valid for 24 hours."""
    ts = str(int(time.time()))
    payload = f"{ts}.{user_id}.{username}.{role}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{ts}.{user_id}.{sig}"


def verify_user_token(token: str, secret: str, user_info: dict | None = None) -> dict | None:
    """Verify a user token and return user info, or None if invalid.

    ``user_info`` is a dict with at least ``id``, ``username``, ``role``,
    and ``is_active`` keys — typically fetched from ``AuthRepository``.
    The DB query is the caller's responsibility so the domain layer stays
    infrastructure-free.
    """
    try:
        parts = token.split(".", 2)
        if len(parts) != 3:
            return None
        ts_str, user_id_str, sig = parts
        ts = int(ts_str)
        if time.time() - ts > 86400:
            return None
        user_id = int(user_id_str)
        if user_info is None:
            return None
        if not user_info.get("is_active"):
            return None
        if int(user_info.get("id", -1)) != user_id:
            return None
        username = user_info["username"]
        role = user_info["role"]
        payload = f"{ts}.{user_id}.{username}.{role}"
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, expected):
            return None
        return {"id": user_id, "username": username, "role": role}
    except Exception:
        return None


# ── Share token ───────────────────────────────────────────────

def generate_share_token(share_id: str, secret: str) -> str:
    """Generate a signed share access token. Valid for 1 hour."""
    ts = str(int(time.time()))
    message = f"{ts}.{share_id}"
    sig = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{ts}.{sig}"


def verify_share_token(token: str, share_id: str, secret: str) -> bool:
    """Verify a share access token."""
    try:
        ts_str, sig = token.split(".", 1)
        ts = int(ts_str)
        if time.time() - ts > 3600:
            return False
        message = f"{ts_str}.{share_id}"
        expected = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()[:32]
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


# ── Password strength validation ──────────────────────────────

def validate_password_strength(password: str) -> str | None:
    """Validate password strength. Returns error message or None if valid.

    Requirements:
    - At least 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character (!@#$%^&*()_+-=[]{}|;:,.<>?)
    """
    if not password:
        return "Password is required"

    if len(password) < 8:
        return "Password must be at least 8 characters"

    if len(password) > 128:
        return "Password must be less than 128 characters"

    weak_passwords = {
        "password", "12345678", "qwerty123", "admin123", "letmein",
        "welcome1", "monkey123", "dragon12", "master12", "abc12345",
    }
    if password.lower() in weak_passwords:
        return "Password is too common. Please choose a stronger password"

    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_special = any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password)

    missing = []
    if not has_upper:
        missing.append("uppercase letter")
    if not has_lower:
        missing.append("lowercase letter")
    if not has_digit:
        missing.append("digit")
    if not has_special:
        missing.append("special character")

    if missing:
        return f"Password must contain at least one {', '.join(missing)}"

    return None
