"""Plugin metadata repository — CRUD for the plugin_metadata table.

Stores key-value pairs parsed by plugins (e.g. booth URL, item name, author).
Data persists even when plugins are disabled.

Session binding rides the shared strict scaffolding (``_SessionBoundRepository``:
real-session token, captured ``RootIdentity``, operation lease) — the third
and last of the repository session dialects unified 2026-09-04 (see the
unification plan for the removed legacy comparison).
"""
from __future__ import annotations

import time
from pathlib import Path
from sqlite3 import Connection
from typing import Any

from AssetsManager.core.database import db_write_lock
from AssetsManager.core.path_resolver import RootIdentity, sql_like_descendant_pattern
from AssetsManager.repositories._common import (
    _SessionBoundRepository,
    _guarded_commit,
    _repository_operation,
)


class PluginMetadataRepository(_SessionBoundRepository):
    """Encapsulates plugin_metadata table operations."""

    def __init__(
        self,
        conn: Connection,
        *,
        session: Any | None = None,
        library_root: str | Path | RootIdentity | None = None,
    ):
        # Historical quirk preserved: ``session`` used to be the second
        # positional keyword and ``library_root`` third; the base takes
        # ``library_root`` first, so both orders must keep working for the
        # raw constructor path (info_controller passes them by keyword).
        super().__init__(conn, library_root=library_root, session=session)

    def _path_key(self, path: str | Path) -> str:
        """Return a canonical resolved path and reject paths outside the root.

        Unlike the sibling repositories this ALWAYS resolves (even unbound):
        the historical contract stored plugin fields under resolved keys, and
        raw-constructed callers (info controller, export snapshots) read and
        write through the same resolution so forward/backward slash variants
        of one path land on a single row.
        """
        target = Path(path).resolve()
        if self._library_root is not None and not target.is_relative_to(self._library_root):
            raise ValueError(
                f"path must be under library_root: {target} (root {self._library_root})"
            )
        return str(target)

    # ── Writes ──────────────────────────────────────────────────

    @_repository_operation
    def upsert(self, file_path: str, plugin_id: str, field_key: str, field_value: str) -> None:
        """Insert or update a plugin metadata entry."""
        file_path = self._path_key(file_path)
        with db_write_lock(self._conn):
            outer_transaction = self._conn.in_transaction
            self._conn.execute(
                "INSERT INTO plugin_metadata (file_path, plugin_id, field_key, field_value, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(file_path, plugin_id, field_key) DO UPDATE SET "
                "field_value=excluded.field_value, updated_at=excluded.updated_at",
                (file_path, plugin_id, field_key, field_value, time.time()),
            )
            _guarded_commit(self._conn, outer_transaction=outer_transaction)

    @_repository_operation
    def upsert_batch(self, file_path: str, plugin_id: str, fields: dict[str, str]) -> None:
        """Insert or update multiple fields for a file/plugin pair in one transaction."""
        if not fields:
            return
        file_path = self._path_key(file_path)
        with db_write_lock(self._conn):
            outer_transaction = self._conn.in_transaction
            self._conn.executemany(
                "INSERT INTO plugin_metadata (file_path, plugin_id, field_key, field_value, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(file_path, plugin_id, field_key) DO UPDATE SET "
                "field_value=excluded.field_value, updated_at=excluded.updated_at",
                [(file_path, plugin_id, k, v, time.time()) for k, v in fields.items()],
            )
            _guarded_commit(self._conn, outer_transaction=outer_transaction)

    # ── Reads ───────────────────────────────────────────────────

    @_repository_operation
    def get_fields(self, file_path: str) -> dict[str, dict[str, str]]:
        """Return all plugin metadata for a file.

        Returns {plugin_id: {key: value, ...}}.
        """
        file_path = self._path_key(file_path)
        rows = self._conn.execute(
            "SELECT plugin_id, field_key, field_value FROM plugin_metadata WHERE file_path=?",
            (file_path,),
        ).fetchall()
        result: dict[str, dict[str, str]] = {}
        for pid, key, value in rows:
            if pid not in result:
                result[pid] = {}
            result[pid][key] = value
        return result

    @_repository_operation
    def get_fields_for_children(self, dir_path: str) -> dict[str, dict[str, str]]:
        """Return plugin metadata for all direct children of a directory.

        Used when clicking a folder to aggregate _link/*.txt metadata.
        Returns {plugin_id: {key: value, ...}} (merged from all children).
        """
        dir_path = self._path_key(dir_path)
        # Descendants-only pattern with LIKE wildcards (\, %, _) escaped;
        # the separator is derived from the stored key representation.
        descendant_pattern = sql_like_descendant_pattern(dir_path)
        rows = self._conn.execute(
            "SELECT plugin_id, field_key, field_value FROM plugin_metadata "
            "WHERE file_path LIKE ? ESCAPE '\\'",
            (descendant_pattern,),
        ).fetchall()
        result: dict[str, dict[str, str]] = {}
        for pid, key, value in rows:
            if pid not in result:
                result[pid] = {}
            # First value wins (don't overwrite with later children)
            if key not in result[pid]:
                result[pid][key] = value
        return result

    # ── Deletes ──────────────────────────────────────────────────

    @_repository_operation
    def delete_for_file(self, file_path: str) -> None:
        """Delete all plugin metadata for a file."""
        file_path = self._path_key(file_path)
        with db_write_lock(self._conn):
            outer_transaction = self._conn.in_transaction
            self._conn.execute(
                "DELETE FROM plugin_metadata WHERE file_path=?",
                (file_path,),
            )
            _guarded_commit(self._conn, outer_transaction=outer_transaction)

    @_repository_operation
    def delete_for_plugin(self, plugin_id: str) -> None:
        """Delete all metadata for a plugin (e.g. on uninstall)."""
        with db_write_lock(self._conn):
            outer_transaction = self._conn.in_transaction
            self._conn.execute(
                "DELETE FROM plugin_metadata WHERE plugin_id=?",
                (plugin_id,),
            )
            _guarded_commit(self._conn, outer_transaction=outer_transaction)
