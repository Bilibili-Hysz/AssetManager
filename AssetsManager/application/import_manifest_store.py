"""Durable import intents and restart-time projection recovery."""
from __future__ import annotations

from contextlib import contextmanager
import json
import logging
import re
from pathlib import Path
import sqlite3
import time
from typing import Iterator, Mapping
from uuid import uuid4

from AssetsManager.core.database import db_write_lock

_log = logging.getLogger(__name__)

IMPORT_MANIFEST_PAYLOAD_VERSION = 2
_IMPORT_MANIFEST_LEGACY_PAYLOAD_VERSION = 1
IMPORT_MANIFEST_MAX_ITEMS = 10_000
_COPY_ID_RE = re.compile(r"^import-[0-9a-f]+:[0-9]+$")
IMPORT_MANIFEST_MAX_BYTES = 512 * 1024
_IMPORT_STATES = {
    "prepared",
    "running",
    "completed",
    "degraded",
    "cancelled",
    "recovery_pending",
}
_RECOVERY_STATES = {"prepared", "running", "degraded", "recovery_pending"}
_TERMINAL_STATES = {"completed", "cancelled"}
_ITEM_TERMINAL_STATES = {"copied", "failed", "skipped"}
_ITEM_ALLOWED_TRANSITIONS = {
    "pending": _ITEM_TERMINAL_STATES,
    "copied": {"copied"},
    "failed": {"failed"},
    "skipped": {"skipped"},
}
_ALLOWED_TRANSITIONS = {
    "prepared": {"prepared", "running", "completed", "degraded", "cancelled", "recovery_pending"},
    "running": {"running", "completed", "degraded", "cancelled", "recovery_pending"},
    "degraded": {"degraded", "recovery_pending", "completed"},
    "recovery_pending": {"recovery_pending", "completed"},
    "completed": {"completed"},
    "cancelled": {"cancelled"},
}


def _canonical(path: str | Path) -> str:
    return str(Path(path).resolve())


def _validate_payload_header(
    data: Mapping[str, object], *, destination: Path
) -> tuple[object, list[object]]:
    """Validate the payload-level header shared by every write path.

    Returns the payload version and the item list so per-item validation can
    reuse both without re-deriving them.
    """
    payload_version = data.get("payload_version")
    if payload_version not in {
        _IMPORT_MANIFEST_LEGACY_PAYLOAD_VERSION,
        IMPORT_MANIFEST_PAYLOAD_VERSION,
    }:
        raise ValueError("unsupported import manifest payload version")
    if data.get("destination") != str(destination):
        raise ValueError("import manifest destination mismatch")
    items = data.get("items")
    if not isinstance(items, list) or not items or len(items) > IMPORT_MANIFEST_MAX_ITEMS:
        raise ValueError("import manifest items are invalid")
    return payload_version, items


def _validate_item(
    item: Mapping[str, object],
    *,
    root: Path,
    payload_version: object,
    copy_ids: set[str] | None = None,
) -> None:
    """Validate one manifest item in isolation.

    Raises ValueError on the first invalid field. ``copy_ids`` is only passed
    by whole-payload validation, which must enforce cross-item copy_id
    uniqueness; single-item callers omit it because stored payloads already
    guarantee uniqueness (every writer validates before persisting) and
    update_item never rewrites copy_id.
    """
    source = item.get("source")
    target = item.get("target")
    state = item.get("state")
    if not isinstance(source, str) or not source:
        raise ValueError("import manifest source is required")
    if not isinstance(target, str) or not target:
        raise ValueError("import manifest target is required")
    if not Path(target).resolve().is_relative_to(root):
        raise ValueError("import manifest target escapes library root")
    if state not in {"pending", "copied", "failed", "skipped"}:
        raise ValueError("import manifest item state is invalid")
    if payload_version == IMPORT_MANIFEST_PAYLOAD_VERSION:
        copy_id = item.get("copy_id")
        fingerprint = item.get("source_fingerprint")
        if not isinstance(copy_id, str) or not _COPY_ID_RE.fullmatch(copy_id):
            raise ValueError("import manifest copy_id is invalid")
        if copy_ids is not None:
            if copy_id in copy_ids:
                raise ValueError("import manifest copy_id is duplicated")
            copy_ids.add(copy_id)
        if not isinstance(fingerprint, Mapping):
            raise ValueError("import manifest source fingerprint is required")
        if (
            not isinstance(fingerprint.get("size"), int)
            or fingerprint["size"] < 0
            or not isinstance(fingerprint.get("mtime_ns"), int)
            or fingerprint["mtime_ns"] < 0
            or not isinstance(fingerprint.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", fingerprint["sha256"])
        ):
            raise ValueError("import manifest source fingerprint is invalid")


def _encode_payload(data: Mapping[str, object]) -> str:
    """Canonical JSON encoding with the payload size ceiling enforced."""
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > IMPORT_MANIFEST_MAX_BYTES:
        raise ValueError("import manifest payload is too large")
    return encoded


def _validate_payload(
    payload: Mapping[str, object], *, root: Path, destination: Path
) -> str:
    data = dict(payload)
    payload_version, items = _validate_payload_header(data, destination=destination)
    copy_ids: set[str] = set()
    for item in items:
        if not isinstance(item, Mapping):
            raise ValueError("import manifest item must be an object")
        _validate_item(item, root=root, payload_version=payload_version, copy_ids=copy_ids)
    return _encode_payload(data)


class ImportManifestStore:
    """CAS-backed store for one library's durable import intents."""

    def __init__(self, connection: sqlite3.Connection, library_root: str | Path):
        self.connection = connection
        self.library_root = Path(library_root).resolve()

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        outer = self.connection.in_transaction
        savepoint = f"import_manifest_{id(self):x}_{time.monotonic_ns()}"
        active = False
        owned = False
        try:
            with db_write_lock(self.connection):
                if outer:
                    self.connection.execute(f"SAVEPOINT {savepoint}")
                    active = True
                else:
                    self.connection.execute("BEGIN IMMEDIATE")
                    owned = True
                yield
                if active:
                    self.connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                elif owned:
                    self.connection.commit()
        except BaseException:
            if active:
                try:
                    self.connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                finally:
                    self.connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            elif owned and self.connection.in_transaction:
                self.connection.rollback()
            raise

    def create(
        self,
        *,
        operation_id: str,
        destination: str | Path,
        payload: Mapping[str, object],
        state: str = "prepared",
    ) -> None:
        if not operation_id or state not in _IMPORT_STATES:
            raise ValueError("invalid import manifest identity/state")
        destination_path = Path(destination).resolve()
        if not destination_path.is_relative_to(self.library_root):
            raise ValueError("import manifest destination escapes library root")
        encoded = _validate_payload(
            payload, root=self.library_root, destination=destination_path
        )
        now = time.time()
        with self._transaction():
            self.connection.execute(
                "INSERT INTO import_manifests ("
                "operation_id, library_root, destination, state, payload, generation, "
                "attempts, last_error_type, last_error, created_at, updated_at, "
                "recovery_claim_token, recovery_lease_expires_at"
                ") VALUES (?, ?, ?, ?, ?, 0, 0, NULL, NULL, ?, ?, NULL, NULL)",
                (
                    operation_id,
                    str(self.library_root),
                    str(destination_path),
                    state,
                    encoded,
                    now,
                    now,
                ),
            )

    def get(self, operation_id: str) -> dict[str, object] | None:
        return self._read_record(operation_id, validate=True)

    def _read_record(
        self, operation_id: str, *, validate: bool
    ) -> dict[str, object] | None:
        """Read one row; ``validate=False`` skips whole-payload revalidation.

        Update hot paths use ``validate=False`` because stored payloads only
        ever contain data that passed ``_validate_payload`` when written;
        re-validating every item on every single-item update is what made one
        import O(n^2). Rows that cannot even be decoded still surface as
        ``malformed`` records exactly as before.
        """
        with db_write_lock(self.connection):
            row = self.connection.execute(
                "SELECT operation_id, library_root, destination, state, payload, generation, "
                "attempts, last_error_type, last_error, created_at, updated_at, "
                "recovery_claim_token, recovery_lease_expires_at "
                "FROM import_manifests WHERE operation_id=? AND library_root=?",
                (operation_id, str(self.library_root)),
            ).fetchone()
        if row is None:
            return None
        try:
            return self._decode_row(row, validate=validate)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            return self._malformed_row(row, exc)

    def list_recovery(self) -> tuple[dict[str, object], ...]:
        with db_write_lock(self.connection):
            rows = self.connection.execute(
                "SELECT operation_id, library_root, destination, state, payload, generation, "
                "attempts, last_error_type, last_error, created_at, updated_at, "
                "recovery_claim_token, recovery_lease_expires_at "
                "FROM import_manifests WHERE library_root=? AND state IN (?, ?, ?, ?) "
                "ORDER BY updated_at, operation_id",
                (str(self.library_root), *_RECOVERY_STATES),
            ).fetchall()
        records: list[dict[str, object]] = []
        for row in rows:
            try:
                records.append(self._decode_row(row))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                records.append(self._malformed_row(row, exc))
        return tuple(records)

    def claim_recovery(
        self,
        record: Mapping[str, object],
        *,
        now: float | None = None,
        lease_seconds: float = 30.0,
    ) -> dict[str, object] | None:
        """Atomically claim one unresolved manifest for bounded recovery work."""
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        timestamp = time.time() if now is None else float(now)
        token = uuid4().hex
        expected_generation = int(record["generation"])
        expected_state = str(record["state"])
        operation_id = str(record["operation_id"])
        with self._transaction():
            cursor = self.connection.execute(
                "UPDATE import_manifests SET recovery_claim_token=?, "
                "recovery_lease_expires_at=?, generation=generation+1, updated_at=? "
                "WHERE operation_id=? AND library_root=? AND generation=? AND state=? "
                "AND state IN (?, ?, ?, ?) AND "
                "(recovery_claim_token IS NULL OR recovery_lease_expires_at IS NULL "
                "OR recovery_lease_expires_at <= ?)",
                (
                    token,
                    timestamp + lease_seconds,
                    timestamp,
                    operation_id,
                    str(self.library_root),
                    expected_generation,
                    expected_state,
                    *_RECOVERY_STATES,
                    timestamp,
                ),
            )
            if cursor.rowcount != 1:
                return None
        claimed = self.get(operation_id)
        if claimed is None:
            return None
        claimed["recovery_claim_token"] = token
        claimed["recovery_lease_expires_at"] = timestamp + lease_seconds
        return claimed

    def renew_recovery(
        self,
        record: Mapping[str, object],
        *,
        lease_seconds: float = 30.0,
        now: float | None = None,
    ) -> bool:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        timestamp = time.time() if now is None else float(now)
        with self._transaction():
            cursor = self.connection.execute(
                "UPDATE import_manifests SET recovery_lease_expires_at=?, "
                "generation=generation+1, updated_at=? "
                "WHERE operation_id=? AND library_root=? AND generation=? AND state=? "
                "AND recovery_claim_token=? AND recovery_lease_expires_at>?",
                (
                    timestamp + lease_seconds,
                    timestamp,
                    str(record["operation_id"]),
                    str(self.library_root),
                    int(record["generation"]),
                    str(record["state"]),
                    str(record["recovery_claim_token"]),
                    timestamp,
                ),
            )
            return cursor.rowcount == 1

    def update_item(
        self,
        operation_id: str,
        *,
        item_index: int,
        state: str,
        error: str | None = None,
    ) -> bool:
        if state not in {"copied", "failed", "skipped"}:
            raise ValueError("invalid import manifest item state")
        # Unchecked read: the record still supplies state/generation/destination
        # for the CAS below, but whole-payload revalidation is skipped. It is
        # sound to validate only the modified item because every write path
        # (create and update_item) validates its payload before persisting, so
        # stored items were validated when written and this update rewrites
        # just one item's state/error without touching its identity fields.
        record = self._read_record(operation_id, validate=False)
        if record is None:
            return False
        current_state = str(record["state"])
        if current_state in _TERMINAL_STATES:
            return False
        if "running" not in _ALLOWED_TRANSITIONS.get(current_state, set()):
            return False
        if record.get("malformed"):
            return False
        payload = dict(record["payload"])
        try:
            payload_version, stored_items = _validate_payload_header(
                payload, destination=Path(str(record["destination"]))
            )
        except ValueError:
            # Header corruption cannot originate from a validated write; keep
            # the historical malformed-record behavior of refusing the update.
            return False
        if item_index < 0 or item_index >= len(stored_items):
            raise IndexError("import manifest item index out of range")
        raw_item = stored_items[item_index]
        if not isinstance(raw_item, Mapping):
            return False
        item = dict(raw_item)
        current_item_state = item.get("state")
        if state not in _ITEM_ALLOWED_TRANSITIONS.get(str(current_item_state), set()):
            return False
        item["state"] = state
        item["error"] = error
        items = list(stored_items)
        items[item_index] = item
        payload["items"] = items
        try:
            _validate_item(item, root=self.library_root, payload_version=payload_version)
        except ValueError:
            # Same rationale as the header check above: refuse rather than
            # persist a payload that cannot be validated.
            return False
        # The whole-payload size ceiling is still enforced by this encode; the
        # per-item scan is what was removed.
        encoded = _encode_payload(payload)
        return self._cas_update(
            operation_id,
            expected_generation=int(record["generation"]),
            expected_state=current_state,
            state="running",
            payload=encoded,
        )

    def finish(
        self,
        operation_id: str,
        *,
        state: str,
        error: str | None = None,
        increment_attempts: bool = False,
    ) -> bool:
        if state not in _IMPORT_STATES:
            raise ValueError("invalid import manifest state")
        record = self.get(operation_id)
        if record is None or record.get("malformed"):
            return False
        current_state = str(record["state"])
        if state not in _ALLOWED_TRANSITIONS.get(current_state, set()):
            return False
        return self._cas_update(
            operation_id,
            expected_generation=int(record["generation"]),
            expected_state=current_state,
            state=state,
            payload=None,
            error=error,
            increment_attempts=increment_attempts,
        )

    def begin_replay(self, operation_id: str) -> dict[str, object] | None:
        """Claim one completed/failed import for explicit item replay."""
        record = self.get(operation_id)
        if record is None or record.get("malformed"):
            return None
        if str(record["state"]) not in {"completed", "degraded", "recovery_pending"}:
            return None
        payload = record.get("payload")
        if not isinstance(payload, Mapping) or payload.get("payload_version") != 2:
            return None
        if not any(
            isinstance(item, Mapping) and item.get("state") == "pending"
            for item in payload.get("items", ())
        ):
            return None
        if not self._cas_update(
            operation_id,
            expected_generation=int(record["generation"]),
            expected_state=str(record["state"]),
            state="running",
            payload=None,
        ):
            return None
        return self.get(operation_id)

    def finish_recovery(
        self,
        record: Mapping[str, object],
        *,
        state: str = "completed",
        error: str | None = None,
        increment_attempts: bool = True,
        now: float | None = None,
    ) -> bool:
        if state not in _IMPORT_STATES:
            raise ValueError("invalid import manifest state")
        timestamp = time.time() if now is None else float(now)
        return self._cas_update(
            str(record["operation_id"]),
            expected_generation=int(record["generation"]),
            expected_state=str(record["state"]),
            state=state,
            payload=None,
            error=error,
            increment_attempts=increment_attempts,
            claim_token=str(record["recovery_claim_token"]),
            require_live_claim=True,
            now=timestamp,
            clear_claim=True,
        )

    def record_recovery_failure(
        self,
        record: Mapping[str, object],
        error: BaseException,
        *,
        now: float | None = None,
    ) -> bool:
        """Keep an unresolved manifest diagnosable after recovery failure."""
        operation_id = str(record["operation_id"])
        expected_state = str(record["state"])
        try:
            updated = self._cas_update(
                operation_id,
                expected_generation=int(record["generation"]),
                expected_state=expected_state,
                state="recovery_pending",
                payload=None,
                error=str(error),
                error_type=type(error).__name__,
                increment_attempts=True,
                claim_token=(
                    str(record["recovery_claim_token"])
                    if record.get("recovery_claim_token")
                    else None
                ),
                require_live_claim=bool(record.get("recovery_claim_token")),
                now=time.time() if now is None else float(now),
                clear_claim=True,
            )
        except Exception as fallback_error:
            _log.warning(
                "Could not record import recovery failure for %s: %s; original=%s",
                operation_id,
                fallback_error,
                error,
            )
            return False
        if not updated:
            _log.warning(
                "Import recovery CAS lost for %s while recording: %s",
                operation_id,
                error,
            )
        return updated

    def _cas_update(
        self,
        operation_id: str,
        *,
        expected_generation: int,
        expected_state: str,
        state: str,
        payload: str | None,
        error: str | None = None,
        error_type: str | None = None,
        increment_attempts: bool = False,
        claim_token: str | None = None,
        require_live_claim: bool = False,
        now: float | None = None,
        clear_claim: bool = False,
    ) -> bool:
        timestamp = time.time() if now is None else float(now)
        with self._transaction():
            assignments = ["state=?", "generation=generation+1", "updated_at=?"]
            values: list[object] = [state, timestamp]
            if payload is not None:
                assignments.append("payload=?")
                values.append(payload)
            assignments.extend(["last_error_type=?", "last_error=?"])
            values.extend([error_type or (type(error).__name__ if error else None), error])
            if increment_attempts:
                assignments.append("attempts=attempts+1")
            if clear_claim:
                assignments.extend(["recovery_claim_token=NULL", "recovery_lease_expires_at=NULL"])
            values.extend([operation_id, str(self.library_root), expected_generation, expected_state])
            predicate = (
                " WHERE operation_id=? AND library_root=? AND generation=? AND state=?"
            )
            if claim_token is not None:
                predicate += " AND recovery_claim_token=?"
                values.append(claim_token)
            if require_live_claim:
                predicate += " AND recovery_lease_expires_at>?"
                values.append(timestamp)
            cursor = self.connection.execute(
                "UPDATE import_manifests SET "
                + ", ".join(assignments)
                + predicate,
                values,
            )
            return cursor.rowcount == 1

    def _decode_row(
        self, row: sqlite3.Row | tuple[object, ...], *, validate: bool = True
    ) -> dict[str, object]:
        values = tuple(row)
        library_root = Path(str(values[1])).resolve()
        destination = Path(str(values[2])).resolve()
        payload = json.loads(str(values[4]))
        if not isinstance(payload, dict):
            raise ValueError("import manifest payload must be an object")
        if validate:
            _validate_payload(payload, root=library_root, destination=destination)
        return {
            "operation_id": str(values[0]),
            "library_root": str(values[1]),
            "state": str(values[3]),
            "destination": str(values[2]),
            "payload": payload,
            "generation": int(values[5]),
            "attempts": int(values[6]),
            "last_error_type": values[7],
            "last_error": values[8],
            "created_at": float(values[9]),
            "updated_at": float(values[10]),
            "recovery_claim_token": values[11],
            "recovery_lease_expires_at": (
                float(values[12]) if values[12] is not None else None
            ),
        }

    @staticmethod
    def _malformed_row(
        row: sqlite3.Row | tuple[object, ...], error: Exception
    ) -> dict[str, object]:
        values = tuple(row)
        return {
            "operation_id": str(values[0]),
            "library_root": str(values[1]),
            "destination": str(values[2]),
            "state": str(values[3]),
            "payload": {},
            "generation": int(values[5]),
            "attempts": int(values[6]),
            "last_error_type": type(error).__name__,
            "last_error": str(error),
            "created_at": float(values[9]),
            "updated_at": float(values[10]),
            "recovery_claim_token": values[11] if len(values) > 11 else None,
            "recovery_lease_expires_at": (
                float(values[12]) if len(values) > 12 and values[12] is not None else None
            ),
            "malformed": True,
        }


class ImportManifestRecoveryService:
    """Turn unresolved import intents into durable root index rescans."""

    def __init__(self, store: ImportManifestStore, reconciliation_queue):
        self.store = store
        self.reconciliation_queue = reconciliation_queue

    def recover(self) -> tuple[str, ...]:
        recovered: list[str] = []
        for record in self.store.list_recovery():
            operation_id = str(record["operation_id"])
            claimed = self.store.claim_recovery(record)
            if claimed is None:
                continue
            if record.get("malformed"):
                self.store.record_recovery_failure(
                    claimed,
                    ValueError(str(record.get("last_error") or "malformed payload")),
                )
                continue
            try:
                self.reconciliation_queue.enqueue_or_merge(
                    path=self.store.library_root,
                    reason="import_manifest_recovery",
                    operation_id=operation_id,
                )
                if not self.store.finish_recovery(
                    claimed,
                    state="completed",
                    increment_attempts=True,
                ):
                    _log.warning(
                        "Import recovery finish CAS failed for %s after enqueue",
                        operation_id,
                    )
                    self.store.record_recovery_failure(
                        claimed,
                        RuntimeError("recovery finish CAS failed after enqueue"),
                    )
                    continue
                recovered.append(operation_id)
            except Exception as exc:
                self.store.record_recovery_failure(claimed, exc)
        return tuple(recovered)
