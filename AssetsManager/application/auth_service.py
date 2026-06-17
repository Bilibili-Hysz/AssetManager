"""LAN authentication application service."""
from __future__ import annotations

import logging
import secrets
import string
import time
from sqlite3 import Connection

from AssetsManager.domain import auth as auth_crypto
from AssetsManager.repositories.auth_repository import AuthRepository
from AssetsManager.repositories.share_repository import ShareRepository

_log = logging.getLogger(__name__)


class AuthService:
    """Wraps repository functions with explicit connection and secret management.

    Route handlers should use this service instead of calling repository
    functions directly with ``db_conn``.
    """

    def __init__(self, db_conn: Connection, token_secret: str):
        self._conn = db_conn
        self._secret = token_secret
        self._repo = AuthRepository(db_conn)
        self._share_repo = ShareRepository(db_conn)

    @property
    def db_conn(self) -> Connection:
        return self._conn

    @property
    def token_secret(self) -> str:
        return self._secret

    # ── Infrastructure ──────────────────────────────────────────

    def init_tables(self) -> None:
        self._repo.init_tables()

    def invalidate_user_cache(self) -> None:
        """No-op placeholder for server-level cache invalidation."""
        pass

    def has_active_users(self) -> bool:
        """Check if there are any active users in the database."""
        return self._repo.has_active_users()

    # ── Password / key hashing ──────────────────────────────────

    @staticmethod
    def hash_password(password: str) -> str:
        return auth_crypto.hash_password(password)

    @staticmethod
    def hash_key(key: str) -> str:
        return auth_crypto.hash_key(key)

    @staticmethod
    def verify_password(password: str, stored_hash: str) -> bool:
        return auth_crypto.verify_password(password, stored_hash)

    @staticmethod
    def verify_key(key: str, stored_hash: str) -> bool:
        return auth_crypto.verify_key(key, stored_hash)

    # ── Simple token (single-password mode) ─────────────────────

    def generate_token(self, password_hash: str) -> str:
        return auth_crypto.generate_token(password_hash)

    def verify_token(self, token: str, password_hash: str) -> bool:
        return auth_crypto.verify_token(token, password_hash)

    # ── User management ─────────────────────────────────────────

    def authenticate_user(self, username: str, password: str) -> tuple[dict | None, str]:
        user = self._repo.get_user_by_username(username)
        if not user:
            return None, "User not found"
        if not user.get("is_active"):
            return None, "User is deactivated"
        if not auth_crypto.verify_password(password, user.get("password_hash", "")):
            return None, "Invalid password"
        return user, ""

    def generate_user_token(self, user_id: int, username: str, role: str) -> str:
        return auth_crypto.generate_user_token(user_id, username, role, self._secret)

    def verify_user_token(self, token: str) -> dict | None:
        """Verify a user token by fetching user info from the repo."""
        try:
            parts = token.split(".", 2)
            if len(parts) != 3:
                return None
            user_id = int(parts[1])
        except (ValueError, IndexError):
            return None
        user_info = self._repo.get_user_by_id(user_id)
        return auth_crypto.verify_user_token(token, self._secret, user_info)

    def register_user(self, username: str, password: str,
                      email: str | None = None,
                      invite_code: str | None = None) -> tuple[int | None, str]:
        username = username.strip()
        if not username or len(username) < 2:
            return None, "Username must be at least 2 characters"
        if not username.isalnum() and not all(c.isalnum() or c in "_-" for c in username):
            return None, "Username can only contain letters, numbers, _ and -"

        pw_error = auth_crypto.validate_password_strength(password)
        if pw_error:
            return None, pw_error

        # Invite code logic: validate if provided, require if codes exist
        has_active_codes = self._repo.has_active_invite_codes()
        if not invite_code and has_active_codes:
            return None, "Invite code is required"

        existing = self._repo.get_user_by_username(username)
        if existing:
            return None, "Username already exists"

        pw_hash = auth_crypto.hash_password(password)
        if invite_code:
            user_id = self._repo.insert_user_with_invite(username, pw_hash, invite_code, email=email)
            if user_id is None:
                return None, "Invalid or already used invite code"
            return user_id, ""

        user_id = self._repo.insert_user(username, pw_hash, email=email)
        if user_id is None:
            return None, "Failed to create user"

        return user_id, ""

    def list_users(self) -> list[dict]:
        return self._repo.list_users()

    def activate_user(self, user_id: int) -> bool:
        return self._repo.set_user_active(user_id, True)

    def deactivate_user(self, user_id: int) -> bool:
        return self._repo.set_user_active(user_id, False)

    # ── Invite codes ────────────────────────────────────────────

    def generate_invite_code(self, created_by: str = "admin") -> str:
        code = secrets.token_urlsafe(16)
        if self._repo.insert_invite_code(code, created_by):
            return code
        return ""

    def list_invite_codes(self) -> list[dict]:
        return self._repo.list_invite_codes()

    def revoke_invite_code(self, code: str) -> bool:
        return self._repo.deactivate_invite_code(code)

    # ── Share links ─────────────────────────────────────────────

    @staticmethod
    def _generate_share_id() -> str:
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(12))

    def create_share_link(
        self,
        paths: list[str],
        password: str | None = None,
        expires_hours: int | None = None,
        max_downloads: int | None = None,
        allow_preview: bool = True,
        created_by: str | None = None,
    ) -> dict | None:
        share_id = self._generate_share_id()
        password_hash = auth_crypto.hash_password(password) if password else None
        expires_at = (time.time() + expires_hours * 3600) if expires_hours else None
        ok = self._share_repo.insert(
            share_id, paths, password_hash, expires_at,
            max_downloads, allow_preview, created_by,
        )
        if not ok:
            return None
        return self._share_repo.get(share_id)

    def get_share_link(self, share_id: str) -> dict | None:
        return self._share_repo.get(share_id)

    def list_share_links(self, created_by: str | None = None) -> list[dict]:
        return self._share_repo.list_all(created_by)

    def delete_share_link(self, share_id: str) -> bool:
        return self._share_repo.delete(share_id)

    def verify_share_password(self, share_id: str, password: str) -> bool:
        stored_hash = self._share_repo.get_password_hash(share_id)
        if not stored_hash:
            return True
        return auth_crypto.verify_password(password, stored_hash)

    def generate_share_token(self, share_id: str) -> str:
        return auth_crypto.generate_share_token(share_id, self._secret)

    def verify_share_token(self, token: str, share_id: str) -> bool:
        return auth_crypto.verify_share_token(token, share_id, self._secret)

    def increment_share_download(self, share_id: str) -> bool:
        return self._share_repo.increment_download(share_id)
