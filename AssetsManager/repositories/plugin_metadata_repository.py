"""Plugin metadata repository — CRUD for the plugin_metadata table.

Stores key-value pairs parsed by plugins (e.g. booth URL, item name, author).
Data persists even when plugins are disabled.
"""
from __future__ import annotations

import time
from functools import wraps
from pathlib import Path
from sqlite3 import Connection
from typing import Any, Callable

from AssetsManager.core.database import db_write_lock
from AssetsManager.core.path_resolver import sql_like_descendant_pattern


def _session_operation(method: Callable[..., Any]) -> Callable[..., Any]:
    """Lease an optional session without making repositories depend on application."""
    @wraps(method)
    def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        session = getattr(self, "_session", None)
        if session is None:
            return method(self, *args, **kwargs)
        with session.operation():
            return method(self, *args, **kwargs)

    return wrapped


class PluginMetadataRepository:
    """Encapsulates plugin_metadata table operations."""

    def __init__(
        self,
        conn: Connection,
        *,
        session: Any | None = None,
        library_root: str | Path | None = None,
    ):
        if session is not None:
            session_root = Path(session.root).resolve()
            if library_root is not None and Path(library_root).resolve() != session_root:
                raise ValueError("library_root does not match the bound LibrarySession")
            if conn is not session.connection_for(session.root):
                raise ValueError("connection does not belong to the bound LibrarySession")
            library_root = session_root
        self._conn = conn
        self._session = session
        self._library_root = (
            Path(library_root).resolve() if library_root is not None else None
        )

    def _resolve_under_root(self, path: str | Path) -> str:
        """Return a canonical path and reject paths outside the configured root."""
        target = Path(path).resolve()
        if self._library_root is not None and not target.is_relative_to(self._library_root):
            raise ValueError(
                f"path must be under library_root: {target} (root {self._library_root})"
            )
        return str(target)

    @_session_operation
    def upsert(self, file_path: str, plugin_id: str, field_key: str, field_value: str) -> None:
        """Insert or update a plugin metadata entry."""
        file_path = self._resolve_under_root(file_path)
        with db_write_lock(self._conn):
            self._conn.execute(
                "INSERT INTO plugin_metadata (file_path, plugin_id, field_key, field_value, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(file_path, plugin_id, field_key) DO UPDATE SET "
                "field_value=excluded.field_value, updated_at=excluded.updated_at",
                (file_path, plugin_id, field_key, field_value, time.time()),
            )
            self._conn.commit()

    @_session_operation
    def upsert_batch(self, file_path: str, plugin_id: str, fields: dict[str, str]) -> None:
        """Insert or update multiple fields for a file/plugin pair in one transaction."""
        if not fields:
            return
        file_path = self._resolve_under_root(file_path)
        with db_write_lock(self._conn):
            self._conn.executemany(
                "INSERT INTO plugin_metadata (file_path, plugin_id, field_key, field_value, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(file_path, plugin_id, field_key) DO UPDATE SET "
                "field_value=excluded.field_value, updated_at=excluded.updated_at",
                [(file_path, plugin_id, k, v, time.time()) for k, v in fields.items()],
            )
            self._conn.commit()

    @_session_operation
    def get_fields(self, file_path: str) -> dict[str, dict[str, str]]:
        """Return all plugin metadata for a file.

        Returns {plugin_id: {key: value, ...}}.
        """
        file_path = self._resolve_under_root(file_path)
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

    @_session_operation
    def get_fields_for_children(self, dir_path: str) -> dict[str, dict[str, str]]:
        """Return plugin metadata for all direct children of a directory.

        Used when clicking a folder to aggregate _link/*.txt metadata.
        Returns {plugin_id: {key: value, ...}} (merged from all children).
        """
        dir_path = self._resolve_under_root(dir_path)
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

    @_session_operation
    def delete_for_file(self, file_path: str) -> None:
        """Delete all plugin metadata for a file."""
        file_path = self._resolve_under_root(file_path)
        with db_write_lock(self._conn):
            self._conn.execute(
                "DELETE FROM plugin_metadata WHERE file_path=?",
                (file_path,),
            )
            self._conn.commit()

    @_session_operation
    def delete_for_plugin(self, plugin_id: str) -> None:
        """Delete all metadata for a plugin (e.g. on uninstall)."""
        with db_write_lock(self._conn):
            self._conn.execute(
                "DELETE FROM plugin_metadata WHERE plugin_id=?",
                (plugin_id,),
            )
            self._conn.commit()
