"""Repository for principal-scoped library favorites.

Dialect (P2/Q1 onboarding, 2026-09-05): the repository inherits the strict
``_SessionBoundRepository`` binding contract. ``FavoriteRepository(conn)``
remains the explicit raw compatibility path (file-operation projection
cleanup, LAN route tests); canonical callers should use
:meth:`for_session`, which binds connection ownership, root containment,
transaction lifetime, and close semantics to one real ``LibrarySession``.

Favorites are per-library rows keyed by ``file_path`` like tags/collections
(the ``library_favorites`` table lives in the owning library database), so
the migration follows the P1 tag/collection/metadata pattern exactly,
including the deliberate ``_path_key`` raw pass-through override with its
rationale (see the override docstring).
"""
from __future__ import annotations

from pathlib import Path

from AssetsManager.core.database import db_write_lock, locked_read
from AssetsManager.core.path_resolver import remap_path_subtree, sql_like_descendant_pattern
from AssetsManager.core.schema_defs import LIBRARY_FAVORITES_SCHEMA
from AssetsManager.repositories._common import (
    _SessionBoundRepository,
    _guarded_commit,
    _repository_operation,
)


class FavoriteRepository(_SessionBoundRepository):
    """Persist favorite paths in the owning library database."""

    # Mirrors application.favorite_service.MAX_FAVORITES_PER_OWNER (importing
    # it upward would violate repository layering — keep the two in sync).
    # list_paths clamps to this ceiling so a full favorite list is never
    # silently truncated below the per-owner cap.
    LIMIT_CEILING = 10_000

    def _path_key(self, file_path: str | Path) -> str:
        """Return a canonical path and enforce bound-root containment.

        The raw path keeps the historical pass-through (the same deliberate
        deviation tag/collection/metadata carry, P1): favorites are stored
        with caller-resolved absolute paths, and raw callers
        (file-operation projection cleanup, export/restore snapshots)
        operate on connection-owned paths where the repository has no
        session identity to enforce containment against.
        """
        if self._library_root is None:
            return str(file_path)
        target = Path(file_path).resolve()
        if not target.is_relative_to(self._library_root):
            raise ValueError(
                f"favorite path must be under library_root: {target} "
                f"(root {self._library_root})"
            )
        return str(target)

    def init_table(self) -> None:
        """Create the favorites table for explicit legacy/test compatibility."""
        with db_write_lock(self._conn):
            outer_transaction = self._conn.in_transaction
            self._conn.executescript(LIBRARY_FAVORITES_SCHEMA)
            _guarded_commit(self._conn, outer_transaction=outer_transaction)

    @_repository_operation
    @locked_read
    def list_paths(self, owner_key: str, *, limit: int = LIMIT_CEILING) -> list[str]:
        rows = self._conn.execute(
            "SELECT file_path FROM library_favorites WHERE owner_key=? "
            "ORDER BY created_at DESC, file_path LIMIT ?",
            (owner_key, max(1, min(int(limit), self.LIMIT_CEILING))),
        ).fetchall()
        return [str(row[0]) for row in rows]

    @_repository_operation
    @locked_read
    def contains(self, owner_key: str, file_path: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM library_favorites WHERE owner_key=? AND file_path=?",
            (owner_key, self._path_key(file_path)),
        ).fetchone() is not None

    @_repository_operation
    def add(self, owner_key: str, file_path: str, *, max_items: int = LIMIT_CEILING) -> bool:
        """Add a favorite atomically. False if already present; OverflowError at limit."""
        file_path = self._path_key(file_path)
        with db_write_lock(self._conn):
            # Single statement: the duplicate check, the per-owner count check
            # and the insert commit together, so concurrent adds cannot slip
            # past the limit (no separate count-then-insert window).
            outer_transaction = self._conn.in_transaction
            cursor = self._conn.execute(
                "INSERT INTO library_favorites (owner_key, file_path) "
                "SELECT ?, ? "
                "WHERE NOT EXISTS ("
                "  SELECT 1 FROM library_favorites WHERE owner_key=? AND file_path=?"
                ") AND (SELECT COUNT(*) FROM library_favorites WHERE owner_key=?) < ?",
                (owner_key, file_path, owner_key, file_path, owner_key, max_items),
            )
            _guarded_commit(self._conn, outer_transaction=outer_transaction)
            if cursor.rowcount == 1:
                return True
            if self.contains(owner_key, file_path):
                return False
            raise OverflowError("favorite limit reached")

    @_repository_operation
    def remove(self, owner_key: str, file_path: str) -> bool:
        file_path = self._path_key(file_path)
        with db_write_lock(self._conn):
            outer_transaction = self._conn.in_transaction
            cursor = self._conn.execute(
                "DELETE FROM library_favorites WHERE owner_key=? AND file_path=?",
                (owner_key, file_path),
            )
            _guarded_commit(self._conn, outer_transaction=outer_transaction)
            return cursor.rowcount > 0

    @_repository_operation
    def delete_path(self, file_path: str, *, commit: bool = True) -> int:
        """Delete favorites for one path and all descendants, across owners."""
        file_path = self._path_key(file_path)
        descendant_pattern = sql_like_descendant_pattern(file_path)
        with db_write_lock(self._conn):
            outer_transaction = self._conn.in_transaction
            cursor = self._conn.execute(
                "DELETE FROM library_favorites "
                "WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
                (file_path, descendant_pattern),
            )
            if commit:
                _guarded_commit(self._conn, outer_transaction=outer_transaction)
            return cursor.rowcount

    @_repository_operation
    def migrate_path(self, old_path: str, new_path: str, *, commit: bool = True) -> int:
        """Remap favorites for a moved path and its descendants."""
        old_path = self._path_key(old_path)
        new_path = self._path_key(new_path)
        descendant_pattern = sql_like_descendant_pattern(old_path)
        with db_write_lock(self._conn):
            outer_transaction = self._conn.in_transaction
            rows = self._conn.execute(
                "SELECT owner_key, file_path, created_at FROM library_favorites "
                "WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
                (old_path, descendant_pattern),
            ).fetchall()
            for owner_key, file_path, created_at in rows:
                mapped = remap_path_subtree(old_path, new_path, str(file_path))
                self._conn.execute(
                    "INSERT OR IGNORE INTO library_favorites "
                    "(owner_key, file_path, created_at) VALUES (?, ?, ?)",
                    (owner_key, mapped, created_at),
                )
            if rows:
                self._conn.execute(
                    "DELETE FROM library_favorites "
                    "WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
                    (old_path, descendant_pattern),
                )
            if commit:
                _guarded_commit(self._conn, outer_transaction=outer_transaction)
            return len(rows)


__all__ = ["FavoriteRepository"]
