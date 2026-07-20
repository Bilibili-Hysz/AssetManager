"""Share repository — persistence operations for share_links table.

Note: This repository handles only low-level CRUD. Business logic
(authentication, validation, token generation) lives in ShareService.
"""
from __future__ import annotations

import json
import logging
import time
from sqlite3 import Connection

from AssetsManager.core.database import db_write_lock

_log = logging.getLogger(__name__)

SHARE_LINKS_SCHEMA = """
CREATE TABLE IF NOT EXISTS share_links (
    id              TEXT PRIMARY KEY,
    paths           TEXT NOT NULL,
    password_hash   TEXT,
    expires_at      REAL,
    max_downloads   INTEGER,
    download_count  INTEGER DEFAULT 0,
    allow_preview   INTEGER DEFAULT 1,
    created_by      TEXT,
    created_at      REAL DEFAULT (strftime('%s','now')),
    is_active       INTEGER DEFAULT 1
);
"""


class ShareRepository:
    """Encapsulates share_links table operations."""

    def __init__(self, conn: Connection):
        self._conn = conn

    def init_table(self) -> None:
        """Create the share_links table if it doesn't exist."""
        with db_write_lock(self._conn):
            self._conn.execute(SHARE_LINKS_SCHEMA)
            self._conn.commit()

    def get(self, share_id: str, *, include_unavailable: bool = False) -> dict | None:
        """Get a share link by ID.

        By default, expired or download-limited links are treated as unavailable.
        Set ``include_unavailable`` when callers need to distinguish the reason.
        """
        row = self._conn.execute(
            "SELECT id, paths, password_hash, expires_at, max_downloads, "
            "download_count, allow_preview, created_by, created_at, is_active "
            "FROM share_links WHERE id=?",
            (share_id,),
        ).fetchone()
        if not row:
            return None

        sid, paths_json, pw_hash, expires_at, max_dl, dl_count, allow_prev, created_by, created_at, is_active = row

        if not is_active:
            return None
        if not include_unavailable and expires_at and time.time() > expires_at:
            return None
        if not include_unavailable and max_dl and dl_count >= max_dl:
            return None

        return {
            "id": sid,
            "paths": json.loads(paths_json),
            "password_hash": pw_hash,
            "expires_at": expires_at,
            "max_downloads": max_dl,
            "download_count": dl_count,
            "allow_preview": allow_prev,
            "created_by": created_by,
            "created_at": created_at,
        }

    def list_all(self, created_by: str | None = None) -> list[dict]:
        """List share links, optionally filtered by creator."""
        if created_by:
            rows = self._conn.execute(
                "SELECT id, paths, password_hash, expires_at, max_downloads, "
                "download_count, allow_preview, created_by, created_at, is_active "
                "FROM share_links WHERE is_active=1 AND created_by=? "
                "ORDER BY created_at DESC",
                (created_by,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, paths, password_hash, expires_at, max_downloads, "
                "download_count, allow_preview, created_by, created_at, is_active "
                "FROM share_links WHERE is_active=1 ORDER BY created_at DESC"
            ).fetchall()

        return [item for r in rows if (item := self._row_to_dict(r)) is not None]

    def insert(self, share_id: str, paths: list[str], password_hash: str | None,
               expires_at: float | None, max_downloads: int | None,
               allow_preview: bool, created_by: str | None) -> bool:
        """Insert a new share link. Returns True on success."""
        try:
            with db_write_lock(self._conn):
                self._conn.execute(
                    "INSERT INTO share_links "
                    "(id, paths, password_hash, expires_at, max_downloads, "
                    "download_count, allow_preview, created_by, created_at, is_active) "
                    "VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?, 1)",
                    (
                        share_id,
                        json.dumps(paths),
                        password_hash,
                        expires_at,
                        max_downloads,
                        allow_preview,
                        created_by,
                        time.time(),
                    ),
                )
                self._conn.commit()
            return True
        except Exception:
            _log.warning("Failed to insert share link %s", share_id, exc_info=True)
            return False

    def delete(self, share_id: str) -> bool:
        """Soft-delete a share link. Returns True if deleted."""
        with db_write_lock(self._conn):
            cur = self._conn.execute(
                "UPDATE share_links SET is_active=0 WHERE id=?",
                (share_id,),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def increment_download(self, share_id: str) -> bool:
        """Increment download counter if the share is still downloadable."""
        with db_write_lock(self._conn):
            cur = self._conn.execute(
                "UPDATE share_links SET download_count = download_count + 1 "
                "WHERE id=? AND is_active=1 "
                "AND (expires_at IS NULL OR expires_at > ?) "
                "AND (max_downloads IS NULL OR download_count < max_downloads)",
                (share_id, time.time()),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def get_password_hash(self, share_id: str) -> str | None:
        """Return the password hash for a share link, or None."""
        row = self._conn.execute(
            "SELECT password_hash FROM share_links WHERE id=?",
            (share_id,),
        ).fetchone()
        return row[0] if row else None

    def _row_to_dict(self, row) -> dict | None:
        """Convert a DB row to a dict, checking active/expired/limit."""
        sid, paths_json, pw_hash, expires_at, max_dl, dl_count, allow_prev, created_by, created_at, is_active = row

        if not is_active:
            return None
        if expires_at and time.time() > expires_at:
            return None
        if max_dl and dl_count >= max_dl:
            return None

        return {
            "id": sid,
            "paths": json.loads(paths_json),
            "password_hash": pw_hash,
            "expires_at": expires_at,
            "max_downloads": max_dl,
            "download_count": dl_count,
            "allow_preview": allow_prev,
            "created_by": created_by,
            "created_at": created_at,
        }
