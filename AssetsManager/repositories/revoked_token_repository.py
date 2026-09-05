"""Persistent auth-token revocation repository.

Simple-password LAN tokens are signed with the persisted password hash and
survive app restarts; their revocations must too. Rows live in the library
database so a revoked token cannot resurrect when the in-memory revocation
table dies with the process.

Dialect audit (2026-09-05) — deliberately raw-only:

Why raw: token revocation is an *auth-host* concept, not a library-data
concept. The repository's sole consumer is AuthService
(``_revocation_repo``), which is constructed once per auth host with a
``db_conn`` owned by the host (bootstrap wires ``AuthService(connection,
...)``) and then serves the process-wide LAN request path — the revocation
check runs for every authenticated request regardless of which library
session the request rides on, and the in-memory positive cache in
``lan/token_revocations.py`` is host-scoped, not session-scoped. Binding
the repository to one ``LibrarySession`` would be semantically wrong: it
would tie "is this token revoked" to a session that has nothing to do with
the token's issuance, and the strict base's four-way guard (one session,
one connection, one root) would forbid the host's shared-connection reuse
that AuthService deliberately keeps. There is also no path dimension at
all (the key is a SHA256 token digest), so ``_path_key`` root containment
has nothing to enforce.

When revisit: only if token issuance ever becomes per-library (e.g. tokens
scoped to one root with revocation checked inside that root's session).
Until then the auth host owns the connection and this repository stays a
small raw table adapter.
"""
from __future__ import annotations

import threading
import time
from sqlite3 import Connection

from AssetsManager.core.database import db_write_lock


class RevokedTokenRepository:
    """Encapsulate the revoked_tokens table (digest -> expiry)."""

    def __init__(self, conn: Connection):
        self._conn = conn
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with db_write_lock(self._conn):
                outer_transaction = self._conn.in_transaction
                savepoint = "revoked_token_repository_init"
                self._conn.execute(f"SAVEPOINT {savepoint}")
                try:
                    self._conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS revoked_tokens (
                            token_digest TEXT PRIMARY KEY NOT NULL
                                         CHECK (length(trim(token_digest)) = 64),
                            expires_at REAL NOT NULL,
                            revoked_at REAL NOT NULL
                        )
                        """
                    )
                    self._conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_revoked_tokens_expires "
                        "ON revoked_tokens(expires_at)"
                    )
                    if outer_transaction:
                        self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                    else:
                        self._conn.commit()
                except BaseException:
                    self._conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                    raise
                # A caller-owned transaction may still roll back the DDL, so
                # do not cache readiness until this repository owns the commit.
                schema_committed = not outer_transaction
            self._schema_ready = schema_committed

    def add(
        self,
        token_digest: str,
        *,
        expires_at: float,
        revoked_at: float | None = None,
        commit: bool = True,
    ) -> None:
        """Insert or replace one revocation row."""
        self._ensure_schema()
        with db_write_lock(self._conn):
            outer_transaction = self._conn.in_transaction
            self._conn.execute(
                "INSERT OR REPLACE INTO revoked_tokens (token_digest, expires_at, revoked_at) "
                "VALUES (?, ?, ?)",
                (
                    token_digest,
                    expires_at,
                    time.time() if revoked_at is None else revoked_at,
                ),
            )
            if commit and not outer_transaction:
                self._conn.commit()

    def is_revoked(self, token_digest: str, *, now: float | None = None) -> bool:
        """Return True when an unexpired revocation row exists."""
        self._ensure_schema()
        current = time.time() if now is None else now
        with db_write_lock(self._conn):
            row = self._conn.execute(
                "SELECT expires_at FROM revoked_tokens WHERE token_digest = ?",
                (token_digest,),
            ).fetchone()
            return row is not None and row[0] > current

    def load_active(self, *, now: float | None = None) -> dict[str, float]:
        """Return {token_digest: expires_at} for every unexpired row."""
        self._ensure_schema()
        current = time.time() if now is None else now
        with db_write_lock(self._conn):
            rows = self._conn.execute(
                "SELECT token_digest, expires_at FROM revoked_tokens WHERE expires_at > ?",
                (current,),
            ).fetchall()
            return {row[0]: row[1] for row in rows}

    def prune_expired(self, *, now: float | None = None, commit: bool = True) -> int:
        """Delete expired rows and return how many were removed."""
        self._ensure_schema()
        current = time.time() if now is None else now
        with db_write_lock(self._conn):
            outer_transaction = self._conn.in_transaction
            cursor = self._conn.execute(
                "DELETE FROM revoked_tokens WHERE expires_at <= ?", (current,)
            )
            if commit and not outer_transaction:
                self._conn.commit()
            return cursor.rowcount
