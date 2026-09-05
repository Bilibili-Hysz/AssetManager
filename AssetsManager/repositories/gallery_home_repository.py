"""Gallery home projection repository — persisted across process restarts.

The full-library gallery walk takes tens of seconds on very large
libraries; the resulting projection is stored as one row per library
(the single-row ``gallery_home`` table) so a restart serves it instantly.

Dialect audit (2026-09-05) — deliberately raw-only:

Why raw: the repository is a single-row write-behind projection cache,
not a session-scoped data family. Its only consumer
(``_GalleryPersistenceMixin``, application/gallery/_persistence.py) is a
root-parameter service: every call resolves the library root explicitly
(``_persist_repository(root_key)``), leases the connection through
``DatabaseManager.validate_connection_owner`` and drops the repository
when the call returns — it is a stateless pure projection of one
``root_key``, never a session-bound object graph. The strict base class
buys exactly nothing here: there are no per-path rows (so ``_path_key``
containment has no key to canonicalize), no cross-call state (the instance
is constructed per call), and the write lifetime is governed by the
caller's ``commit=False`` staging contract rather than a session lease.
Forcing ``for_session`` would mean migrating GalleryService to hold a
session first — a service-layer rewrite whose only yield is ledger
arithmetic, while the mixin's connection validation already gives it the
same safety property the base class enforces on the binding path.

When revisit: if GalleryService ever becomes session-scoped (holds one
LibrarySession for its lifetime, P2-style like tag/thumbnail services),
onboard this repository with ``for_session`` and drop the ledger entry.
"""
from __future__ import annotations

from sqlite3 import Connection

from AssetsManager.core.database import db_write_lock
from AssetsManager.repositories._common import _guarded_commit


class GalleryHomeRepository:
    """Encapsulate the gallery_home table (single persisted row)."""

    def __init__(self, conn: Connection):
        self._conn = conn

    def get(self) -> tuple[float, str] | None:
        """Return (saved_at, projection_json) or None when not persisted.

        Serialized through the connection's db_write_lock like the write
        operations: the gallery home build thread and the file-event
        invalidation handler share one sqlite3 connection, and concurrent
        access to a single connection surfaces as SQLITE_MISUSE
        (InterfaceError).
        """
        with db_write_lock(self._conn):
            row = self._conn.execute(
                "SELECT saved_at, projection FROM gallery_home WHERE id = 1"
            ).fetchone()
            return (row[0], row[1]) if row else None

    def save(self, saved_at: float, projection_json: str, *, commit: bool = True) -> None:
        """Insert or replace the persisted projection atomically."""
        with db_write_lock(self._conn):
            outer_transaction = self._conn.in_transaction
            self._conn.execute(
                "INSERT OR REPLACE INTO gallery_home (id, saved_at, projection) "
                "VALUES (1, ?, ?)",
                (saved_at, projection_json),
            )
            if commit:
                _guarded_commit(self._conn, outer_transaction=outer_transaction)

    def delete(self, *, commit: bool = True) -> None:
        """Remove the persisted projection (library changed)."""
        with db_write_lock(self._conn):
            outer_transaction = self._conn.in_transaction
            self._conn.execute("DELETE FROM gallery_home WHERE id = 1")
            if commit:
                _guarded_commit(self._conn, outer_transaction=outer_transaction)
