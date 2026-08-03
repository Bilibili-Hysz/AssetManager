"""LAN authentication application service."""
from __future__ import annotations

import logging
import secrets
from sqlite3 import Connection
from typing import TYPE_CHECKING

from AssetsManager.application.context import session_operation

from AssetsManager.domain import auth as auth_crypto
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import InviteChanged, UserChanged
from AssetsManager.repositories.auth_repository import AuthRepository

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from AssetsManager.application.context import LibrarySession


class AuthService:
    """Wraps repository functions with explicit connection and secret management.

    Route handlers should use this service instead of calling repository
    functions directly with ``db_conn``.
    """

    def __init__(
        self,
        db_conn: Connection,
        token_secret: str,
        *,
        session: LibrarySession | None = None,
    ):
        self._conn = db_conn
        self._secret = token_secret
        self._session = session
        self._repo = AuthRepository(db_conn)
        self._event_bus = get_event_bus()
        self._library_root = (
            getattr(session, "root_str", str(getattr(session, "root", "")))
            if session is not None
            else ""
        )
        self._session_token = (
            getattr(session, "event_token", "") if session is not None else ""
        )

    def _publish(self, event_type: type) -> None:
        if self._library_root and self._session_token:
            try:
                self._event_bus.publish(event_type(
                    library_root=self._library_root,
                    session_token=self._session_token,
                ))
            except Exception:
                _log.exception("Auth projection notification failed for %s", event_type.__name__)

    @property
    def db_conn(self) -> Connection:
        return self._conn

    # ── Infrastructure ──────────────────────────────────────────

    @session_operation
    def init_tables(self) -> None:
        self._repo.init_tables()

    def invalidate_user_cache(self) -> None:
        """No-op placeholder for server-level cache invalidation."""
        pass

    @session_operation
    def has_active_users(self, *, raise_on_error: bool = False) -> bool:
        """Check if there are any active users in the database."""
        return self._repo.has_active_users(raise_on_error=raise_on_error)

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

    @session_operation
    def authenticate_user(self, username: str, password: str) -> tuple[dict | None, str]:
        user = self._repo.get_user_by_username(username)
        if not user:
            return None, "User not found"
        if not user.get("is_active"):
            return None, "User is deactivated"
        if not auth_crypto.verify_password(password, user.get("password_hash", "")):
            return None, "Invalid password"
        return user, ""

    @session_operation
    def generate_user_token(self, user_id: int, username: str, role: str) -> str:
        return auth_crypto.generate_user_token(user_id, username, role, self._secret)

    @session_operation
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

    @session_operation
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
            self._publish(UserChanged)
            self._publish(InviteChanged)
            return user_id, ""

        user_id = self._repo.insert_user(username, pw_hash, email=email)
        if user_id is None:
            return None, "Failed to create user"

        self._publish(UserChanged)
        return user_id, ""

    @session_operation
    def list_users(self) -> list[dict]:
        return self._repo.list_users()

    @session_operation
    def activate_user(self, user_id: int) -> bool:
        ok = self._repo.set_user_active(user_id, True)
        if ok:
            self._publish(UserChanged)
        return ok

    @session_operation
    def deactivate_user(self, user_id: int) -> bool:
        ok = self._repo.set_user_active(user_id, False)
        if ok:
            self._publish(UserChanged)
        return ok

    # ── Invite codes ────────────────────────────────────────────

    @session_operation
    def generate_invite_code(self, created_by: str = "admin") -> str:
        code = secrets.token_urlsafe(16)
        if self._repo.insert_invite_code(code, created_by):
            self._publish(InviteChanged)
            return code
        return ""

    @session_operation
    def list_invite_codes(self) -> list[dict]:
        return self._repo.list_invite_codes()

    @session_operation
    def revoke_invite_code(self, code: str) -> bool:
        ok = self._repo.deactivate_invite_code(code)
        if ok:
            self._publish(InviteChanged)
        return ok
