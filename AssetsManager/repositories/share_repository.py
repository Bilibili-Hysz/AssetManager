"""Share repository — persistence operations for share_links table.

Note: This repository handles only low-level CRUD. Business logic
(authentication, validation, token generation) lives in ShareService.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from sqlite3 import Connection, IntegrityError
from typing import Any, Callable, TypeVar

from AssetsManager.core.database import DatabaseManager, db_write_lock
from AssetsManager.core.path_resolver import RootIdentity, root_identity
from AssetsManager.core.schema_defs import validate_schema_objects
from AssetsManager.core.schema_defs import SHARE_LINKS_SCHEMA

_log = logging.getLogger(__name__)

# Compatibility alias: schema ownership lives in core.schema_defs / migration v6.



_R = TypeVar("_R")


def _repository_operation(method: Callable[..., _R]) -> Callable[..., _R]:
    @wraps(method)
    def wrapped(self: Any, *args: Any, **kwargs: Any) -> _R:
        with self._operation_scope():
            return method(self, *args, **kwargs)

    return wrapped


def _session_root(session: Any, repository_name: str) -> str | Path | RootIdentity:
    root = getattr(session, "root", None)
    if root is None:
        root = getattr(session, "root_str", None)
    if root is None:
        raise TypeError(
            f"{repository_name} canonical session requires root or root_str"
        )
    return root


def _require_session_contract(
    session: Any, repository_name: str
) -> tuple[Callable[..., Any], Callable[..., Any]]:
    operation = getattr(session, "operation", None)
    if not callable(operation):
        raise TypeError(
            f"{repository_name} canonical session requires callable operation()"
        )
    connection_for = getattr(session, "connection_for", None)
    if not callable(connection_for):
        raise TypeError(
            f"{repository_name} canonical session requires callable connection_for()"
        )
    return operation, connection_for


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


class ShareRepository:
    """Encapsulates share_links table operations."""

    def __init__(
        self,
        conn: Connection,
        *,
        library_root: str | Path | RootIdentity | None = None,
        session: Any | None = None,
    ):
        self._conn = conn
        self._session: Any | None = None
        self._library_root_key: str | None = None
        self._binding_lock = threading.RLock()
        if library_root is not None:
            identity = root_identity(library_root, strict=False)
            self._library_root_key = identity.map_key
            DatabaseManager.validate_connection_owner(
                identity, conn, allow_unmanaged=True
            )
        if session is not None:
            self._bind_session(session, library_root=library_root)

    @classmethod
    def for_session(cls, session: Any) -> "ShareRepository":
        """Build a strictly session/root-bound repository for a canonical session."""
        operation, connection_for = _require_session_contract(session, "ShareRepository")
        with operation():
            root = _session_root(session, "ShareRepository")
            conn = connection_for(root)
            conn = DatabaseManager.require_managed_connection_owner(root, conn)
            repository = cls(conn)
            repository._bind_session(session, library_root=root)
            return repository

    @contextmanager
    def _operation_scope(self):
        if self._session is None:
            yield
            return
        with self._session.operation():
            yield

    def _bind_session(
        self, session: Any, *, library_root: str | Path | RootIdentity | None = None
    ) -> None:
        with self._binding_lock:
            if self._session is not None:
                if self._session is session:
                    return
                raise RuntimeError(
                    "ShareRepository is already bound to another LibrarySession"
                )

            operation, connection_for = _require_session_contract(
                session, "ShareRepository"
            )
            session_root = _session_root(session, "ShareRepository")
            session_identity = root_identity(session_root, strict=False)
            if library_root is not None:
                explicit_identity = root_identity(library_root, strict=False)
                if explicit_identity.map_key != session_identity.map_key:
                    raise ValueError(
                        "ShareRepository library_root does not match the LibrarySession"
                    )
            if (
                self._library_root_key is not None
                and self._library_root_key != session_identity.map_key
            ):
                raise ValueError("ShareRepository belongs to a different library root")

            with operation():
                conn = connection_for(session_root)
                conn = DatabaseManager.require_managed_connection_owner(
                    session_identity, conn
                )
                if conn is not self._conn:
                    raise ValueError(
                        "ShareRepository connection does not belong to the LibrarySession"
                    )

                def publish_binding() -> None:
                    # `_session` is the readiness flag read by operation scopes,
                    # so publish all accompanying identity state before it.
                    self._library_root_key = session_identity.map_key
                    self._session = session

                publish_while_live = getattr(session, "_publish_while_live", None)
                if callable(publish_while_live):
                    publish_while_live(publish_binding)
                else:
                    publish_binding()

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
            cur = self._conn.execute(
                "UPDATE share_links SET is_active=0 WHERE id=?",
                (share_id,),
            )
            self._conn.commit()
            return cur.rowcount > 0

    @_repository_operation
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

    @_repository_operation
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
            "paths": self._decode_paths(paths_json),
            "password_hash": pw_hash,
            "expires_at": expires_at,
            "max_downloads": max_dl,
            "download_count": dl_count,
            "allow_preview": allow_prev,
            "created_by": created_by,
            "created_at": created_at,
        }
