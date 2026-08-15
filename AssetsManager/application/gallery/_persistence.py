"""Gallery persistence mixin: load/save the persisted home projection.

The mixin owns ``_connection``, ``_persist_repository`` and the two
persisted-projection helpers.  It relies on ``GalleryService`` for the
``_connection_provider`` and ``_persisted_ttl`` attributes, declared below
as class-level annotations so static analysis can resolve them.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from AssetsManager.application.context import ConnectionProvider
from AssetsManager.core.database import DatabaseManager
from AssetsManager.repositories.gallery_home_repository import GalleryHomeRepository

from AssetsManager.application.gallery._types import (
    GalleryHome,
    _log,
    _strip_legacy_url_fields,
)


class _GalleryPersistenceMixin:
    # Attributes owned by GalleryService.__init__; declared here so pyright
    # can resolve attribute access on this mixin without importing it.
    _connection_provider: ConnectionProvider | None = None
    _persisted_ttl: float = 3600.0

    @staticmethod
    def _connection(
        library_root: str | Path,
        db_conn: sqlite3.Connection | None,
        provider: ConnectionProvider | None,
    ) -> sqlite3.Connection | None:
        if db_conn is not None:
            return DatabaseManager.validate_connection_owner(
                Path(library_root).resolve(), db_conn, allow_unmanaged=True
            )
        if provider is None:
            return None
        root = Path(library_root).resolve()
        return DatabaseManager.validate_connection_owner(root, provider(root), allow_unmanaged=True)

    def _persist_repository(self, root_key: str) -> GalleryHomeRepository:
        conn = self._connection(Path(root_key).resolve(), None, self._connection_provider)
        if conn is None:
            raise RuntimeError("Gallery persistence requires a connection provider")
        return GalleryHomeRepository(conn)

    def _load_persisted_projection(self, root_key: str) -> "GalleryHome | None":
        """Load the persisted projection within its TTL, or None."""
        try:
            row = self._persist_repository(root_key).get()
            if row is None:
                return None
            saved_at, projection_json = row
            if time.time() - saved_at > self._persisted_ttl:
                return None
            projection = json.loads(projection_json)
            if not isinstance(projection, dict):
                return None
            projection = _strip_legacy_url_fields(projection)
            return GalleryHome(
                featured=projection.get("featured"),
                collections=projection.get("collections", []),
                projects=projection.get("projects", []),
                recent=projection.get("recent", []),
                stats=projection.get("stats", {}),
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError, sqlite3.Error):
            _log.debug("Gallery home persisted projection unreadable for %s", root_key, exc_info=True)
            return None

    def _save_persisted_projection(self, root_key: str, home: "GalleryHome") -> None:
        """Persist the projection into the library database."""
        try:
            self._persist_repository(root_key).save(
                time.time(), json.dumps(home.to_response(), ensure_ascii=False)
            )
        except (OSError, sqlite3.Error):
            _log.debug("Gallery home persisted projection write failed", exc_info=True)
