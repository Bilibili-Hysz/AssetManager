"""LAN authentication application service."""
from __future__ import annotations

import hashlib
import logging
import secrets
import threading
import time
from sqlite3 import Connection
from typing import TYPE_CHECKING

from AssetsManager.application.context import session_operation

from AssetsManager.domain import auth as auth_crypto
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import InviteChanged, UserChanged
from AssetsManager.repositories.auth_repository import AuthRepository
from AssetsManager.repositories.revoked_token_repository import RevokedTokenRepository

_log = logging.getLogger(__name__)
_MISSING_PROVIDER = object()

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
        self._session = None
        self._repo = AuthRepository(db_conn)
        self._binding_lock = threading.RLock()
        self._event_bus = get_event_bus()
        self._library_root = ""
        self._session_token = ""
        # Per-user record cache: token verification runs on every
        # authenticated request, so the is_active/role lookup is cached
        # briefly. Mutations (register/activate/deactivate) clear it; the
        # TTL caps staleness for role edits made through the repository.
        self._user_cache: dict[int, tuple[float, dict | None]] = {}
        self._user_cache_lock = threading.RLock()
        self._user_cache_ttl = 5.0
        # Persistent token revocation lives in the library DB so revoked
        # simple-password tokens cannot resurrect after an app restart.
        self._revoked_repo: RevokedTokenRepository | None = None
        if session is not None:
            self._bind_session(session)

    def _bind_session(self, session: LibrarySession) -> None:
        with self._binding_lock:
            if self._session is not None:
                if self._session is session:
                    return
                raise RuntimeError(
                    "AuthService is already bound to another LibrarySession"
                )

            connection_for = getattr(session, "connection_for", _MISSING_PROVIDER)
            if connection_for is _MISSING_PROVIDER:
                # Explicit legacy compatibility: historical fake sessions omit
                # the canonical provider entirely.  Malformed provider values
                # must not silently downgrade into this raw compatibility path.
                if not callable(getattr(session, "operation", None)):
                    raise TypeError("Legacy session must provide callable operation()")
                root_value = getattr(session, "root_str", None)
                if root_value is None:
                    root_value = getattr(session, "root", None)
                if root_value is None:
                    raise TypeError("Legacy session must provide root or root_str")

                with session.operation():
                    bound_repository = AuthRepository(self._conn)
                    library_root = str(root_value)
                    session_token = getattr(session, "event_token", "")
                    self._publish_session_binding(
                        session, bound_repository, library_root, session_token
                    )
                return

            if not callable(connection_for):
                raise TypeError(
                    "Canonical LibrarySession must provide callable connection_for()"
                )
            if not callable(getattr(session, "operation", None)):
                raise TypeError("Canonical LibrarySession must provide operation()")
            requested_root = getattr(session, "root", None)
            if requested_root is None:
                requested_root = getattr(session, "root_str", None)
            if requested_root is None:
                raise TypeError("Canonical LibrarySession must provide root or root_str")

            with session.operation():
                session_connection = session.connection_for(requested_root)
                if session_connection is not self._conn:
                    raise ValueError(
                        "AuthService connection does not belong to the LibrarySession"
                    )
                bound_repository = AuthRepository.for_session(session)
                library_root = getattr(session, "root_str", str(requested_root))
                session_token = getattr(session, "event_token", "")
                self._publish_session_binding(
                    session, bound_repository, library_root, session_token
                )

    def _publish_session_binding(
        self,
        session: LibrarySession,
        repository: AuthRepository,
        library_root: str,
        session_token: str,
    ) -> None:
        def publish_binding() -> None:
            # `_session` is the readiness flag read by `session_operation`, so
            # publish every accompanying field before it.
            self._repo = repository
            self._library_root = library_root
            self._session_token = session_token
            self._session = session

        publish_while_live = getattr(session, "_publish_while_live", None)
        if callable(publish_while_live):
            publish_while_live(publish_binding)
        else:
            publish_binding()

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
    def has_active_users(self, *, raise_on_error: bool = True) -> bool:
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
            return None, "Invalid username or password"
        if not user.get("is_active"):
            return None, "Invalid username or password"
        if not auth_crypto.verify_password(password, user.get("password_hash", "")):
            return None, "Invalid username or password"
        return user, ""

    @session_operation
    def get_user_by_id(self, user_id: int) -> dict | None:
        """Return the current persisted user record for authorization rechecks."""
        return self._repo.get_user_by_id(int(user_id))

    @session_operation
    def generate_user_token(self, user_id: int, username: str, role: str) -> str:
        return auth_crypto.generate_user_token(user_id, username, role, self._secret)

    @session_operation
    def verify_user_token(self, token: str) -> dict | None:
        """Verify a user token by fetching user info from the repo.

        The per-user record (is_active/role/username) is cached briefly so
        every authenticated request does not hit SQLite; mutations clear
        the cache and the TTL caps staleness for out-of-band edits.
        """
        try:
            parts = token.split(".", 2)
            if len(parts) != 3:
                return None
            user_id = int(parts[1])
        except (ValueError, IndexError):
            return None
        hit, user_info = self._cached_user(user_id)
        if not hit:
            try:
                user_info = self._repo.get_user_by_id(user_id)
            except Exception:
                # A simple-password token ("ts.nonce.sig") shares the
                # three-part shape with a legacy user token when its nonce
                # happens to be all digits; treat any DB failure as "not a
                # user token" so the caller can fall through to password
                # verification.
                return None
            self._store_cached_user(user_id, user_info)
        verified = auth_crypto.verify_user_token(token, self._secret, user_info)
        if verified is not None:
            # The domain verifier returns only the signed identity fields;
            # carry the persisted per-user write flag forward so authorization
            # gates can see it without an extra DB round-trip. A non-None
            # verification implies user_info is a live record, but guard for
            # a cached None (unknown user) anyway.
            verified["can_write"] = int(
                bool((user_info or {}).get("can_write", 0))
            )
        return verified

    def _cached_user(self, user_id: int) -> tuple[bool, dict | None]:
        """Return (hit, record) for a cached user, or (False, None)."""
        with self._user_cache_lock:
            entry = self._user_cache.get(user_id)
            if entry is not None and (time.monotonic() - entry[0]) < self._user_cache_ttl:
                return True, entry[1]
        return False, None

    def _store_cached_user(self, user_id: int, user_info: dict | None) -> None:
        with self._user_cache_lock:
            self._user_cache[user_id] = (time.monotonic(), user_info)

    def _invalidate_user_cache(self) -> None:
        """Drop cached user records; mutations are rare, so clear all."""
        with self._user_cache_lock:
            self._user_cache.clear()

    # ── Persistent token revocation ─────────────────────────────

    def _revocation_repo(self) -> RevokedTokenRepository:
        """Lazily build the persistent revocation repository."""
        if self._revoked_repo is None:
            self._revoked_repo = RevokedTokenRepository(self._conn)
        return self._revoked_repo

    def revoke_token(self, token: str, *, ttl: float = 86400.0) -> None:
        """Persist a token revocation (SHA256 digest, default TTL 24h)."""
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        self._revocation_repo().add(digest, expires_at=time.time() + ttl)

    def is_token_revoked(self, token: str) -> bool:
        """Return True when an unexpired revocation row exists."""
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return self._revocation_repo().is_revoked(digest)

    def load_active_revocations(self) -> dict[str, float]:
        """Return {digest: expires_at} for all unexpired revocation rows."""
        return self._revocation_repo().load_active()

    def prune_revocations(self) -> None:
        """Delete expired revocation rows (best-effort hygiene)."""
        self._revocation_repo().prune_expired()

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
        # This lookup is security-sensitive: a database failure must not be
        # treated as an empty invite-code table and allow registration through.
        has_active_codes = self._repo.has_active_invite_codes(raise_on_error=True)
        if not invite_code and has_active_codes:
            return None, "Invite code is required"

        existing = self._repo.get_user_by_username(username)
        if existing:
            return None, "Registration failed"

        pw_hash = auth_crypto.hash_password(password)
        if invite_code:
            user_id = self._repo.insert_user_with_invite(username, pw_hash, invite_code, email=email)
            if user_id is None:
                return None, "Invalid or already used invite code"
            self._invalidate_user_cache()
            self._publish(UserChanged)
            self._publish(InviteChanged)
            return user_id, ""

        user_id = self._repo.insert_user(username, pw_hash, email=email)
        if user_id is None:
            return None, "Failed to create user"

        self._invalidate_user_cache()
        self._publish(UserChanged)
        return user_id, ""

    @session_operation
    def list_users(self) -> list[dict]:
        return self._repo.list_users()

    @session_operation
    def activate_user(self, user_id: int) -> bool:
        ok = self._repo.set_user_active(user_id, True)
        if ok:
            self._invalidate_user_cache()
            self._publish(UserChanged)
        return ok

    @session_operation
    def deactivate_user(self, user_id: int) -> bool:
        ok = self._repo.set_user_active(user_id, False)
        if ok:
            self._invalidate_user_cache()
            self._publish(UserChanged)
        return ok

    @session_operation
    def get_user_by_username(self, username: str) -> dict | None:
        return self._repo.get_user_by_username(username)

    @session_operation
    def set_user_can_write(self, username: str, enabled: bool) -> bool:
        """Enable or disable per-user metadata/tag write access by username."""
        user = self._repo.get_user_by_username(username)
        if user is None:
            return False
        ok = self._repo.set_user_can_write(int(user["id"]), enabled)
        if ok:
            self._invalidate_user_cache()
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
