"""Collection repository — CRUD for user collections and their members.

Two table shapes back the feature (migration v38): ``asset_collections``
holds one row per collection with a ``kind`` of ``'manual'`` (physical
membership rows below) or ``'smart'`` (the structured predicate JSON in
``query_json``, evaluated at read time — no membership rows).  Members are
pure references: the repository never moves or copies files.
"""
from __future__ import annotations

import time
from pathlib import Path
from sqlite3 import IntegrityError
from typing import Literal

from AssetsManager.core.database import db_write_lock, locked_read
from AssetsManager.repositories._common import (
    _SessionBoundRepository,
    _repository_operation,
)
from AssetsManager.domain.errors import DuplicateError, NotFoundError

CollectionKind = Literal["manual", "smart"]

_KINDS: tuple[str, ...] = ("manual", "smart")


def _collection_kind(kind: str) -> CollectionKind:
    """Route ``kind`` through a controlled whitelist before SQL use."""
    if kind not in _KINDS:
        raise ValueError(f"unknown collection kind: {kind!r}")
    return kind  # type: ignore[return-value]


class CollectionRepository(_SessionBoundRepository):
    """Encapsulate all user-collection database operations.

    ``CollectionRepository(conn)`` remains the explicit raw compatibility
    path. Canonical callers should use :meth:`for_session`, which binds
    connection ownership, root containment, transaction lifetime, and close
    semantics to one real ``LibrarySession``.
    """

    def _path_key(self, file_path: str | Path) -> str:
        """Return a canonical path and enforce bound-root containment.

        The raw path keeps the historical pass-through: collection members
        are pure references written with caller-resolved paths, and raw
        callers (export/restore snapshots) operate on connection-owned paths.
        """
        if self._library_root is None:
            return str(file_path)
        target = Path(file_path).resolve()
        if not target.is_relative_to(self._library_root):
            raise ValueError(
                f"collection path must be under library_root: {target} "
                f"(root {self._library_root})"
            )
        return str(target)

    def _path_keys(self, file_paths: list[str]) -> list[str]:
        return [self._path_key(file_path) for file_path in file_paths]

    # ── Reads ─────────────────────────────────────────────────────

    @_repository_operation
    @locked_read
    def get(self, collection_id: int) -> dict | None:
        """Return one collection row, or None when the id is unknown."""
        row = self._conn.execute(
            "SELECT id, name, kind, query_json, created_at, updated_at "
            "FROM asset_collections WHERE id=?",
            (collection_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "name": row[1],
            "kind": row[2],
            "query_json": row[3],
            "created_at": row[4],
            "updated_at": row[5],
        }

    @_repository_operation
    @locked_read
    def list_collections(self) -> list[dict]:
        """Return all collections with member counts, sorted by name.

        Smart collections have no membership rows, so their count is 0; the
        count is informational (sidebar badges), not authoritative.
        """
        rows = self._conn.execute(
            "SELECT c.id, c.name, c.kind, c.query_json, c.created_at, c.updated_at, "
            "COUNT(m.file_path) AS member_count "
            "FROM asset_collections c "
            "LEFT JOIN asset_collection_members m ON m.collection_id = c.id "
            "GROUP BY c.id ORDER BY c.name COLLATE NOCASE, c.id"
        ).fetchall()
        return [
            {
                "id": row[0],
                "name": row[1],
                "kind": row[2],
                "query_json": row[3],
                "created_at": row[4],
                "updated_at": row[5],
                "member_count": row[6],
            }
            for row in rows
        ]

    @_repository_operation
    @locked_read
    def get_members(self, collection_id: int) -> list[dict]:
        """Return membership rows ordered by insertion time.

        Missing-on-disk paths are deliberately NOT pruned here: the collection
        is a reference set, and readers tolerate absent members (the service
        layer marks them with ``exists`` so consumers can skip them).
        """
        rows = self._conn.execute(
            "SELECT file_path, added_at FROM asset_collection_members "
            "WHERE collection_id=? ORDER BY added_at, file_path",
            (collection_id,),
        ).fetchall()
        return [{"file_path": row[0], "added_at": row[1]} for row in rows]

    @_repository_operation
    @locked_read
    def count_members(self, collection_id: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM asset_collection_members WHERE collection_id=?",
            (collection_id,),
        ).fetchone()
        return int(row[0]) if row is not None else 0

    # ── Writes ────────────────────────────────────────────────────

    @_repository_operation
    def create(
        self,
        kind: str,
        name: str,
        query_json: str,
        *,
        commit: bool = True,
        require_clean_transaction: bool = False,
    ) -> dict:
        """Create a collection; duplicate names raise DuplicateError."""
        _collection_kind(kind)
        now = time.time()

        def insert() -> dict:
            duplicate = self._conn.execute(
                "SELECT 1 FROM asset_collections WHERE name=?", (name,)
            ).fetchone()
            if duplicate is not None:
                raise DuplicateError("collection", name)
            try:
                cursor = self._conn.execute(
                    "INSERT INTO asset_collections "
                    "(name, kind, query_json, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (name, kind, query_json, now, now),
                )
            except IntegrityError as exc:
                raise DuplicateError("collection", name) from exc
            return {
                "id": cursor.lastrowid,
                "name": name,
                "kind": kind,
                "query_json": query_json,
                "created_at": now,
                "updated_at": now,
                "member_count": 0,
            }

        if commit:
            with self._write_scope(
                "create", require_clean_transaction=require_clean_transaction
            ):
                return insert()
        return insert()

    @_repository_operation
    def rename(
        self,
        collection_id: int,
        new_name: str,
        *,
        commit: bool = True,
        require_clean_transaction: bool = False,
    ) -> None:
        """Rename a collection; duplicate names raise DuplicateError."""
        def rename() -> None:
            row = self._conn.execute(
                "SELECT 1 FROM asset_collections WHERE id=?", (collection_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("collection", str(collection_id))
            duplicate = self._conn.execute(
                "SELECT 1 FROM asset_collections WHERE name=? AND id<>?",
                (new_name, collection_id),
            ).fetchone()
            if duplicate is not None:
                raise DuplicateError("collection", new_name)
            self._conn.execute(
                "UPDATE asset_collections SET name=?, updated_at=? WHERE id=?",
                (new_name, time.time(), collection_id),
            )

        if commit:
            with self._write_scope(
                "rename", require_clean_transaction=require_clean_transaction
            ):
                rename()
            return
        with db_write_lock(self._conn):
            rename()

    @_repository_operation
    def set_query(
        self,
        collection_id: int,
        query_json: str,
        *,
        commit: bool = True,
        require_clean_transaction: bool = False,
    ) -> None:
        """Replace the structured predicate JSON of a smart collection."""
        def set_query() -> None:
            row = self._conn.execute(
                "SELECT 1 FROM asset_collections WHERE id=?", (collection_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("collection", str(collection_id))
            self._conn.execute(
                "UPDATE asset_collections SET query_json=?, updated_at=? WHERE id=?",
                (query_json, time.time(), collection_id),
            )

        if commit:
            with self._write_scope(
                "set_query", require_clean_transaction=require_clean_transaction
            ):
                set_query()
            return
        with db_write_lock(self._conn):
            set_query()

    @_repository_operation
    def delete(
        self,
        collection_id: int,
        *,
        commit: bool = True,
        require_clean_transaction: bool = False,
    ) -> bool:
        """Delete one collection; membership rows cascade (v38 FK)."""
        def delete() -> bool:
            cursor = self._conn.execute(
                "DELETE FROM asset_collections WHERE id=?", (collection_id,)
            )
            return cursor.rowcount > 0

        if commit:
            with self._write_scope(
                "delete", require_clean_transaction=require_clean_transaction
            ):
                return delete()
        with db_write_lock(self._conn):
            return delete()

    @_repository_operation
    def add_members(
        self,
        collection_id: int,
        file_paths: list[str],
        *,
        commit: bool = True,
        require_clean_transaction: bool = False,
    ) -> int:
        """Add member references; duplicates are an idempotent no-op.

        Returns the number of newly inserted rows.
        """
        canonical = list(dict.fromkeys(self._path_key(p) for p in file_paths))

        def insert() -> int:
            row = self._conn.execute(
                "SELECT 1 FROM asset_collections WHERE id=?", (collection_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("collection", str(collection_id))
            added = 0
            now = time.time()
            for path in canonical:
                cursor = self._conn.execute(
                    "INSERT OR IGNORE INTO asset_collection_members "
                    "(collection_id, file_path, added_at) VALUES (?, ?, ?)",
                    (collection_id, path, now),
                )
                added += cursor.rowcount
            if added:
                self._conn.execute(
                    "UPDATE asset_collections SET updated_at=? WHERE id=?",
                    (now, collection_id),
                )
            return added

        if commit:
            with self._write_scope(
                "add_members", require_clean_transaction=require_clean_transaction
            ):
                return insert()
        with db_write_lock(self._conn):
            return insert()

    @_repository_operation
    def remove_members(
        self,
        collection_id: int,
        file_paths: list[str],
        *,
        commit: bool = True,
        require_clean_transaction: bool = False,
    ) -> int:
        """Remove member references; missing rows are an idempotent no-op."""
        canonical = list(dict.fromkeys(self._path_key(p) for p in file_paths))

        def remove() -> int:
            removed = 0
            for path in canonical:
                cursor = self._conn.execute(
                    "DELETE FROM asset_collection_members "
                    "WHERE collection_id=? AND file_path=?",
                    (collection_id, path),
                )
                removed += cursor.rowcount
            if removed:
                self._conn.execute(
                    "UPDATE asset_collections SET updated_at=? WHERE id=?",
                    (time.time(), collection_id),
                )
            return removed

        if commit:
            with self._write_scope(
                "remove_members", require_clean_transaction=require_clean_transaction
            ):
                return remove()
        with db_write_lock(self._conn):
            return remove()
