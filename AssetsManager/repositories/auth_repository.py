"""Auth repository — CRUD operations for users and invite codes.

Encapsulates all authentication-related database operations behind
a clean interface. Token and password hashing remain in domain.auth
as pure functions.
"""
from __future__ import annotations

import logging
from sqlite3 import Connection

from AssetsManager.core.database import db_write_lock

_log = logging.getLogger(__name__)

USERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT UNIQUE NOT NULL,
    password    TEXT NOT NULL,
    email       TEXT,
    role        TEXT DEFAULT 'viewer',
    created_at  REAL DEFAULT (strftime('%s','now')),
    last_login  REAL,
    is_active   INTEGER DEFAULT 1
);
"""

INVITE_CODES_SCHEMA = """
CREATE TABLE IF NOT EXISTS invite_codes (
    code        TEXT PRIMARY KEY,
    created_by  TEXT,
    used_by     TEXT,
    created_at  REAL DEFAULT (strftime('%s','now')),
    used_at     REAL,
    is_active   INTEGER DEFAULT 1
);
"""


class AuthRepository:
    """Encapsulates users and invite_codes table operations."""

    def __init__(self, conn: Connection):
        self._conn = conn

    # ── Schema ──────────────────────────────────────────────────

    def init_tables(self) -> None:
        """Create users and invite_codes tables if they don't exist."""
        with db_write_lock(self._conn):
            self._conn.execute(USERS_SCHEMA)
            self._conn.execute(INVITE_CODES_SCHEMA)
            self._conn.commit()

    # ── Users ────────────────────────────────────────────────────

    def has_active_users(self, *, raise_on_error: bool = False) -> bool:
        """Check if there are any active users."""
        try:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM users WHERE is_active=1"
            ).fetchone()
            return (row[0] > 0) if row else False
        except Exception:
            _log.warning("has_active_users query failed", exc_info=True)
            if raise_on_error:
                raise
            return False

    def get_user_by_username(self, username: str) -> dict | None:
        """Get a user by username."""
        row = self._conn.execute(
            "SELECT id, username, password, email, role, is_active, created_at "
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
        }

    def get_user_by_id(self, user_id: int) -> dict | None:
        """Get a user by ID."""
        row = self._conn.execute(
            "SELECT id, username, password, email, role, is_active, created_at "
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
        }

    def insert_user(self, username: str, password_hash: str,
                    email: str | None = None, role: str = "viewer") -> int | None:
        """Insert a new user. Returns user ID or None on failure."""
        try:
            with db_write_lock(self._conn):
                cur = self._conn.execute(
                    "INSERT INTO users (username, password, email, role, is_active) "
                    "VALUES (?, ?, ?, ?, 1)",
                    (username, password_hash, email, role),
                )
                self._conn.commit()
                return cur.lastrowid
        except Exception:
            _log.warning("insert_user failed for %s", username, exc_info=True)
            return None

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
                self._conn.commit()
                return user_cur.lastrowid
        except Exception:
            self._conn.rollback()
            _log.warning("insert_user_with_invite failed for %s", username, exc_info=True)
            return None

    def list_users(self, include_password: bool = False) -> list[dict]:
        """List all users."""
        rows = self._conn.execute(
            "SELECT id, username, password, email, role, is_active, created_at FROM users"
        ).fetchall()
        result = []
        for r in rows:
            d = {"id": r[0], "username": r[1], "email": r[3], "role": r[4], "is_active": r[5], "created_at": r[6]}
            if include_password:
                d["password_hash"] = r[2]
            result.append(d)
        return result

    def set_user_active(self, user_id: int, active: bool) -> bool:
        """Activate or deactivate a user. Returns True if updated."""
        with db_write_lock(self._conn):
            cur = self._conn.execute(
                "UPDATE users SET is_active=? WHERE id=?",
                (1 if active else 0, user_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    # ── Invite codes ─────────────────────────────────────────────

    def insert_invite_code(self, code: str, created_by: str = "admin") -> bool:
        """Insert a new invite code. Returns True on success."""
        try:
            with db_write_lock(self._conn):
                self._conn.execute(
                    "INSERT INTO invite_codes (code, created_by, is_active) "
                    "VALUES (?, ?, 1)",
                    (code, created_by),
                )
                self._conn.commit()
            return True
        except Exception:
            _log.warning("insert_invite_code failed", exc_info=True)
            return False

    def get_invite_code(self, code: str) -> dict | None:
        """Get an invite code by code string."""
        row = self._conn.execute(
            "SELECT code, created_by, created_at, is_active FROM invite_codes WHERE code=?",
            (code,),
        ).fetchone()
        if not row:
            return None
        return {"code": row[0], "created_by": row[1], "created_at": row[2], "is_active": row[3]}

    def list_invite_codes(self) -> list[dict]:
        """List all invite codes."""
        rows = self._conn.execute(
            "SELECT code, created_by, created_at, is_active FROM invite_codes ORDER BY created_at DESC"
        ).fetchall()
        return [
            {"code": r[0], "created_by": r[1], "created_at": r[2], "is_active": r[3]}
            for r in rows
        ]

    def deactivate_invite_code(self, code: str) -> bool:
        """Deactivate an invite code. Returns True if updated."""
        with db_write_lock(self._conn):
            cur = self._conn.execute(
                "UPDATE invite_codes SET is_active=0 WHERE code=?",
                (code,),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def verify_invite_code(self, code: str) -> bool:
        """Check if an invite code is valid and unused."""
        row = self._conn.execute(
            "SELECT is_active, used_by FROM invite_codes WHERE code=?", (code,)
        ).fetchone()
        if not row:
            return False
        is_active, used_by = row
        return bool(is_active) and used_by is None

    def consume_invite_code(self, code: str, username: str) -> bool:
        """Mark an invite code as used by the given username."""
        try:
            with db_write_lock(self._conn):
                cur = self._conn.execute(
                    "UPDATE invite_codes SET used_by=?, used_at=strftime('%s','now') "
                    "WHERE code=? AND is_active=1 AND used_by IS NULL",
                    (username, code)
                )
                self._conn.commit()
            return cur.rowcount == 1
        except Exception:
            return False

    def has_active_invite_codes(self) -> bool:
        """Check if there are any active unused invite codes."""
        try:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM invite_codes WHERE is_active=1 AND used_by IS NULL"
            ).fetchone()
            return (row[0] > 0) if row else False
        except Exception:
            return False
