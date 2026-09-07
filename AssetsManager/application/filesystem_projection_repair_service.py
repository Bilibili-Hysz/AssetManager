"""Durable repair executor for filesystem-backed library projections."""
from __future__ import annotations

import json
from pathlib import Path
from sqlite3 import OperationalError
from time import monotonic_ns

from AssetsManager.application.reconciliation_queue import (
    ReconciliationKind,
    ReconciliationTask,
    normalize_reconciliation_payload,
)
from AssetsManager.application.thumbnail_cache_lifecycle import cache_owner_lock
from AssetsManager.core.database import migrate_path_metadata


class FilesystemProjectionRepairTerminalError(ValueError):
    """Raised when a durable repair intent cannot be applied safely."""


class FilesystemProjectionRepairService:
    """Apply idempotent projection repairs after filesystem operations commit."""

    def __init__(self, *, session, asset_index_service, file_operation_service):
        self.session = session
        self.asset_index_service = asset_index_service
        self.file_operation_service = file_operation_service

    def repair(self, task: ReconciliationTask) -> None:
        if task.kind is not ReconciliationKind.FILESYSTEM_PROJECTION_REPAIR:
            raise FilesystemProjectionRepairTerminalError(
                f"unsupported repair task kind: {task.kind.value}"
            )
        try:
            payload = json.loads(task.payload)
        except (TypeError, json.JSONDecodeError) as exc:
            raise FilesystemProjectionRepairTerminalError(
                "invalid filesystem repair payload"
            ) from exc
        try:
            normalized = normalize_reconciliation_payload(
                task.kind, payload, library_root=self.session.root
            )
            payload = json.loads(normalized)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise FilesystemProjectionRepairTerminalError(
                "invalid filesystem repair payload"
            ) from exc
        operation_kind = payload.get("operation_kind")
        if operation_kind == "move":
            self._repair_move(payload)
        elif operation_kind == "delete":
            self._repair_delete(payload)
        elif operation_kind == "restore":
            self._repair_restore(payload)
        else:
            raise FilesystemProjectionRepairTerminalError(
                "unsupported filesystem repair operation"
            )

    def _repair_move(self, payload: dict[str, object]) -> None:
        source = self._root_path(payload.get("source_path"), "source_path")
        destination = self._root_path(
            payload.get("destination_path"), "destination_path"
        )
        is_directory = payload.get("is_directory")
        if not isinstance(is_directory, bool):
            raise FilesystemProjectionRepairTerminalError(
                "filesystem repair is_directory must be boolean"
            )
        if source.exists() or not destination.exists():
            raise FilesystemProjectionRepairTerminalError(
                "filesystem state conflicts with move repair intent"
            )
        conn = self.session.connection_for(self.session.root)
        with cache_owner_lock(self.session.thumb_dir):
            migrate_path_metadata(
                conn, self.session.thumb_dir, source, destination,
            )
        self._refresh_move(source, destination, is_directory)

    def _repair_delete(self, payload: dict[str, object]) -> None:
        target = self._root_path(payload.get("target_path"), "target_path")
        delete_mode = payload.get("delete_mode")
        if delete_mode not in {"permanent", "trash"}:
            raise FilesystemProjectionRepairTerminalError(
                "filesystem repair delete_mode is invalid"
            )
        if target.exists():
            raise FilesystemProjectionRepairTerminalError(
                "filesystem state conflicts with delete repair intent"
            )
        self.file_operation_service._clear_deleted_projection(
            target,
            publish_event=False,
        )
        self._refresh(target, False)

    def _repair_restore(self, payload: dict[str, object]) -> None:
        target = self._root_path(payload.get("target_path"), "target_path")
        if not target.exists():
            raise FilesystemProjectionRepairTerminalError(
                "filesystem state conflicts with restore repair intent"
            )
        snapshot = payload.get("snapshot")
        if not isinstance(snapshot, dict):
            raise FilesystemProjectionRepairTerminalError("restore snapshot is invalid")
        base = str(snapshot["base"])
        from AssetsManager.core.database import db_write_lock
        from AssetsManager.core.path_resolver import remap_path_subtree

        target_key = str(target.resolve())

        def map_path(value: object) -> str:
            if not isinstance(value, str):
                raise FilesystemProjectionRepairTerminalError(
                    "restore snapshot path is invalid"
                )
            return remap_path_subtree(base, target_key, value)

        conn = self.session.connection_for(self.session.root)
        savepoint = f"projection_restore_repair_{monotonic_ns():x}"
        with db_write_lock(conn):
            outer_transaction = conn.in_transaction
            try:
                conn.execute(f"SAVEPOINT {savepoint}")
                for file_path, tag in snapshot.get("file_tags", []):
                    conn.execute(
                        "INSERT OR IGNORE INTO file_tags (file_path, tag) VALUES (?, ?)",
                        (map_path(file_path), tag),
                    )
                for row in snapshot.get("file_meta", []):
                    file_path, notes, size, mtime, count, urls = row
                    conn.execute(
                        "INSERT INTO file_meta "
                        "(file_path, notes, cached_size, cached_mtime, cached_file_count, urls) "
                        "VALUES (?, ?, ?, ?, ?, ?) "
                        "ON CONFLICT(file_path) DO UPDATE SET "
                        "notes=CASE WHEN excluded.notes!='' THEN excluded.notes ELSE file_meta.notes END, "
                        "cached_size=COALESCE(excluded.cached_size, file_meta.cached_size), "
                        "cached_mtime=COALESCE(excluded.cached_mtime, file_meta.cached_mtime), "
                        "cached_file_count=COALESCE(excluded.cached_file_count, file_meta.cached_file_count), "
                        "urls=CASE WHEN excluded.urls!='[]' THEN excluded.urls ELSE file_meta.urls END",
                        (map_path(file_path), notes, size, mtime, count, urls),
                    )
                for owner_key, file_path, created_at in snapshot.get(
                    "library_favorites", []
                ):
                    conn.execute(
                        "INSERT OR IGNORE INTO library_favorites "
                        "(owner_key, file_path, created_at) VALUES (?, ?, ?)",
                        (owner_key, map_path(file_path), created_at),
                    )
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                if not outer_transaction:
                    conn.commit()
            except BaseException:
                try:
                    conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                finally:
                    if not outer_transaction and conn.in_transaction:
                        conn.rollback()
                raise
        self._refresh(target, bool(payload.get("is_directory")))

    def _root_path(self, value: object, field: str) -> Path:
        if not isinstance(value, str) or not value:
            raise FilesystemProjectionRepairTerminalError(
                f"filesystem repair {field} is required"
            )
        path = Path(value).resolve()
        if not path.is_relative_to(self.session.root):
            raise FilesystemProjectionRepairTerminalError(
                f"filesystem repair {field} escapes library root"
            )
        return path

    def _refresh_move(
        self, source: Path, destination: Path, is_directory: bool
    ) -> None:
        conn = self.session.connection_for(self.session.root)
        for parent in {source.parent, destination.parent}:
            result = self.asset_index_service.index_directory_result(
                conn, self.session.root, parent, force=True
            )
            self._require_committed(result, conn)
        if is_directory:
            result = self.asset_index_service.index_directory_tree_result(
                conn, self.session.root, destination
            )
            self._require_committed(result, conn)

    def _refresh(self, path: Path, is_directory: bool) -> None:
        conn = self.session.connection_for(self.session.root)
        if is_directory and path.is_dir():
            result = self.asset_index_service.index_directory_tree_result(
                conn, self.session.root, path
            )
            self._require_committed(result, conn)
        else:
            parent = path.parent if path.exists() else path.parent
            result = self.asset_index_service.index_directory_result(
                conn, self.session.root, parent, force=True
            )
            self._require_committed(result, conn)

    @staticmethod
    def _require_committed(result, conn) -> None:
        if getattr(result, "published", False):
            # Commit decision under the connection-owned write gate: an
            # unlocked ``in_transaction`` read could observe the
            # reconciliation worker's transaction on this shared connection
            # and commit IT mid-flight (round-3 recheck, transaction-sampling
            # root cause).
            from AssetsManager.core.database import db_write_lock
            with db_write_lock(conn):
                if conn.in_transaction:
                    conn.commit()
            return
        if not getattr(result, "published", False):
            failure = getattr(result, "failure", None)
            if isinstance(failure, OperationalError):
                raise failure
            raise RuntimeError(
                "filesystem projection repair index refresh did not commit"
            )
