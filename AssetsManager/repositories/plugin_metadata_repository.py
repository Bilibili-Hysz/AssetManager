"""Plugin metadata repository — CRUD for the plugin_metadata table.

Stores key-value pairs parsed by plugins (e.g. booth URL, item name, author).
Data persists even when plugins are disabled.
"""
from __future__ import annotations

import time
from sqlite3 import Connection

from AssetsManager.core.database import db_write_lock


class PluginMetadataRepository:
    """Encapsulates plugin_metadata table operations."""

    def __init__(self, conn: Connection):
        self._conn = conn

    def upsert(self, file_path: str, plugin_id: str, field_key: str, field_value: str) -> None:
        """Insert or update a plugin metadata entry."""
        with db_write_lock():
            self._conn.execute(
                "INSERT INTO plugin_metadata (file_path, plugin_id, field_key, field_value, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(file_path, plugin_id, field_key) DO UPDATE SET "
                "field_value=excluded.field_value, updated_at=excluded.updated_at",
                (file_path, plugin_id, field_key, field_value, time.time()),
            )
            self._conn.commit()

    def upsert_batch(self, file_path: str, plugin_id: str, fields: dict[str, str]) -> None:
        """Insert or update multiple fields for a file/plugin pair in one transaction."""
        if not fields:
            return
        with db_write_lock():
            self._conn.executemany(
                "INSERT INTO plugin_metadata (file_path, plugin_id, field_key, field_value, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(file_path, plugin_id, field_key) DO UPDATE SET "
                "field_value=excluded.field_value, updated_at=excluded.updated_at",
                [(file_path, plugin_id, k, v, time.time()) for k, v in fields.items()],
            )
            self._conn.commit()

    def get_fields(self, file_path: str) -> dict[str, dict[str, str]]:
        """Return all plugin metadata for a file.

        Returns {plugin_id: {key: value, ...}}.
        """
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

    def get_fields_for_children(self, dir_path: str) -> dict[str, dict[str, str]]:
        """Return plugin metadata for all direct children of a directory.

        Used when clicking a folder to aggregate _link/*.txt metadata.
        Returns {plugin_id: {key: value, ...}} (merged from all children).
        """
        rows = self._conn.execute(
            "SELECT plugin_id, field_key, field_value FROM plugin_metadata "
            "WHERE file_path LIKE ? ESCAPE '\\'",
            (dir_path.replace("\\", "\\\\").replace("%", "\\%") + "/%",),
        ).fetchall()
        result: dict[str, dict[str, str]] = {}
        for pid, key, value in rows:
            if pid not in result:
                result[pid] = {}
            # First value wins (don't overwrite with later children)
            if key not in result[pid]:
                result[pid][key] = value
        return result

    def delete_for_file(self, file_path: str) -> None:
        """Delete all plugin metadata for a file."""
        with db_write_lock():
            self._conn.execute(
                "DELETE FROM plugin_metadata WHERE file_path=?",
                (file_path,),
            )
            self._conn.commit()

    def delete_for_plugin(self, plugin_id: str) -> None:
        """Delete all metadata for a plugin (e.g. on uninstall)."""
        with db_write_lock():
            self._conn.execute(
                "DELETE FROM plugin_metadata WHERE plugin_id=?",
                (plugin_id,),
            )
            self._conn.commit()
