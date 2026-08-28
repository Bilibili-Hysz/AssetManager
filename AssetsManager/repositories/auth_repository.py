"""Auth repository — CRUD operations for users and invite codes.

Encapsulates all authentication-related database operations behind
a clean interface. Token and password hashing remain in domain.auth
as pure functions.
"""
from __future__ import annotations

import logging
import threading
import sqlite3
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from sqlite3 import Connection
from typing import Any, Callable, TypeVar

from AssetsManager.core.database import DatabaseManager, db_write_lock, locked_read
from AssetsManager.core.path_resolver import RootIdentity, root_identity
from AssetsManager.core.schema_defs import validate_schema_objects
from AssetsManager.core.schema_defs import INVITE_CODES_SCHEMA, USERS_SCHEMA
from AssetsManager.repositories._common import _guarded_commit

_log = logging.getLogger(__name__)

# Compatibility aliases: schema ownership lives in core.schema_defs / migration v6.


class InviteCodeLookupError(RuntimeError):
    """Raised when invite-code availability cannot be determined safely."""


def _rollback_safely(conn: Connection) -> None:
    """Best-effort rollback that never masks the original failure."""
    try:
        conn.rollback()
    except Exception:
        _log.debug("Rollback after auth repository failure was unavailable", exc_info=True)


_R = TypeVar("_R")


def _repository_operation(method: Callable[..., _R]) -> Callable[..., _R]:
    @wraps(method)
    def wrapped(self: Any, *args: Any, **kwargs: Any) -> _R:
        with self._operation_scope():
            return method(self, *args, **kwargs)

    return wrapped


def _session_root(session: Any, repository_name: str) -> str | Path | RootIdentity:
    root = getattr(session, "root", None)
    if root is None:
        root = getattr(session, "root_str", None)
    if root is None:
        raise TypeError(
            f"{repository_name} canonical session requires root or root_str"
        )
    return root


def _require_session_contract(
    session: Any, repository_name: str
) -> tuple[Callable[..., Any], Callable[..., Any]]:
    operation = getattr(session, "operation", None)
    if not callable(operation):
        raise TypeError(
            f"{repository_name} canonical session requires callable operation()"
        )
    connection_for = getattr(session, "connection_for", None)
    if not callable(connection_for):
        raise TypeError(
            f"{repository_name} canonical session requires callable connection_for()"
        )
    return operation, connection_for


class AuthRepository:
    """Encapsulates users and invite_codes table operations."""

    def __init__(
        self,
        conn: Connection,
        *,
        library_root: str | Path | RootIdentity | None = None,
        session: Any | None = None,
    ):
        self._conn = conn
        self._session: Any | None = None
        self._library_root_key: str | None = None
        self._binding_lock = threading.RLock()
        if library_root is not None:
            identity = root_identity(library_root, strict=False)
            self._library_root_key = identity.map_key
            DatabaseManager.validate_connection_owner(
                identity, conn, allow_unmanaged=True
            )
        if session is not None:
            self._bind_session(session, library_root=library_root)

    @classmethod
    def for_session(cls, session: Any) -> "AuthRepository":
        """Build a strictly session/root-bound repository for a canonical session."""
        operation, connection_for = _require_session_contract(session, "AuthRepository")
        with operation():
            root = _session_root(session, "AuthRepository")
            conn = connection_for(root)
            conn = DatabaseManager.require_managed_connection_owner(root, conn)
            repository = cls(conn)
            repository._bind_session(session, library_root=root)
            return repository

    @contextmanager
    def _operation_scope(self):
        if self._session is None:
            yield
            return
        with self._session.operation():
            yield

    def _bind_session(
        self, session: Any, *, library_root: str | Path | RootIdentity | None = None
    ) -> None:
        with self._binding_lock:
            if self._session is not None:
                if self._session is session:
                    return
                raise RuntimeError(
                    "AuthRepository is already bound to another LibrarySession"
                )

            operation, connection_for = _require_session_contract(
                session, "AuthRepository"
            )
            session_root = _session_root(session, "AuthRepository")
            session_identity = root_identity(session_root, strict=False)
            if library_root is not None:
                explicit_identity = root_identity(library_root, strict=False)
                if explicit_identity.map_key != session_identity.map_key:
                    raise ValueError(
                        "AuthRepository library_root does not match the LibrarySession"
                    )
            if (
                self._library_root_key is not None
                and self._library_root_key != session_identity.map_key
            ):
                raise ValueError("AuthRepository belongs to a different library root")

            with operation():
                conn = connection_for(session_root)
                conn = DatabaseManager.require_managed_connection_owner(
                    session_identity, conn
                )
                if conn is not self._conn:
                    raise ValueError(
                        "AuthRepository connection does not belong to the LibrarySession"
                    )

                def publish_binding() -> None:
                    # `_session` is the readiness flag read by operation scopes,
                    # so publish all accompanying identity state before it.
                    self._library_root_key = session_identity.map_key
                    self._session = session

                publish_while_live = getattr(session, "_publish_while_live", None)
                if callable(publish_while_live):
                    publish_while_live(publish_binding)
                else:
                    publish_binding()

    # ── Schema ──────────────────────────────────────────────────

    @_repository_operation
    def init_tables(self) -> None:
        """Compatibility ensure for raw/legacy connections; migration v6 owns the schema."""
        with db_write_lock(self._conn):
            outer_transaction = self._conn.in_transaction
            savepoint = "auth_repository_init"
            self._conn.execute(f"SAVEPOINT {savepoint}")
            try:
                self._conn.execute(USERS_SCHEMA)
                self._conn.execute(INVITE_CODES_SCHEMA)
                validate_schema_objects(
                    self._conn, ("users", "invite_codes")
                )
                if outer_transaction:
                    self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                else:
                    self._conn.commit()
            except BaseException:
                self._conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise

    # ── Users ────────────────────────────────────────────────────

    @_repository_operation
    @locked_read
    def has_active_users(self, *, raise_on_error: bool = True) -> bool:
        """Check if there are any active users.

        The strict contract mirrors ``has_active_invite_codes``: a database
        failure must never be interpreted as "there are no users", which
        would let the LAN surface report authentication as disabled.
        ``raise_on_error`` remains accepted for API compatibility, but
        infrastructure failures always raise.
        """
        try:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM users WHERE is_active=1"
            ).fetchone()
            return (row[0] > 0) if row else False
        except Exception:
            _log.warning("has_active_users query failed", exc_info=True)
            raise

    @_repository_operation
    @locked_read
    def get_user_by_username(self, username: str) -> dict | None:
        """Get a user by username."""
        row = self._conn.execute(
            "SELECT id, username, password, email, role, is_active, created_at, "
            "can_write "
            "FROM users WHERE username=?",
            (username,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "username": row[1],
            "password_hash": row[2],
            "email": row[3],
            "role": row[4],
            "is_active": row[5],
            "created_at": row[6],
            "can_write": row[7],
        }

    @_repository_operation
    @locked_read
    def get_user_by_id(self, user_id: int) -> dict | None:
        """Get a user by ID."""
        row = self._conn.execute(
            "SELECT id, username, password, email, role, is_active, created_at, "
            "can_write "
            "FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "username": row[1],
            "password_hash": row[2],
            "email": row[3],
            "role": row[4],
            "is_active": row[5],
            "created_at": row[6],
            "can_write": row[7],
        }

    @_repository_operation
    def insert_user(self, username: str, password_hash: str,
                    email: str | None = None, role: str = "viewer") -> int | None:
        """Insert a new user. Returns user ID or None on failure."""
        try:
            with db_write_lock(self._conn):
                outer_transaction = self._conn.in_transaction
                cur = self._conn.execute(
                    "INSERT INTO users (username, password, email, role, is_active) "
                    "VALUES (?, ?, ?, ?, 1)",
                    (username, password_hash, email, role),
                )
                _guarded_commit(self._conn, outer_transaction=outer_transaction)
                return cur.lastrowid
        except sqlite3.IntegrityError:
            _rollback_safely(self._conn)
            _log.warning("insert_user rejected by a business constraint", exc_info=True)
            return None
        except (sqlite3.Error, RuntimeError):
            _rollback_safely(self._conn)
            _log.warning("insert_user failed because the database is unavailable", exc_info=True)
            raise
        except Exception:
            # Unknown failures must not be mistaken for a rejected user.
            _rollback_safely(self._conn)
            _log.warning("insert_user failed for %s", username, exc_info=True)
            raise

    @_repository_operation
    def insert_user_with_invite(
        self,
        username: str,
        password_hash: str,
        invite_code: str,
        email: str | None = None,
        role: str = "viewer",
    ) -> int | None:
        """Atomically consume an invite code and insert a user."""
        try:
            with db_write_lock(self._conn):
                outer_transaction = self._conn.in_transaction
                user_cur = self._conn.execute(
                    "INSERT INTO users (username, password, email, role, is_active) "
                    "VALUES (?, ?, ?, ?, 1)",
                    (username, password_hash, email, role),
                )
                cur = self._conn.execute(
                    "UPDATE invite_codes SET used_by=?, used_at=strftime('%s','now') "
                    "WHERE code=? AND is_active=1 AND used_by IS NULL",
                    (username, invite_code),
                )
                if cur.rowcount != 1:
                    self._conn.rollback()
                    return None
                _guarded_commit(self._conn, outer_transaction=outer_transaction)
                return user_cur.lastrowid
        except sqlite3.IntegrityError:
            _rollback_safely(self._conn)
            _log.warning("insert_user_with_invite rejected by a business constraint", exc_info=True)
            return None
        except (sqlite3.Error, RuntimeError):
            _rollback_safely(self._conn)
            _log.warning(
                "insert_user_with_invite failed because the database is unavailable",
                exc_info=True,
            )
            raise
        except Exception:
            _rollback_safely(self._conn)
            _log.warning("insert_user_with_invite failed for %s", username, exc_info=True)
            return None

    @_repository_operation
    @locked_read
    def list_users(self, include_password: bool = False) -> list[dict]:
        """List all users."""
        rows = self._conn.execute(
            "SELECT id, username, password, email, role, is_active, created_at, "
            "can_write FROM users"
        ).fetchall()
        result = []
        for r in rows:
            d = {"id": r[0], "username": r[1], "email": r[3], "role": r[4], "is_active": r[5], "created_at": r[6], "can_write": r[7]}
            if include_password:
                d["password_hash"] = r[2]
            result.append(d)
        return result

    @_repository_operation
    def set_user_active(self, user_id: int, active: bool) -> bool:
        """Activate or deactivate a user. Returns True if updated."""
        with db_write_lock(self._conn):
            outer_transaction = self._conn.in_transaction
            cur = self._conn.execute(
                "UPDATE users SET is_active=? WHERE id=?",
                (1 if active else 0, user_id),
            )
            _guarded_commit(self._conn, outer_transaction=outer_transaction)
            return cur.rowcount > 0

    @_repository_operation
    def set_user_can_write(self, user_id: int, enabled: bool) -> bool:
        """Enable or disable per-user metadata/tag write access. Returns True if updated."""
        with db_write_lock(self._conn):
            outer_transaction = self._conn.in_transaction
            cur = self._conn.execute(
                "UPDATE users SET can_write=? WHERE id=?",
                (1 if enabled else 0, user_id),
            )
            _guarded_commit(self._conn, outer_transaction=outer_transaction)
            return cur.rowcount > 0

    @_repository_operation
    def set_user_password_hash(self, user_id: int, password_hash: str) -> bool:
        """Replace a user's stored password hash. Returns True if updated.

        Used by the cost-migration path after a successful login, so an
        existing account moves to the current PBKDF2 cost without asking the
        user to change their password.
        """
        with db_write_lock(self._conn):
            outer_transaction = self._conn.in_transaction
            cur = self._conn.execute(
                "UPDATE users SET password=? WHERE id=?",
                (password_hash, user_id),
            )
            _guarded_commit(self._conn, outer_transaction=outer_transaction)
            return cur.rowcount > 0

    # ── Invite codes ─────────────────────────────────────────────

    @_repository_operation
    def insert_invite_code(self, code: str, created_by: str = "admin") -> bool:
        """Insert a new invite code. Returns True on success."""
        try:
            with db_write_lock(self._conn):
                outer_transaction = self._conn.in_transaction
                self._conn.execute(
                    "INSERT INTO invite_codes (code, created_by, is_active) "
                    "VALUES (?, ?, 1)",
                    (code, created_by),
                )
                _guarded_commit(self._conn, outer_transaction=outer_transaction)
            return True
        except sqlite3.IntegrityError:
            _rollback_safely(self._conn)
            _log.warning("insert_invite_code rejected by a business constraint", exc_info=True)
            return False
        except (sqlite3.Error, RuntimeError):
            _rollback_safely(self._conn)
            _log.warning("insert_invite_code failed because the database is unavailable", exc_info=True)
            raise
        except Exception:
            # Unknown failures must not be mistaken for a rejected invite code.
            _rollback_safely(self._conn)
            _log.warning("insert_invite_code failed", exc_info=True)
            raise

    @_repository_operation
    @locked_read
    def get_invite_code(self, code: str) -> dict | None:
        """Get an invite code by code string."""
        row = self._conn.execute(
            "SELECT code, created_by, created_at, is_active FROM invite_codes WHERE code=?",
            (code,),
        ).fetchone()
        if not row:
            return None
        return {"code": row[0], "created_by": row[1], "created_at": row[2], "is_active": row[3]}

    @_repository_operation
    @locked_read
    def list_invite_codes(self) -> list[dict]:
        """List all invite codes."""
        rows = self._conn.execute(
            "SELECT code, created_by, created_at, is_active FROM invite_codes ORDER BY created_at DESC"
        ).fetchall()
        return [
            {"code": r[0], "created_by": r[1], "created_at": r[2], "is_active": r[3]}
            for r in rows
        ]

    @_repository_operation
    def deactivate_invite_code(self, code: str) -> bool:
        """Deactivate an invite code. Returns True if updated."""
        with db_write_lock(self._conn):
            outer_transaction = self._conn.in_transaction
            cur = self._conn.execute(
                "UPDATE invite_codes SET is_active=0 WHERE code=?",
                (code,),
            )
            _guarded_commit(self._conn, outer_transaction=outer_transaction)
            return cur.rowcount > 0

    @_repository_operation
    @locked_read
    def verify_invite_code(self, code: str) -> bool:
        """Check if an invite code is valid and unused."""
        row = self._conn.execute(
            "SELECT is_active, used_by FROM invite_codes WHERE code=?", (code,)
        ).fetchone()
        if not row:
            return False
        is_active, used_by = row
        return bool(is_active) and used_by is None

    @_repository_operation
    def consume_invite_code(self, code: str, username: str) -> bool:
        """Mark an invite code as used by the given username."""
        try:
            with db_write_lock(self._conn):
                outer_transaction = self._conn.in_transaction
                cur = self._conn.execute(
                    "UPDATE invite_codes SET used_by=?, used_at=strftime('%s','now') "
                    "WHERE code=? AND is_active=1 AND used_by IS NULL",
                    (username, code)
                )
                _guarded_commit(self._conn, outer_transaction=outer_transaction)
            return cur.rowcount == 1
        except sqlite3.IntegrityError:
            _rollback_safely(self._conn)
            return False
        except (sqlite3.Error, RuntimeError):
            _rollback_safely(self._conn)
            raise
        except Exception:
            _rollback_safely(self._conn)
            return False

    @_repository_operation
    @locked_read
    def has_active_invite_codes(self, *, raise_on_error: bool = True) -> bool:
        """Check if there are any active unused invite codes.

        The strict contract prevents database failures from being interpreted
        as "there are no invite codes", which would allow registration to
        proceed without an invite. ``raise_on_error`` remains accepted for API
        compatibility, but infrastructure failures always raise.
        """
        try:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM invite_codes WHERE is_active=1 AND used_by IS NULL"
            ).fetchone()
            return (row[0] > 0) if row else False
        except sqlite3.Error as exc:
            _log.warning("has_active_invite_codes query failed", exc_info=True)
            raise InviteCodeLookupError(
                "Unable to determine whether invite codes are required"
            ) from exc
