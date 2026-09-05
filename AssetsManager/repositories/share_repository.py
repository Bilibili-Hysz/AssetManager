"""Share repository — persistence operations for share_links table.

Note: This repository handles only low-level CRUD. Business logic
(authentication, validation, token generation) lives in ShareService.
"""
from __future__ import annotations

import json
import logging
import time
from sqlite3 import Connection, IntegrityError

from AssetsManager.core.database import db_write_lock, locked_read
from AssetsManager.core.schema_defs import validate_schema_objects
from AssetsManager.core.schema_defs import SHARE_LINKS_SCHEMA
from AssetsManager.repositories._common import (
    _SessionBoundRepository,
    _guarded_commit,
    _repository_operation,
)

_log = logging.getLogger(__name__)

# Compatibility alias: schema ownership lives in core.schema_defs / migration v6.




def _cleanup_insert_savepoint(
    conn: Connection,
    savepoint: str,
    *,
    outer_transaction: bool,
    savepoint_active: bool,
) -> None:
    """Undo one insert without rolling back a caller-owned transaction.

    Cleanup failures are infrastructure failures, not duplicate-share business
    outcomes.  Complete every safe cleanup step, then raise if the original
    transaction boundary could not be restored.
    """
    cleanup_errors: list[Exception] = []
    if savepoint_active:
        for statement, action in (
            (f"ROLLBACK TO SAVEPOINT {savepoint}", "roll back"),
            (f"RELEASE SAVEPOINT {savepoint}", "release"),
        ):
            try:
                conn.execute(statement)
            except Exception as exc:
                cleanup_errors.append(exc)
                _log.debug(
                    "Unable to %s share insert savepoint %s",
                    action,
                    savepoint,
                    exc_info=True,
                )

    if not outer_transaction and conn.in_transaction:
        try:
            conn.rollback()
        except Exception as exc:
            cleanup_errors.append(exc)
            _log.debug(
                "Unable to finish rollback after share insert failure",
                exc_info=True,
            )

    if conn.in_transaction is not outer_transaction:
        cleanup_errors.append(
            RuntimeError("Share insert cleanup changed the caller transaction boundary")
        )

    if cleanup_errors:
        raise RuntimeError("Unable to restore the share insert transaction") from cleanup_errors[0]


class ShareRepository(_SessionBoundRepository):
    """Encapsulates share_links table operations."""

    @_repository_operation
    def init_table(self) -> None:
        """Compatibility ensure for raw/legacy connections; migration v6 owns the schema."""
        with db_write_lock(self._conn):
            outer_transaction = self._conn.in_transaction
            savepoint = "share_repository_init"
            self._conn.execute(f"SAVEPOINT {savepoint}")
            try:
                self._conn.execute(SHARE_LINKS_SCHEMA)
                validate_schema_objects(self._conn, ("share_links",))
                if outer_transaction:
                    self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                else:
                    self._conn.commit()
            except BaseException:
                self._conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise

    @staticmethod
    def _decode_paths(paths_json: str | None) -> list[str]:
        """Decode the paths JSON column, tolerating corrupted rows."""
        try:
            result = json.loads(paths_json or "[]")
            if not isinstance(result, list):
                _log.warning("Share paths JSON is not a list: %r", paths_json)
                return []
            return result
        except (json.JSONDecodeError, TypeError):
            _log.warning("Malformed share paths JSON: %r", paths_json)
            return []

    @_repository_operation
    @locked_read
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
            "paths": self._decode_paths(paths_json),
            "password_hash": pw_hash,
            "expires_at": expires_at,
            "max_downloads": max_dl,
            "download_count": dl_count,
            "allow_preview": allow_prev,
            "created_by": created_by,
            "created_at": created_at,
        }

    @_repository_operation
    @locked_read
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

    @_repository_operation
    def insert(self, share_id: str, paths: list[str], password_hash: str | None,
               expires_at: float | None, max_downloads: int | None,
               allow_preview: bool, created_by: str | None) -> bool:
        """Insert a new share link. Returns True on success."""
        with db_write_lock(self._conn):
            outer_transaction = self._conn.in_transaction
            savepoint = (
                f"share_repository_insert_{id(self):x}_{time.monotonic_ns():x}"
            )
            savepoint_active = False
            try:
                self._conn.execute(f"SAVEPOINT {savepoint}")
                savepoint_active = True
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
                self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                savepoint_active = False
                if not outer_transaction:
                    self._conn.commit()
                return True
            except IntegrityError:
                _cleanup_insert_savepoint(
                    self._conn,
                    savepoint,
                    outer_transaction=outer_transaction,
                    savepoint_active=savepoint_active,
                )
                # Duplicate/constraint violations are expected business-level
                # insert failures.  Infrastructure and lifecycle errors must
                # propagate so callers cannot mistake an unavailable repository
                # for a failed share creation.
                _log.warning("Failed to insert share link %s", share_id, exc_info=True)
                return False
            except BaseException:
                try:
                    _cleanup_insert_savepoint(
                        self._conn,
                        savepoint,
                        outer_transaction=outer_transaction,
                        savepoint_active=savepoint_active,
                    )
                except Exception:
                    # Preserve the original infrastructure/lifecycle failure;
                    # cleanup diagnostics are still recorded for investigation.
                    _log.exception(
                        "Share insert cleanup also failed after an operation error"
                    )
                raise

    @_repository_operation
    def delete(self, share_id: str) -> bool:
        """Soft-delete a share link. Returns True if deleted."""
        with db_write_lock(self._conn):
            outer_transaction = self._conn.in_transaction
            cur = self._conn.execute(
                "UPDATE share_links SET is_active=0 WHERE id=?",
                (share_id,),
            )
            _guarded_commit(self._conn, outer_transaction=outer_transaction)
            return cur.rowcount > 0

    @_repository_operation
    def increment_download(self, share_id: str) -> bool:
        """Increment download counter if the share is still downloadable."""
        with db_write_lock(self._conn):
            outer_transaction = self._conn.in_transaction
            cur = self._conn.execute(
                "UPDATE share_links SET download_count = download_count + 1 "
                "WHERE id=? AND is_active=1 "
                "AND (expires_at IS NULL OR expires_at > ?) "
                "AND (max_downloads IS NULL OR download_count < max_downloads)",
                (share_id, time.time()),
            )
            _guarded_commit(self._conn, outer_transaction=outer_transaction)
            return cur.rowcount > 0

    @_repository_operation
    @locked_read
    def get_password_hash(self, share_id: str) -> str | None:
        """Return the password hash for a share link, or None."""
        row = self._conn.execute(
            "SELECT password_hash FROM share_links WHERE id=?",
            (share_id,),
        ).fetchone()
        return row[0] if row else None

    @_repository_operation
    def set_password_hash(self, share_id: str, password_hash: str) -> bool:
        """Replace a share link's password hash. Returns True if updated.

        Used by the cost-migration path after a successful verification so an
        existing share moves to the current PBKDF2 cost without the owner
        having to reset its password.
        """
        with db_write_lock(self._conn):
            outer_transaction = self._conn.in_transaction
            cur = self._conn.execute(
                "UPDATE share_links SET password_hash=? WHERE id=?",
                (password_hash, share_id),
            )
            _guarded_commit(self._conn, outer_transaction=outer_transaction)
            return cur.rowcount > 0

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
            "paths": self._decode_paths(paths_json),
            "password_hash": pw_hash,
            "expires_at": expires_at,
            "max_downloads": max_dl,
            "download_count": dl_count,
            "allow_preview": allow_prev,
            "created_by": created_by,
            "created_at": created_at,
        }
