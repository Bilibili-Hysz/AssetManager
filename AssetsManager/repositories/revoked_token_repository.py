"""Persistent auth-token revocation repository.

Simple-password LAN tokens are signed with the persisted password hash and
survive app restarts; their revocations must too. Rows live in the library
database so a revoked token cannot resurrect when the in-memory revocation
table dies with the process.
"""
from __future__ import annotations

import time
from sqlite3 import Connection

from AssetsManager.core.database import db_write_lock


class RevokedTokenRepository:
    """Encapsulate the revoked_tokens table (digest -> expiry)."""

    def __init__(self, conn: Connection):
        self._conn = conn

    def add(
        self,
        token_digest: str,
        *,
        expires_at: float,
        revoked_at: float | None = None,
        commit: bool = True,
    ) -> None:
        """Insert or replace one revocation row."""
        with db_write_lock(self._conn):
            self._conn.execute(
                "INSERT OR REPLACE INTO revoked_tokens (token_digest, expires_at, revoked_at) "
                "VALUES (?, ?, ?)",
                (
                    token_digest,
                    expires_at,
                    time.time() if revoked_at is None else revoked_at,
                ),
            )
            if commit:
                self._conn.commit()

    def is_revoked(self, token_digest: str, *, now: float | None = None) -> bool:
        """Return True when an unexpired revocation row exists."""
        current = time.time() if now is None else now
        with db_write_lock(self._conn):
            row = self._conn.execute(
                "SELECT expires_at FROM revoked_tokens WHERE token_digest = ?",
                (token_digest,),
            ).fetchone()
            return row is not None and row[0] > current

    def load_active(self, *, now: float | None = None) -> dict[str, float]:
        """Return {token_digest: expires_at} for every unexpired row."""
        current = time.time() if now is None else now
        with db_write_lock(self._conn):
            rows = self._conn.execute(
                "SELECT token_digest, expires_at FROM revoked_tokens WHERE expires_at > ?",
                (current,),
            ).fetchall()
            return {row[0]: row[1] for row in rows}

    def prune_expired(self, *, now: float | None = None, commit: bool = True) -> int:
        """Delete expired rows and return how many were removed."""
        current = time.time() if now is None else now
        with db_write_lock(self._conn):
            cursor = self._conn.execute(
                "DELETE FROM revoked_tokens WHERE expires_at <= ?", (current,)
            )
            if commit:
                self._conn.commit()
            return cursor.rowcount
