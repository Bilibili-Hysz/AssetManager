"""Durable import intents and restart-time projection recovery."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import logging
import re
import threading
from pathlib import Path
import sqlite3
import time
from typing import Iterable, Iterator, Mapping, cast
from uuid import uuid4

from AssetsManager.application.reconciliation_queue import (
    IMPORT_MANIFEST_RECOVERY_CONSUMER_ID,
    ReconciliationTransitionDisposition,
)
from AssetsManager.core.database import db_write_lock

_log = logging.getLogger(__name__)

IMPORT_MANIFEST_PAYLOAD_VERSION = 2
_IMPORT_MANIFEST_LEGACY_PAYLOAD_VERSION = 1
# v1/v2 JSON payloads keep their historical hard ceilings for backwards
# compatibility.  Large v2 manifests are persisted as a v3 header plus rows
# in ``import_manifest_items`` instead of relaxing the legacy JSON limit.
IMPORT_MANIFEST_MAX_ITEMS = 10_000
IMPORT_MANIFEST_MAX_BYTES = 512 * 1024
IMPORT_MANIFEST_STREAM_PAYLOAD_VERSION = 3
IMPORT_MANIFEST_STREAM_FORMAT = "sqlite_items_v1"
IMPORT_MANIFEST_STREAM_MAX_ITEMS = 100_000
IMPORT_MANIFEST_STREAM_MAX_HEADER_BYTES = 16 * 1024
IMPORT_MANIFEST_STREAM_MAX_ROW_BYTES = 512 * 1024
IMPORT_MANIFEST_STREAM_MAX_TOTAL_BYTES = 256 * 1024 * 1024
_RECOVERY_RETIRED_TASK_ID_LIMIT = 16
_COPY_ID_RE = re.compile(r"^import-[0-9a-f]+:[0-9]+$")
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
_RECOVERY_PHASES = {
    "pending",
    "enqueued",
    "running",
    "retryable",
    "reconciled",
    "cancelled",
    "evicted",
    "dead_letter",
}
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
    manifest_format = data.get("manifest_format")
    allowed_versions = {
        _IMPORT_MANIFEST_LEGACY_PAYLOAD_VERSION,
        IMPORT_MANIFEST_PAYLOAD_VERSION,
        IMPORT_MANIFEST_STREAM_PAYLOAD_VERSION,
    }
    if payload_version not in allowed_versions:
        raise ValueError("unsupported import manifest payload version")
    recovery_phase = data.get("recovery_phase")
    if recovery_phase is not None and recovery_phase not in _RECOVERY_PHASES:
        raise ValueError("import manifest recovery phase is invalid")
    if data.get("destination") != str(destination):
        raise ValueError("import manifest destination mismatch")
    items = data.get("items")
    if payload_version == IMPORT_MANIFEST_STREAM_PAYLOAD_VERSION:
        if manifest_format != IMPORT_MANIFEST_STREAM_FORMAT:
            raise ValueError("stream import manifest format is invalid")
        item_count = data.get("item_count")
        if (
            not isinstance(item_count, int)
            or isinstance(item_count, bool)
            or item_count <= 0
            or item_count > IMPORT_MANIFEST_STREAM_MAX_ITEMS
        ):
            raise ValueError("stream import manifest header is invalid")
        item_bytes = data.get("item_bytes")
        items_sha256 = data.get("items_sha256")
        if (
            not isinstance(item_bytes, int)
            or isinstance(item_bytes, bool)
            or item_bytes < 0
            or item_bytes > IMPORT_MANIFEST_STREAM_MAX_TOTAL_BYTES
            or not isinstance(items_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", items_sha256)
        ):
            raise ValueError("stream import manifest accounting header is invalid")
        if items is None:
            return payload_version, []
        if (
            not isinstance(items, list)
            or not items
            or len(items) != item_count
            or len(items) > IMPORT_MANIFEST_STREAM_MAX_ITEMS
        ):
            raise ValueError("stream import manifest items are invalid")
        return payload_version, items
    if manifest_format is not None:
        raise ValueError("legacy import manifest has an unexpected format")
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
    if payload_version in {
        IMPORT_MANIFEST_PAYLOAD_VERSION,
        IMPORT_MANIFEST_STREAM_PAYLOAD_VERSION,
    }:
        copy_id = item.get("copy_id")
        fingerprint = item.get("source_fingerprint")
        if not isinstance(copy_id, str) or not _COPY_ID_RE.fullmatch(copy_id):
            raise ValueError("import manifest copy_id is invalid")
        if copy_ids is not None:
            if copy_id in copy_ids:
                raise ValueError("import manifest copy_id is duplicated")
            copy_ids.add(copy_id)
        if not isinstance(fingerprint, Mapping):
            # A source that could not be fingerprinted is represented as a
            # terminal failed/skipped item in a v2 manifest.  It must never be
            # replayable or copied without an identity snapshot; pending and
            # copied items still require the full fingerprint contract.
            if state not in {"failed", "skipped"}:
                raise ValueError("import manifest source fingerprint is required")
        else:
            if (
                not isinstance(fingerprint.get("size"), int)
                or fingerprint["size"] < 0
                or not isinstance(fingerprint.get("mtime_ns"), int)
                or fingerprint["mtime_ns"] < 0
                or not isinstance(fingerprint.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", fingerprint["sha256"])
            ):
                raise ValueError("import manifest source fingerprint is invalid")
            # New manifests also persist the source device/inode identity so a
            # same-size, same-mtime replacement cannot be replayed as the original
            # file.  These fields remain optional for payloads written by the v2
            # implementation before identity hardening; replay then falls back to
            # the size/mtime/hash checks already required above.
            for identity_key in ("device", "inode"):
                if identity_key in fingerprint and (
                    not isinstance(fingerprint[identity_key], int)
                    or isinstance(fingerprint[identity_key], bool)
                    or fingerprint[identity_key] < 0
                ):
                    raise ValueError("import manifest source fingerprint identity is invalid")


def _encode_payload(data: Mapping[str, object]) -> str:
    """Canonical JSON encoding with the payload size ceiling enforced."""
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > IMPORT_MANIFEST_MAX_BYTES:
        raise ValueError("import manifest payload is too large")
    return encoded


def _record_generation(record: Mapping[str, object]) -> int:
    """Read the persisted CAS generation counter (always stored as an int)."""
    return int(cast(int, record["generation"]))


def _recovery_retired_task_ids(payload: Mapping[str, object]) -> tuple[str, ...]:
    """Return the bounded, valid retired queue task ids in insertion order.

    The list is intentionally payload-backed instead of a new database table:
    it is tiny audit metadata for one manifest and must travel with the
    manifest CAS that supersedes a dead-letter task.  Invalid legacy/manual
    values are ignored rather than making an otherwise recoverable manifest
    unreadable.
    """
    raw_ids = payload.get("recovery_retired_task_ids")
    if not isinstance(raw_ids, (list, tuple)):
        return ()
    unique: list[str] = []
    for task_id in raw_ids:
        if not isinstance(task_id, str) or not task_id or task_id in unique:
            continue
        unique.append(task_id)
    return tuple(unique[-_RECOVERY_RETIRED_TASK_ID_LIMIT:])


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
    # A materialized v3 payload is useful to compatibility callers, but must
    # never be re-encoded into the parent row.  Only its bounded header is
    # persisted there; the item rows are validated separately by the store.
    if payload_version == IMPORT_MANIFEST_STREAM_PAYLOAD_VERSION:
        header = {key: value for key, value in data.items() if key != "items"}
        return _encode_payload(header)
    return _encode_payload(data)


def _canonical_item_bytes(item: Mapping[str, object]) -> bytes:
    """Return the stable identity representation used for stream accounting.

    ``state`` and ``error`` are mutable progress fields, so they are excluded
    from the checksum.  A single item update can therefore remain O(1) without
    rewriting the parent header or rehashing every row.
    """
    # Only persistently represented fields participate.  This keeps unknown
    # caller metadata from being hashed at creation and then disappearing
    # before a later row-backed read.
    identity = {
        key: item[key]
        for key in ("source", "relative", "target", "copy_id", "source_fingerprint")
        if key in item
    }
    return json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _stream_item_storage_bytes(item: Mapping[str, object]) -> bytes:
    """Return the full bounded row payload, including mutable diagnostics."""
    return json.dumps(
        dict(item), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _decode_stream_item_row(row: sqlite3.Row | tuple[object, ...]) -> dict[str, object]:
    """Decode one row using the same normalized shape used for hashing."""
    values = tuple(row)
    fingerprint = None
    if values[7] is not None:
        fingerprint = json.loads(str(values[7]))
        if not isinstance(fingerprint, Mapping):
            raise ValueError("stream import manifest fingerprint row is invalid")
    item: dict[str, object] = {
        "source": str(values[1]),
        "relative": str(values[2]),
        "target": str(values[3]),
        "state": str(values[4]),
        "copy_id": str(values[6]) if values[6] is not None else None,
    }
    if values[5] is not None:
        item["error"] = str(values[5])
    if fingerprint is not None:
        item["source_fingerprint"] = dict(fingerprint)
    return item


def _stream_header(
    *,
    destination: Path,
    item_count: int,
    item_bytes: int,
    items_sha256: str,
) -> dict[str, object]:
    header: dict[str, object] = {
        "payload_version": IMPORT_MANIFEST_STREAM_PAYLOAD_VERSION,
        "manifest_format": IMPORT_MANIFEST_STREAM_FORMAT,
        "destination": str(destination),
        "item_count": int(item_count),
        "item_bytes": int(item_bytes),
        "items_sha256": items_sha256,
    }
    encoded = json.dumps(
        header, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    if len(encoded) > IMPORT_MANIFEST_STREAM_MAX_HEADER_BYTES:
        raise ValueError("stream import manifest header is too large")
    return header


def _payload_requires_stream(payload: Mapping[str, object]) -> bool:
    """Select row-backed storage without weakening legacy JSON ceilings."""
    items = payload.get("items")
    if not isinstance(items, list):
        return False
    if len(items) > IMPORT_MANIFEST_MAX_ITEMS:
        return True
    try:
        encoded = json.dumps(
            dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError):
        return False
    return len(encoded) > IMPORT_MANIFEST_MAX_BYTES


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
        if payload.get("payload_version") == IMPORT_MANIFEST_STREAM_PAYLOAD_VERSION:
            # v3 is row-backed by definition.  Do not allow the convenience
            # API to create a parent header without its child rows.
            stream_items = payload.get("items")
            if not isinstance(stream_items, list) or not stream_items:
                raise ValueError("v3 import manifests must be created with item rows")
            raw_count = payload.get("item_count", len(stream_items))
            if not isinstance(raw_count, int) or raw_count != len(stream_items):
                raise ValueError("v3 import manifest item count is invalid")
            self.create_stream(
                operation_id=operation_id,
                destination=destination_path,
                items=stream_items,
                item_count=raw_count,
                state=state,
            )
            return
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

    def create_stream(
        self,
        *,
        operation_id: str,
        destination: str | Path,
        items: Iterable[Mapping[str, object]],
        item_count: int,
        state: str = "prepared",
    ) -> None:
        """Persist a row-backed v3 manifest in one atomic transaction.

        The parent row contains only a bounded header.  Item rows are inserted
        in batches while the iterator is consumed, so the JSON ceiling used by
        legacy v1/v2 manifests cannot reject a normal 100k-file import.  A
        failure at any point rolls back both the parent and every inserted row.
        """
        if not operation_id or state not in _IMPORT_STATES:
            raise ValueError("invalid import manifest identity/state")
        if (
            not isinstance(item_count, int)
            or isinstance(item_count, bool)
            or item_count <= 0
            or item_count > IMPORT_MANIFEST_STREAM_MAX_ITEMS
        ):
            raise ValueError("stream import manifest item count is invalid")
        destination_path = Path(destination).resolve()
        if not destination_path.is_relative_to(self.library_root):
            raise ValueError("import manifest destination escapes library root")

        now = time.time()
        digest = hashlib.sha256()
        item_bytes_total = 0
        seen_ids: set[str] = set()
        rows: list[tuple[object, ...]] = []
        observed = 0

        def flush_rows() -> None:
            if not rows:
                return
            self.connection.executemany(
                "INSERT INTO import_manifest_items ("
                "operation_id, library_root, item_index, source, relative, target, "
                "state, error, copy_id, source_fingerprint, row_bytes, created_at, "
                "updated_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            rows.clear()

        with self._transaction():
            for raw_item in items:
                if not isinstance(raw_item, Mapping):
                    raise ValueError("stream import manifest item must be an object")
                item = dict(raw_item)
                _validate_item(
                    item,
                    root=self.library_root,
                    payload_version=IMPORT_MANIFEST_STREAM_PAYLOAD_VERSION,
                    copy_ids=seen_ids,
                )
                error = item.get("error")
                if error is not None and not isinstance(error, str):
                    raise ValueError("stream import manifest item error is invalid")
                relative = item.get("relative", "")
                if not isinstance(relative, str):
                    raise ValueError("stream import manifest item relative path is invalid")
                item["relative"] = relative
                if error is None:
                    item.pop("error", None)
                canonical = _canonical_item_bytes(item)
                row_bytes = len(_stream_item_storage_bytes(item))
                if row_bytes > IMPORT_MANIFEST_STREAM_MAX_ROW_BYTES:
                    raise ValueError("stream import manifest item is too large")
                item_bytes_total += row_bytes
                if item_bytes_total > IMPORT_MANIFEST_STREAM_MAX_TOTAL_BYTES:
                    raise ValueError("stream import manifest metadata exceeds limit")
                digest.update(canonical)
                digest.update(b"\n")
                fingerprint = item.get("source_fingerprint")
                fingerprint_json = (
                    json.dumps(
                        dict(fingerprint),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    if isinstance(fingerprint, Mapping)
                    else None
                )
                rows.append(
                    (
                        operation_id,
                        str(self.library_root),
                        observed,
                        str(item["source"]),
                        relative,
                        str(item["target"]),
                        str(item["state"]),
                        error,
                        str(item["copy_id"]),
                        fingerprint_json,
                        row_bytes,
                        now,
                        now,
                    )
                )
                observed += 1
                if len(rows) >= 512:
                    flush_rows()
            flush_rows()
            if observed != item_count:
                raise ValueError(
                    f"stream import manifest item count mismatch: {observed} != {item_count}"
                )
            header = _stream_header(
                destination=destination_path,
                item_count=item_count,
                item_bytes=item_bytes_total,
                items_sha256=digest.hexdigest(),
            )
            encoded = _encode_payload(header)
            if len(encoded.encode("utf-8")) > IMPORT_MANIFEST_STREAM_MAX_HEADER_BYTES:
                raise ValueError("stream import manifest header is too large")
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

    @staticmethod
    def requires_stream(payload: Mapping[str, object]) -> bool:
        """Return whether a payload exceeds the legacy inline JSON envelope."""
        return _payload_requires_stream(payload)

    def _load_stream_items(
        self,
        operation_id: str,
        library_root: str,
        destination: Path,
        header: Mapping[str, object],
    ) -> list[dict[str, object]]:
        """Materialize and validate v3 rows for compatibility callers."""
        raw_count = header.get("item_count")
        raw_bytes = header.get("item_bytes")
        if not isinstance(raw_count, int) or not isinstance(raw_bytes, int):
            raise ValueError("stream import manifest accounting header is invalid")
        expected_count = raw_count
        expected_bytes = raw_bytes
        expected_digest = str(header["items_sha256"])
        with db_write_lock(self.connection):
            rows = self.connection.execute(
                "SELECT item_index, source, relative, target, state, error, copy_id, "
                "source_fingerprint, row_bytes FROM import_manifest_items "
                "WHERE operation_id=? AND library_root=? ORDER BY item_index",
                (operation_id, library_root),
            ).fetchall()
        if len(rows) != expected_count:
            raise ValueError("stream import manifest item rows are incomplete")
        digest = hashlib.sha256()
        item_bytes_total = 0
        items: list[dict[str, object]] = []
        for expected_index, row in enumerate(rows):
            item_index = int(row[0])
            if item_index != expected_index:
                raise ValueError("stream import manifest item indexes are not contiguous")
            item = _decode_stream_item_row(row)
            canonical = _canonical_item_bytes(item)
            recorded_bytes = int(row[8])
            if recorded_bytes != len(_stream_item_storage_bytes(item)):
                raise ValueError("stream import manifest row byte count is invalid")
            item_bytes_total += recorded_bytes
            if item_bytes_total > IMPORT_MANIFEST_STREAM_MAX_TOTAL_BYTES:
                raise ValueError("stream import manifest metadata exceeds limit")
            digest.update(canonical)
            digest.update(b"\n")
            _validate_item(
                item,
                root=self.library_root,
                payload_version=IMPORT_MANIFEST_STREAM_PAYLOAD_VERSION,
            )
            items.append(item)
        if item_bytes_total != expected_bytes or digest.hexdigest() != expected_digest:
            raise ValueError("stream import manifest item checksum mismatch")
        return items

    def _has_pending_stream_items(self, operation_id: str) -> bool:
        with db_write_lock(self.connection):
            row = self.connection.execute(
                "SELECT 1 FROM import_manifest_items WHERE operation_id=? "
                "AND library_root=? AND state='pending' LIMIT 1",
                (operation_id, str(self.library_root)),
            ).fetchone()
        return row is not None

    def _stream_structure_is_valid(
        self, operation_id: str, payload: Mapping[str, object]
    ) -> bool:
        raw_count = payload.get("item_count")
        if not isinstance(raw_count, int) or raw_count <= 0:
            return False
        try:
            with db_write_lock(self.connection):
                row = self.connection.execute(
                    "SELECT COUNT(*), MIN(item_index), MAX(item_index) "
                    "FROM import_manifest_items WHERE operation_id=? AND library_root=?",
                    (operation_id, str(self.library_root)),
                ).fetchone()
            if row is None:
                return False
            count, minimum, maximum = int(row[0]), row[1], row[2]
            return (
                count == raw_count
                and minimum == 0
                and maximum == raw_count - 1
            )
        except (sqlite3.Error, TypeError, ValueError, OverflowError):
            return False

    def has_pending_items(self, operation_id: str) -> bool:
        """Return whether an import has any replayable pending item."""
        record = self._read_record(operation_id, validate=True, include_items=False)
        if record is None or record.get("malformed"):
            return False
        payload = record.get("payload")
        if (
            not isinstance(payload, Mapping)
            or payload.get("payload_version")
            not in {
                IMPORT_MANIFEST_PAYLOAD_VERSION,
                IMPORT_MANIFEST_STREAM_PAYLOAD_VERSION,
            }
        ):
            return False
        if payload.get("payload_version") == IMPORT_MANIFEST_STREAM_PAYLOAD_VERSION:
            return self._stream_structure_is_valid(operation_id, payload) and self._has_pending_stream_items(operation_id)
        items = payload.get("items")
        return isinstance(items, list) and any(
            isinstance(item, Mapping) and item.get("state") == "pending"
            for item in items
        )

    def iter_items(
        self,
        operation_id: str,
        *,
        states: set[str] | frozenset[str] | None = None,
    ) -> Iterator[tuple[int, dict[str, object]]]:
        """Yield manifest items without materializing a v3 payload."""
        record = self._read_record(operation_id, validate=True, include_items=False)
        if record is None or record.get("malformed"):
            return
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            return
        wanted = set(states) if states is not None else None
        if payload.get("payload_version") != IMPORT_MANIFEST_STREAM_PAYLOAD_VERSION:
            items = payload.get("items")
            if not isinstance(items, list):
                return
            for index, raw_item in enumerate(items):
                if not isinstance(raw_item, Mapping):
                    raise ValueError("import manifest item must be an object")
                item = dict(raw_item)
                if wanted is None or str(item.get("state")) in wanted:
                    yield index, item
            return

        raw_count = payload.get("item_count")
        raw_bytes = payload.get("item_bytes")
        raw_digest = payload.get("items_sha256")
        if (
            not isinstance(raw_count, int)
            or not isinstance(raw_bytes, int)
            or not isinstance(raw_digest, str)
        ):
            raise ValueError("stream import manifest accounting header is invalid")
        expected_count = raw_count
        expected_bytes = raw_bytes
        expected_digest = raw_digest
        digest = hashlib.sha256()
        item_bytes_total = 0
        observed = 0
        last_index = -1
        while True:
            with db_write_lock(self.connection):
                batch = self.connection.execute(
                    "SELECT item_index, source, relative, target, state, error, copy_id, "
                    "source_fingerprint, row_bytes FROM import_manifest_items "
                    "WHERE operation_id=? AND library_root=? AND item_index>? "
                    "ORDER BY item_index LIMIT 256",
                    (operation_id, str(self.library_root), last_index),
                ).fetchall()
            if not batch:
                break
            decoded_batch: list[tuple[int, dict[str, object]]] = []
            for row in batch:
                item_index = int(row[0])
                if item_index != observed:
                    raise ValueError("stream import manifest item indexes are not contiguous")
                item = _decode_stream_item_row(row)
                canonical = _canonical_item_bytes(item)
                recorded_bytes = int(row[8])
                if recorded_bytes != len(_stream_item_storage_bytes(item)):
                    raise ValueError("stream import manifest row byte count is invalid")
                item_bytes_total += recorded_bytes
                digest.update(canonical)
                digest.update(b"\n")
                _validate_item(
                    item,
                    root=self.library_root,
                    payload_version=IMPORT_MANIFEST_STREAM_PAYLOAD_VERSION,
                )
                decoded_batch.append((item_index, item))
                observed += 1
                last_index = item_index
            for item_index, item in decoded_batch:
                if wanted is None or str(item.get("state")) in wanted:
                    yield item_index, item
        if (
            observed != expected_count
            or item_bytes_total != expected_bytes
            or digest.hexdigest() != expected_digest
        ):
            raise ValueError("stream import manifest item checksum mismatch")

    def _stream_items_are_intact(
        self, operation_id: str, payload: Mapping[str, object]
    ) -> bool:
        """Verify a v3 row set before it can become terminal.

        Recovery must not turn a header with missing or altered item rows into
        a completed manifest merely because a root-rescan task succeeded.  The
        verification is intentionally deferred to terminal transitions so
        ordinary recovery scanning does not materialize every large intent.
        """
        if payload.get("payload_version") != IMPORT_MANIFEST_STREAM_PAYLOAD_VERSION:
            return True
        try:
            for _item_index, _item in self.iter_items(operation_id):
                pass
        except (TypeError, ValueError, json.JSONDecodeError, sqlite3.Error):
            return False
        return True

    def get(
        self, operation_id: str, *, include_items: bool = True
    ) -> dict[str, object] | None:
        return self._read_record(operation_id, validate=True, include_items=include_items)

    def _read_record(
        self, operation_id: str, *, validate: bool, include_items: bool = True
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
            return self._decode_row(row, validate=validate, include_items=include_items)
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
                records.append(self._decode_row(row, include_items=False))
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
        expected_generation = _record_generation(record)
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
        claimed = self.get(operation_id, include_items=False)
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
                    _record_generation(record),
                    str(record["state"]),
                    str(record["recovery_claim_token"]),
                    timestamp,
                ),
            )
            return cursor.rowcount == 1

    def _update_stream_item(
        self,
        record: Mapping[str, object],
        *,
        item_index: int,
        state: str,
        error: str | None,
    ) -> bool:
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            return False
        try:
            _validate_payload_header(
                payload, destination=Path(str(record["destination"]))
            )
        except ValueError:
            return False
        raw_item_count = payload.get("item_count")
        raw_item_bytes = payload.get("item_bytes")
        if not isinstance(raw_item_count, int) or not isinstance(raw_item_bytes, int):
            return False
        if item_index < 0 or item_index >= raw_item_count:
            raise IndexError("import manifest item index out of range")
        if error is not None and not isinstance(error, str):
            return False
        operation_id = str(record["operation_id"])
        library_root = str(self.library_root)
        timestamp = time.time()
        with self._transaction():
            row = self.connection.execute(
                "SELECT item_index, source, relative, target, state, error, copy_id, "
                "source_fingerprint, row_bytes FROM import_manifest_items "
                "WHERE operation_id=? AND library_root=? AND item_index=?",
                (operation_id, library_root, item_index),
            ).fetchone()
            if row is None:
                raise ValueError("stream import manifest item row is missing")
            item = _decode_stream_item_row(row)
            current_item_state = str(item.get("state"))
            if state not in _ITEM_ALLOWED_TRANSITIONS.get(current_item_state, set()):
                return False
            item["state"] = state
            if error is None:
                item.pop("error", None)
            else:
                item["error"] = error
            _validate_item(
                item,
                root=self.library_root,
                payload_version=IMPORT_MANIFEST_STREAM_PAYLOAD_VERSION,
            )
            row_bytes = len(_stream_item_storage_bytes(item))
            if row_bytes > IMPORT_MANIFEST_STREAM_MAX_ROW_BYTES:
                return False
            previous_row_bytes = int(row[8])
            next_total_bytes = raw_item_bytes - previous_row_bytes + row_bytes
            if (
                previous_row_bytes < 0
                or next_total_bytes < 0
                or next_total_bytes > IMPORT_MANIFEST_STREAM_MAX_TOTAL_BYTES
            ):
                return False
            updated_payload = dict(payload)
            updated_payload["item_bytes"] = next_total_bytes
            encoded_payload = _encode_payload(updated_payload)
            if len(encoded_payload.encode("utf-8")) > IMPORT_MANIFEST_STREAM_MAX_HEADER_BYTES:
                return False
            parent_cursor = self.connection.execute(
                "UPDATE import_manifests SET state='running', payload=?, generation=generation+1, "
                "updated_at=?, last_error_type=NULL, last_error=NULL "
                "WHERE operation_id=? AND library_root=? AND generation=? AND state=?",
                (
                    encoded_payload,
                    timestamp,
                    operation_id,
                    library_root,
                    _record_generation(record),
                    str(record["state"]),
                ),
            )
            if parent_cursor.rowcount != 1:
                return False
            fingerprint = item.get("source_fingerprint")
            fingerprint_json = (
                json.dumps(
                    dict(fingerprint),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if isinstance(fingerprint, Mapping)
                else None
            )
            item_cursor = self.connection.execute(
                "UPDATE import_manifest_items SET state=?, error=?, copy_id=?, "
                "source_fingerprint=?, row_bytes=?, updated_at=? WHERE operation_id=? "
                "AND library_root=? AND item_index=?",
                (
                    state,
                    error,
                    str(item["copy_id"]),
                    fingerprint_json,
                    row_bytes,
                    timestamp,
                    operation_id,
                    library_root,
                    item_index,
                ),
            )
            if item_cursor.rowcount != 1:
                raise ValueError("stream import manifest item row disappeared")
            return True

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
        record = self._read_record(
            operation_id,
            validate=False,
            include_items=False,
        )
        if record is None:
            return False
        current_state = str(record["state"])
        if current_state in _TERMINAL_STATES:
            return False
        if "running" not in _ALLOWED_TRANSITIONS.get(current_state, set()):
            return False
        if record.get("malformed"):
            return False
        payload = dict(cast(Mapping[str, object], record["payload"]))
        if payload.get("payload_version") == IMPORT_MANIFEST_STREAM_PAYLOAD_VERSION:
            return self._update_stream_item(
                record,
                item_index=item_index,
                state=state,
                error=error,
            )
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
            expected_generation=_record_generation(record),
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
        record = self.get(operation_id, include_items=False)
        if record is None or record.get("malformed"):
            return False
        current_state = str(record["state"])
        if state not in _ALLOWED_TRANSITIONS.get(current_state, set()):
            return False
        payload = record.get("payload")
        if (
            state == "completed"
            and isinstance(payload, Mapping)
            and not self._stream_items_are_intact(operation_id, payload)
        ):
            return False
        return self._cas_update(
            operation_id,
            expected_generation=_record_generation(record),
            expected_state=current_state,
            state=state,
            payload=None,
            error=error,
            increment_attempts=increment_attempts,
        )

    def begin_replay(self, operation_id: str) -> dict[str, object] | None:
        """Claim one completed/failed import for explicit item replay."""
        record = self.get(operation_id, include_items=False)
        if record is None or record.get("malformed"):
            return None
        if str(record["state"]) not in {"completed", "degraded", "recovery_pending"}:
            return None
        payload = record.get("payload")
        if not isinstance(payload, Mapping) or payload.get("payload_version") not in {
            IMPORT_MANIFEST_PAYLOAD_VERSION,
            IMPORT_MANIFEST_STREAM_PAYLOAD_VERSION,
        }:
            return None
        if not self.has_pending_items(operation_id):
            return None
        if not self._cas_update(
            operation_id,
            expected_generation=_record_generation(record),
            expected_state=str(record["state"]),
            state="running",
            payload=None,
        ):
            return None
        return self.get(operation_id, include_items=False)

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
        payload = record.get("payload")
        if (
            state == "completed"
            and isinstance(payload, Mapping)
            and not self._stream_items_are_intact(
                str(record["operation_id"]), payload
            )
        ):
            return False
        timestamp = time.time() if now is None else float(now)
        return self._cas_update(
            str(record["operation_id"]),
            expected_generation=_record_generation(record),
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

    def bind_recovery_task(
        self,
        record: Mapping[str, object],
        task_id: str,
        *,
        now: float | None = None,
        allow_rebind: bool = False,
    ) -> bool:
        """Persist the queue task that owns a recovery intent.

        Enqueue and manifest updates intentionally remain separate durable
        transactions: if the process exits between them, a later recovery pass
        can enqueue/merge by ``operation_id`` and bind the same task.  The
        manifest is kept non-terminal until :meth:`acknowledge_recovery` sees a
        successful queue completion.
        """
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("recovery task_id is required")
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            return False
        current_state = str(record.get("state"))
        if current_state not in _RECOVERY_STATES:
            return False
        existing_task = payload.get("recovery_task_id")
        # A manual retry deliberately supersedes its terminal queue task.  A
        # delayed listener/startup event for that old task must never reclaim
        # the newly-unbound manifest during the enqueue→bind window.
        if task_id in _recovery_retired_task_ids(payload):
            return False
        if (
            existing_task is not None
            and str(existing_task) != task_id
            and not allow_rebind
        ):
            return False
        updated_payload = dict(payload)
        updated_payload["recovery_task_id"] = task_id
        updated_payload["recovery_phase"] = "enqueued"
        updated_payload["recovery_enqueued_at"] = time.time() if now is None else float(now)
        encoded = _encode_payload(updated_payload)
        claim_token = record.get("recovery_claim_token")
        return self._cas_update(
            str(record["operation_id"]),
            expected_generation=_record_generation(record),
            expected_state=current_state,
            state="recovery_pending",
            payload=encoded,
            claim_token=str(claim_token) if claim_token else None,
            require_live_claim=bool(claim_token),
            now=time.time() if now is None else float(now),
            clear_claim=True,
        )

    def bind_existing_recovery_task(
        self,
        operation_id: str,
        task_id: str,
        *,
        now: float | None = None,
    ) -> bool:
        """Bind a task found after a crash between enqueue and metadata CAS."""
        record = self.get(operation_id, include_items=False)
        if record is None or record.get("malformed"):
            return False
        return self.bind_recovery_task(record, task_id, now=now)

    def mark_recovery_running(
        self,
        operation_id: str,
        task_id: str,
        *,
        now: float | None = None,
    ) -> bool:
        """Record that the reconciliation worker has claimed the task."""
        record = self.get(operation_id, include_items=False)
        if record is None or record.get("malformed"):
            return False
        if str(record.get("state")) not in _RECOVERY_STATES:
            return str(record.get("state")) == "completed"
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            return False
        bound = payload.get("recovery_task_id")
        # A running worker must first observe the enqueue→bind CAS.  Allowing
        # an unbound task to write here would create a second ownership path
        # after a crash and can make an unrelated task appear authoritative.
        if bound is None or str(bound) != task_id:
            return False
        updated_payload = dict(payload)
        updated_payload["recovery_task_id"] = task_id
        updated_payload["recovery_phase"] = "running"
        updated_payload["recovery_started_at"] = time.time() if now is None else float(now)
        return self._cas_update(
            operation_id,
            expected_generation=_record_generation(record),
            expected_state=str(record["state"]),
            state="recovery_pending",
            payload=_encode_payload(updated_payload),
            now=time.time() if now is None else float(now),
        )

    def acknowledge_recovery(
        self,
        operation_id: str,
        task_id: str,
        *,
        now: float | None = None,
    ) -> bool:
        """Move an import intent to ``completed`` only after queue ACK.

        The operation is idempotent for the same task.  A mismatched task is
        rejected so an unrelated root rescan cannot accidentally hide a
        still-unreconciled import.
        """
        record = self.get(operation_id, include_items=False)
        if record is None or record.get("malformed"):
            return False
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            return False
        bound = payload.get("recovery_task_id")
        state = str(record.get("state"))
        if state in _TERMINAL_STATES:
            # Preserve idempotence for legacy completed rows that predate
            # durable task ids; no state transition is possible in this path.
            return state == "completed" and (bound is None or str(bound) == task_id)
        # Non-terminal manifests require an explicit binding.  Otherwise a
        # worker could invent ownership after an enqueue/bind crash window.
        if bound is None or str(bound) != task_id:
            return False
        if state not in _RECOVERY_STATES:
            return False
        if not self._stream_items_are_intact(operation_id, payload):
            return False
        timestamp = time.time() if now is None else float(now)
        updated_payload = dict(payload)
        updated_payload["recovery_task_id"] = task_id
        updated_payload["recovery_phase"] = "reconciled"
        updated_payload["recovery_ack_at"] = timestamp
        return self._cas_update(
            operation_id,
            expected_generation=_record_generation(record),
            expected_state=state,
            state="completed",
            payload=_encode_payload(updated_payload),
            increment_attempts=True,
            now=timestamp,
            clear_claim=True,
        )

    def request_recovery_retry(
        self,
        operation_id: str,
        *,
        now: float | None = None,
    ) -> bool:
        """Explicitly re-open a dead-lettered or cancelled recovery hand-off.

        This is intentionally a manifest-level CAS rather than a queue edit.
        The terminal task remains in the queue audit history, while the
        manifest forgets its active binding and records that the old task is
        retired.  A following recovery pass can therefore create a new queue
        task without allowing a delayed event for the old task to dead-letter
        the new attempt again.

        ``True`` means this call durably accepted a new retry request; it does
        not imply that a worker has completed the replacement rescan.
        """
        if not isinstance(operation_id, str) or not operation_id:
            return False
        timestamp = time.time() if now is None else float(now)
        # A second read handles the ordinary two-writer race: the winner moves
        # the phase to pending, and the loser observes that the request has
        # already been accepted instead of creating a duplicate retry.
        for _ in range(2):
            record = self.get(operation_id, include_items=False)
            if record is None or record.get("malformed"):
                return False
            if str(record.get("state")) != "recovery_pending":
                return False
            payload = record.get("payload")
            if not isinstance(payload, Mapping):
                return False
            previous_phase = payload.get("recovery_phase")
            if previous_phase not in {"dead_letter", "cancelled"}:
                return False
            previous_task_id = payload.get("recovery_task_id")
            if not isinstance(previous_task_id, str) or not previous_task_id:
                # A terminal phase without a durable queue identity cannot be
                # safely superseded: accepting it would reopen the old
                # allow-unbound ownership hole.
                return False

            updated_payload = dict(payload)
            retired_task_ids = list(_recovery_retired_task_ids(payload))
            if previous_task_id not in retired_task_ids:
                retired_task_ids.append(previous_task_id)
            updated_payload["recovery_retired_task_ids"] = retired_task_ids[
                -_RECOVERY_RETIRED_TASK_ID_LIMIT:
            ]
            raw_retry_count = payload.get("recovery_retry_count", 0)
            retry_count = (
                raw_retry_count
                if isinstance(raw_retry_count, int)
                and not isinstance(raw_retry_count, bool)
                and raw_retry_count >= 0
                else 0
            )
            updated_payload["recovery_retry_count"] = retry_count + 1
            updated_payload["recovery_retry_requested_at"] = timestamp
            updated_payload["recovery_retry_superseded_task_id"] = previous_task_id
            updated_payload["recovery_phase"] = "pending"
            for key in (
                "recovery_task_id",
                "recovery_enqueued_at",
                "recovery_started_at",
                "recovery_ack_at",
                "recovery_task_attempts",
                "recovery_task_error_type",
                "recovery_task_error",
                "recovery_transition_marker",
                "recovery_transition_at",
                "recovery_evicted_task_id",
            ):
                updated_payload.pop(key, None)
            try:
                encoded = _encode_payload(updated_payload)
                if (
                    updated_payload.get("payload_version")
                    == IMPORT_MANIFEST_STREAM_PAYLOAD_VERSION
                    and len(encoded.encode("utf-8"))
                    > IMPORT_MANIFEST_STREAM_MAX_HEADER_BYTES
                ):
                    return False
            except (TypeError, ValueError):
                return False
            if self._cas_update(
                operation_id,
                expected_generation=_record_generation(record),
                expected_state="recovery_pending",
                state="recovery_pending",
                payload=encoded,
                now=timestamp,
                clear_claim=True,
            ):
                return True
        return False

    def record_recovery_task_transition(
        self,
        operation_id: str,
        task_id: str,
        task_state: str,
        *,
        task_attempts: int | None = None,
        error_type: str | None = None,
        error: str | None = None,
        now: float | None = None,
        allow_unbound: bool = False,
    ) -> bool:
        """Persist a queue outcome for one import operation.

        Queue state and manifest state live in separate tables/transactions.
        This method is the single CAS boundary used by the queue transition
        observer: success is ACKed, retryable work remains visibly pending,
        terminal/cancelled work is dead-lettered, and an evicted task loses its
        binding so the next recovery pass can enqueue a replacement.  Every
        operation id is checked independently, which is important when one
        root-rescan task is merged for several imports.

        ``allow_unbound`` is only for the enqueue→bind crash window.  Callers
        must have already validated the task's library/path/kind scope before
        enabling it.
        """
        if not isinstance(operation_id, str) or not operation_id:
            return False
        if not isinstance(task_id, str) or not task_id:
            return False
        state = str(task_state).lower()
        if state in {"succeeded", "success", "completed"}:
            normalized_state = "succeeded"
        elif state in {"retryable", "retry", "pending"}:
            normalized_state = "retryable"
        elif state in {"terminal", "dead_letter", "dead-letter"}:
            normalized_state = "terminal"
        elif state in {"cancelled", "canceled", "cancel"}:
            normalized_state = "cancelled"
        elif state in {"running", "in_progress"}:
            normalized_state = "running"
        elif state in {"evicted", "missing"}:
            normalized_state = "evicted"
        else:
            return False
        if task_attempts is not None and (
            not isinstance(task_attempts, int)
            or isinstance(task_attempts, bool)
            or task_attempts < 0
        ):
            return False

        # A bounded retry handles two workers observing the same queue event at
        # once.  The second read sees the first CAS and becomes idempotent.
        for _ in range(2):
            record = self.get(operation_id, include_items=False)
            if record is None or record.get("malformed"):
                return False
            payload = record.get("payload")
            # ``request_recovery_retry`` makes the previous task identity
            # permanently ineligible for this manifest attempt.  Check this
            # before terminal-state handling as an old event can arrive even
            # after the replacement task has completed.
            if (
                isinstance(payload, Mapping)
                and task_id in _recovery_retired_task_ids(payload)
            ):
                return True
            manifest_state = str(record.get("state"))
            if manifest_state == "completed":
                bound = (
                    payload.get("recovery_task_id")
                    if isinstance(payload, Mapping)
                    else None
                )
                return normalized_state == "succeeded" and (
                    bound is None or str(bound) == task_id
                )
            if manifest_state == "cancelled":
                bound = (
                    payload.get("recovery_task_id")
                    if isinstance(payload, Mapping)
                    else None
                )
                # A cancelled manifest is terminal from the import
                # perspective.  Only the task which owns its recovery binding
                # may repeat that terminal observation; an unrelated task (or
                # a forged transition) must not be accepted as an ACK.
                return normalized_state in {"cancelled", "terminal"} and (
                    bound is not None and str(bound) == task_id
                )
            if manifest_state not in _RECOVERY_STATES:
                return False
            if not isinstance(payload, Mapping):
                return False
            payload_dict = dict(payload)
            bound = payload_dict.get("recovery_task_id")
            if bound is not None and str(bound) != task_id:
                return False
            if bound is None and not allow_unbound and normalized_state != "evicted":
                return False
            if normalized_state == "evicted" and bound is not None and str(bound) != task_id:
                return False

            # Queue events can arrive out of order after a lease takeover or a
            # listener retry.  An older attempt must never regress a newer
            # running/retryable/terminal phase.  Treat it as an idempotent
            # no-op so the caller does not keep retrying an event that can no
            # longer change durable state.
            recorded_attempts = payload_dict.get("recovery_task_attempts")
            if (
                task_attempts is not None
                and isinstance(recorded_attempts, int)
                and not isinstance(recorded_attempts, bool)
                and task_attempts < recorded_attempts
            ):
                return True

            previous_phase = payload_dict.get("recovery_phase")
            previous_marker = payload_dict.get("recovery_transition_marker")
            marker = f"{task_id}:{normalized_state}:{task_attempts if task_attempts is not None else ''}"
            # Replaying the same durable queue event must not increment the
            # manifest attempt counter repeatedly.
            if previous_marker == marker:
                return True

            timestamp = time.time() if now is None else float(now)
            increment_attempts = False
            clear_claim = False
            next_state = "recovery_pending"
            if normalized_state == "succeeded":
                if bound is None:
                    if not allow_unbound:
                        return False
                    if not self.bind_existing_recovery_task(
                        operation_id, task_id, now=timestamp
                    ):
                        continue
                    # Re-read after the binding CAS so ACK uses the fresh
                    # generation and cannot overwrite a concurrent update.
                    continue
                return self.acknowledge_recovery(operation_id, task_id, now=timestamp)

            if normalized_state == "running":
                if bound is None:
                    if not allow_unbound:
                        return False
                    if not self.bind_existing_recovery_task(
                        operation_id, task_id, now=timestamp
                    ):
                        continue
                    continue
                updated_phase = "running"
            elif normalized_state == "retryable":
                updated_phase = "retryable"
                # A retry is an observable queue outcome, but it is not a new
                # manifest recovery claim.  Count it only when the task's
                # attempt number advances (or when no attempt metadata exists).
                increment_attempts = bool(
                    task_attempts is None
                    or payload_dict.get("recovery_task_attempts") != task_attempts
                )
            elif normalized_state == "cancelled":
                updated_phase = "cancelled"
                increment_attempts = previous_phase != "cancelled"
                clear_claim = True
            elif normalized_state == "terminal":
                updated_phase = "dead_letter"
                increment_attempts = previous_phase != "dead_letter"
                clear_claim = True
            else:  # evicted
                updated_phase = "pending"
                increment_attempts = previous_phase not in {"pending", "evicted"}
                clear_claim = True

            if normalized_state == "evicted":
                payload_dict.pop("recovery_task_id", None)
                payload_dict["recovery_evicted_task_id"] = task_id
            else:
                payload_dict["recovery_task_id"] = task_id
            payload_dict["recovery_phase"] = updated_phase
            payload_dict["recovery_transition_marker"] = marker
            payload_dict["recovery_transition_at"] = timestamp
            if task_attempts is not None:
                payload_dict["recovery_task_attempts"] = task_attempts
            if error_type is not None:
                payload_dict["recovery_task_error_type"] = str(error_type)
            if error is not None:
                payload_dict["recovery_task_error"] = str(error)
            elif normalized_state == "running":
                payload_dict.pop("recovery_task_error", None)
                payload_dict.pop("recovery_task_error_type", None)
            try:
                encoded = _encode_payload(payload_dict)
                if payload_dict.get("payload_version") == IMPORT_MANIFEST_STREAM_PAYLOAD_VERSION:
                    if len(encoded.encode("utf-8")) > IMPORT_MANIFEST_STREAM_MAX_HEADER_BYTES:
                        return False
            except (TypeError, ValueError):
                return False
            updated = self._cas_update(
                operation_id,
                expected_generation=_record_generation(record),
                expected_state=manifest_state,
                state=next_state,
                payload=encoded,
                error=error,
                error_type=error_type,
                increment_attempts=increment_attempts,
                now=timestamp,
                clear_claim=clear_claim,
            )
            if updated:
                return True
        return False

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
                expected_generation=_record_generation(record),
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
        self,
        row: sqlite3.Row | tuple[object, ...],
        *,
        validate: bool = True,
        include_items: bool = True,
    ) -> dict[str, object]:
        values = tuple(row)
        library_root = Path(str(values[1])).resolve()
        destination = Path(str(values[2])).resolve()
        payload = json.loads(str(values[4]))
        if not isinstance(payload, dict):
            raise ValueError("import manifest payload must be an object")
        if payload.get("payload_version") == IMPORT_MANIFEST_STREAM_PAYLOAD_VERSION:
            _validate_payload_header(payload, destination=destination)
            if include_items:
                payload["items"] = self._load_stream_items(
                    str(values[0]), str(values[1]), destination, payload
                )
            if validate:
                _validate_payload(payload, root=library_root, destination=destination)
        elif validate:
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
    """Turn unresolved import intents into durable root index rescans.

    A queue insertion is an ownership hand-off, not proof that the rescan has
    run.  Real queue implementations therefore leave the manifest in
    ``recovery_pending`` with a bound task id until :meth:`acknowledge_task` is
    called by the worker after a durable success.  The small legacy adapter
    used by older embedders may return ``None`` from ``enqueue_or_merge``; that
    adapter is treated as synchronous for compatibility and is intentionally
    kept out of the production bootstrap path.
    """

    def __init__(self, store: ImportManifestStore, reconciliation_queue):
        self.store = store
        self.reconciliation_queue = reconciliation_queue
        self._ack_event = threading.Event()
        self._last_scheduled: tuple[str, ...] = ()
        # The SQLite transition outbox has one durable consumer: this recovery
        # service.  Older embedded queues expose only the advisory listener
        # API, so retain that registration as a compatibility fallback.
        register = getattr(
            reconciliation_queue,
            "set_durable_transition_consumer",
            None,
        )
        if callable(register):
            try:
                register(
                    IMPORT_MANIFEST_RECOVERY_CONSUMER_ID,
                    self.handle_task_transition,
                )
            except Exception:
                _log.exception("Could not register import recovery durable consumer")
        else:
            register = getattr(reconciliation_queue, "add_transition_listener", None)
            if not callable(register):
                return
            try:
                register(self.handle_task_transition)
            except Exception:
                _log.exception("Could not register import recovery queue listener")

    def _uses_durable_transition_outbox(self) -> bool:
        """Whether queue transition delivery is the authoritative ACK path."""
        enabled = getattr(
            self.reconciliation_queue,
            "durable_transition_outbox_enabled",
            False,
        )
        try:
            return bool(enabled() if callable(enabled) else enabled)
        except Exception:
            return False

    @staticmethod
    def _task_state(task: object) -> str:
        state = getattr(task, "state", "")
        value = getattr(state, "value", state)
        return str(value)

    def _task_matches_operation(
        self,
        task: object,
        operation_id: str,
        *,
        operation_ids: Iterable[object] | None = None,
    ) -> bool:
        """Fail closed when a queue task carries an explicit wrong scope.

        Older embedders supplied only ``task_id``/``operation_ids``; missing
        optional fields remain accepted for that compatibility adapter.  The
        production ``ReconciliationTask`` exposes all fields, so a task for a
        different library/path/kind can never terminalize this manifest.
        """
        candidates = (
            operation_ids
            if operation_ids is not None
            else getattr(task, "operation_ids", ())
        )
        try:
            if operation_id not in tuple(candidates or ()):
                return False
            task_root = getattr(task, "library_root", None)
            if task_root is not None and _canonical(str(task_root)).casefold() != str(self.store.library_root).casefold():
                return False
            task_path = getattr(task, "path", None)
            if task_path is not None and _canonical(str(task_path)).casefold() != str(self.store.library_root).casefold():
                return False
            task_kind = getattr(task, "kind", None)
            if task_kind is not None:
                kind_value = getattr(task_kind, "value", task_kind)
                if str(kind_value) != "asset_index_root_rescan":
                    return False
        except (OSError, RuntimeError, ValueError, TypeError):
            return False
        return True

    @staticmethod
    def _transition_state(transition: object) -> str:
        """Normalize a queue transition's current state for duck-typed callers."""
        current = getattr(transition, "current", None)
        if current is None:
            # An event with no current task is a capacity eviction.  The queue
            # supplies the previous task id/operation scope in that case.
            return "evicted"
        state = getattr(current, "state", current)
        value = getattr(state, "value", state)
        return str(value).lower()

    @staticmethod
    def _transition_task(transition: object) -> object | None:
        return getattr(transition, "current", None) or getattr(transition, "previous", None)

    def _transition_manifest_requires_delivery(
        self,
        operation_id: str,
        task_id: str,
    ) -> bool | None:
        """Classify whether one scoped manifest still needs this event.

        ``True`` means a manifest CAS must be durably confirmed.  ``False``
        means the event is provably unrelated, superseded, or already
        terminal.  ``None`` deliberately means that the consumer could not
        prove either condition, so the durable outbox must retry it.
        """
        try:
            try:
                record = self.store.get(operation_id, include_items=False)
            except TypeError:
                record = self.store.get(operation_id)
        except Exception:
            _log.exception(
                "Could not inspect import recovery %s for task %s",
                operation_id,
                task_id,
            )
            return None
        if record is None:
            return False
        if record.get("malformed"):
            _log.error(
                "Cannot prove import recovery transition delivery for malformed "
                "manifest %s (task=%s)",
                operation_id,
                task_id,
            )
            return None
        if str(record.get("state")) in _TERMINAL_STATES:
            return False
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            _log.error(
                "Cannot prove import recovery transition delivery for invalid "
                "manifest payload %s (task=%s)",
                operation_id,
                task_id,
            )
            return None
        if task_id in _recovery_retired_task_ids(payload):
            return False
        bound_task_id = payload.get("recovery_task_id")
        if bound_task_id is not None and str(bound_task_id) != task_id:
            return False
        return True

    def handle_task_transition(
        self,
        transition: object,
    ) -> ReconciliationTransitionDisposition:
        """Apply one committed queue transition to all attached manifests.

        A single root-rescan task may carry several operation ids.  Each id is
        independently scope-checked and CAS-updated; one malformed or stale
        binding therefore cannot terminalize its siblings.  Unlike the legacy
        advisory callback contract, this durable consumer explicitly returns
        ``RETRY`` when it cannot prove that every applicable manifest write
        committed.  The v44 outbox then retains the event instead of ACKing a
        callback that merely returned normally.
        """
        task = self._transition_task(transition)
        if task is None:
            return ReconciliationTransitionDisposition.STALE
        state = self._transition_state(transition)
        task_id = str(getattr(task, "task_id", ""))
        if not task_id:
            return ReconciliationTransitionDisposition.STALE
        if state not in {
            "pending",
            "running",
            "retryable",
            "succeeded",
            "terminal",
            "cancelled",
            "evicted",
        }:
            return ReconciliationTransitionDisposition.STALE
        # The transition-level list is an audit hint and may come from an old
        # or untrusted adapter.  The authoritative scope is carried by the
        # task snapshots themselves.  Only fall back to transition_ids when a
        # legacy adapter exposes no operation ids on either snapshot, and then
        # keep the fallback explicitly isolated below.
        try:
            transition_ids = tuple(getattr(transition, "operation_ids", ()) or ())
            operation_ids = tuple(getattr(task, "operation_ids", ()) or ())
        except TypeError:
            return ReconciliationTransitionDisposition.STALE
        previous = getattr(transition, "previous", None)
        try:
            previous_ids = (
                tuple(getattr(previous, "operation_ids", ()) or ())
                if previous is not None
                else ()
            )
            authoritative_ids: tuple[object, ...] = tuple(
                dict.fromkeys(operation_ids + previous_ids)
            )
        except TypeError:
            return ReconciliationTransitionDisposition.STALE
        if authoritative_ids:
            # A producer must not be able to enlarge the scope by injecting an
            # id only into the event envelope.  Ignore such ids and retain the
            # task snapshot's complete scope for the per-operation CAS below.
            if any(operation_id not in authoritative_ids for operation_id in transition_ids):
                _log.warning(
                    "Ignoring transition operation ids outside task scope for %s",
                    task_id,
                )
            ids = authoritative_ids
        else:
            # Compatibility with pre-transition adapters which placed the
            # operation scope only on the envelope.  This path is intentionally
            # unavailable once a production task snapshot exposes its scope.
            ids = tuple(dict.fromkeys(transition_ids))
        if not ids:
            return ReconciliationTransitionDisposition.STALE
        applied = False
        error_type = getattr(task, "last_error_type", None)
        error = getattr(task, "last_error", None)
        attempts = getattr(task, "attempts", None)
        for operation_id in ids:
            if not isinstance(operation_id, str) or not operation_id:
                continue
            # Scope is checked against the task before any allow-unbound bind.
            # This is the guard against an operation id copied onto an unrelated
            # library/path/kind task.
            if not self._task_matches_operation(
                task,
                operation_id,
                operation_ids=ids,
            ):
                continue
            if state == "pending":
                # Enqueue notifications happen before recovery has written its
                # binding.  They carry no evidence that work ran, so no
                # manifest mutation is required for this event.
                continue
            requires_delivery = self._transition_manifest_requires_delivery(
                operation_id,
                task_id,
            )
            if requires_delivery is None:
                return ReconciliationTransitionDisposition.RETRY
            if not requires_delivery:
                continue
            try:
                changed = self.store.record_recovery_task_transition(
                    operation_id,
                    task_id,
                    state,
                    task_attempts=attempts,
                    error_type=(str(error_type) if error_type is not None else None),
                    error=(str(error) if error is not None else None),
                    # Every non-pending queue state can be observed in the
                    # narrow enqueue→bind crash window.  The event's full
                    # task scope was validated above, so binding here is the
                    # only way a later terminal/retry outcome remains tied to
                    # the original import intent.
                    allow_unbound=state != "pending",
                )
            except Exception:
                _log.exception(
                    "Could not apply import recovery transition %s for task %s",
                    operation_id,
                    task_id,
                )
                return ReconciliationTransitionDisposition.RETRY
            if not changed:
                _log.warning(
                    "Import recovery transition did not durably apply for %s "
                    "(task=%s); retaining outbox event",
                    operation_id,
                    task_id,
                )
                return ReconciliationTransitionDisposition.RETRY
            applied = True
            if state == "succeeded":
                self._ack_event.set()
        return (
            ReconciliationTransitionDisposition.APPLIED
            if applied
            else ReconciliationTransitionDisposition.STALE
        )

    def _bind_if_unbound(self, operation_id: str, task_id: str) -> bool:
        """Recover the tiny enqueue→bind window using a CAS, if necessary."""
        try:
            record = self.store.get(operation_id, include_items=False)
        except TypeError:
            record = self.store.get(operation_id)
        if record is None or record.get("malformed"):
            return False
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            return False
        bound = payload.get("recovery_task_id")
        if bound is not None:
            return str(bound) == task_id
        return bool(self.store.bind_existing_recovery_task(operation_id, task_id))

    def _queue_tasks(self) -> tuple[object, ...] | None:
        """Read a durable queue snapshot for ACK/reuse checks.

        ``None`` means the queue could not be refreshed or inspected.  That
        distinction matters for an already-bound task: reusing a stale
        snapshot could cause ``allow_rebind=True`` to replace the original
        task with a duplicate.  Callers therefore keep the manifest pending
        when refresh is unavailable, while legacy queues without a refresh
        method continue to use their local snapshot.
        """
        refresh = getattr(self.reconciliation_queue, "refresh", None)
        if callable(refresh):
            try:
                # A queue instance may have been opened before another
                # process persisted the task.  Refresh before inspecting the
                # in-memory snapshot so recovery does not enqueue a duplicate
                # or miss a completed task that can ACK this manifest.
                refresh()
            except Exception:
                # Do not use a stale snapshot for task rebinding or ACK.  The
                # next recovery pass can retry the refresh without losing the
                # durable manifest intent.
                _log.warning(
                    "Could not refresh reconciliation queue for import recovery",
                    exc_info=True,
                )
                return None
        snapshot = getattr(self.reconciliation_queue, "snapshot", None)
        if not callable(snapshot):
            return ()
        try:
            value = snapshot()
            tasks = getattr(value, "tasks", value)
            if isinstance(tasks, (list, tuple)):
                return tuple(tasks)
        except Exception:
            _log.exception("Could not inspect reconciliation queue for import recovery")
            return None

    def acknowledge_task(self, task: object) -> tuple[str, ...]:
        """ACK manifests attached to one successfully completed queue task.

        The worker calls this only after the queue's own success CAS commits.
        A malformed/mismatched binding is left pending and reported via the
        return value, never silently terminalized.
        """
        if self._task_state(task) != "succeeded":
            return ()
        task_id = str(getattr(task, "task_id", ""))
        operation_ids = getattr(task, "operation_ids", ())
        acknowledged: list[str] = []
        for operation_id in tuple(operation_ids or ()):
            if not isinstance(operation_id, str) or not operation_id:
                continue
            if not self._task_matches_operation(task, operation_id):
                continue
            try:
                acknowledged_now = self.store.acknowledge_recovery(operation_id, task_id)
                if not acknowledged_now and self._bind_if_unbound(operation_id, task_id):
                    acknowledged_now = self.store.acknowledge_recovery(
                        operation_id, task_id
                    )
                if acknowledged_now:
                    acknowledged.append(operation_id)
                    self._ack_event.set()
            except Exception:
                _log.exception(
                    "Could not acknowledge import recovery %s for task %s",
                    operation_id,
                    task_id,
                )
        return tuple(acknowledged)

    def mark_task_running(self, task: object) -> tuple[str, ...]:
        """Best-effort visibility update when the queue worker claims a task."""
        task_id = str(getattr(task, "task_id", ""))
        operation_ids = getattr(task, "operation_ids", ())
        marked: list[str] = []
        for operation_id in tuple(operation_ids or ()):
            if not isinstance(operation_id, str) or not operation_id:
                continue
            if not self._task_matches_operation(task, operation_id):
                continue
            try:
                marked_now = self.store.mark_recovery_running(operation_id, task_id)
                if not marked_now and self._bind_if_unbound(operation_id, task_id):
                    marked_now = self.store.mark_recovery_running(operation_id, task_id)
                if marked_now:
                    marked.append(operation_id)
            except Exception:
                _log.exception(
                    "Could not mark import recovery %s running for task %s",
                    operation_id,
                    task_id,
                )
        return tuple(marked)

    def _acknowledge_completed_tasks(self) -> tuple[str, ...]:
        acknowledged: list[str] = []
        tasks = self._queue_tasks()
        if tasks is None:
            return ()
        for task in tasks:
            acknowledged.extend(self.acknowledge_task(task))
        return tuple(acknowledged)

    def _reconcile_terminal_task_for_retry(self, operation_id: str) -> None:
        """Record a lost terminal callback before an operator retries it.

        An operator can reasonably open a recovery view in the narrow period
        after the queue committed a terminal/cancelled result but before its
        listener wrote the manifest phase.  Read the durable queue snapshot
        for this one bound task so ``retry_dead_letter`` remains usable in
        that window without scheduling unrelated recovery work.
        """
        try:
            record = self.store.get(operation_id, include_items=False)
        except TypeError:
            record = self.store.get(operation_id)
        if record is None or record.get("malformed"):
            return
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            return
        bound_task_id = payload.get("recovery_task_id")
        if not isinstance(bound_task_id, str) or not bound_task_id:
            return
        tasks = self._queue_tasks()
        if tasks is None:
            return
        matching = next(
            (
                task
                for task in tasks
                if str(getattr(task, "task_id", "")) == bound_task_id
            ),
            None,
        )
        if matching is None:
            return
        state = self._task_state(matching)
        if state not in {"terminal", "cancelled"}:
            return
        if not self._task_matches_operation(matching, operation_id):
            return
        try:
            self.store.record_recovery_task_transition(
                operation_id,
                bound_task_id,
                state,
                task_attempts=getattr(matching, "attempts", None),
                error_type=getattr(matching, "last_error_type", None),
                error=getattr(matching, "last_error", None),
            )
        except Exception:
            _log.exception(
                "Could not reconcile terminal import recovery task %s before retry",
                bound_task_id,
            )

    def retry_dead_letter(self, operation_id: str) -> bool:
        """Request one explicit retry for a terminal/cancelled recovery task.

        The method returns after the retry intent is durably accepted, not
        after reconciliation succeeds.  A queue outage while scheduling leaves
        the manifest visibly ``pending`` with its new error detail; the next
        normal recovery pass may then retry it.  Repeated calls after the first
        accepted CAS are deliberately no-ops, so operators cannot enqueue a
        second replacement task by double-clicking a retry action.
        """
        if not self.store.request_recovery_retry(operation_id):
            self._reconcile_terminal_task_for_retry(operation_id)
            if not self.store.request_recovery_retry(operation_id):
                return False
        self.recover()
        return True

    def recover(self) -> tuple[str, ...]:
        # A listener can fail after the queue commit while this process stays
        # alive.  Give the queue a bounded retry opportunity before scanning
        # manifests; this closes the gap where no new queue mutation occurs
        # and avoids waiting for a full process restart.
        retry_backlog = getattr(self.reconciliation_queue, "retry_transition_backlog", None)
        if callable(retry_backlog):
            try:
                retry_backlog()
            except Exception:
                _log.warning(
                    "Could not retry reconciliation transition backlog",
                    exc_info=True,
                )
        durable_outbox = self._uses_durable_transition_outbox()
        # Pre-v44 queues have no durable transition record, so their startup
        # snapshot remains the compatibility compensator.  With the v44
        # outbox, only its listener may advance a manifest: a direct snapshot
        # ACK would bypass the event's explicit delivery disposition.
        if not durable_outbox:
            self._acknowledge_completed_tasks()
        recovered: list[str] = []
        for record in self.store.list_recovery():
            operation_id = str(record["operation_id"])

            # If a prior pass already bound a live task, do not enqueue a
            # duplicate.  A missing/terminal task is safe to merge again by
            # operation_id below.
            payload = record.get("payload")
            recovery_phase = (
                str(payload.get("recovery_phase"))
                if isinstance(payload, Mapping) and payload.get("recovery_phase")
                else None
            )
            # A terminal/cancelled queue outcome is an explicit dead-letter
            # decision.  Do not silently turn it into a fresh repair on every
            # restart; an operator or a future explicit retry API must clear
            # this phase first.
            if recovery_phase in {"dead_letter", "cancelled"}:
                continue
            bound_task_id = (
                str(payload.get("recovery_task_id"))
                if isinstance(payload, Mapping) and payload.get("recovery_task_id")
                else None
            )
            if bound_task_id:
                queue_tasks = self._queue_tasks()
                if queue_tasks is None:
                    # A bound task cannot safely be replaced while the
                    # durable queue snapshot is unavailable.  Leave the
                    # manifest pending for a later pass.
                    continue
                matching = next(
                    (
                        task
                        for task in queue_tasks
                        if str(getattr(task, "task_id", "")) == bound_task_id
                    ),
                    None,
                )
                if matching is not None and self._task_state(matching) in {
                    "pending",
                    "running",
                    "retryable",
                }:
                    if self._task_state(matching) == "running":
                        self.store.mark_recovery_running(operation_id, bound_task_id)
                    continue
                if matching is not None and self._task_state(matching) in {
                    "terminal",
                    "cancelled",
                }:
                    # Reconcile a callback that was lost after the queue
                    # commit.  This records a visible dead-letter/cancelled
                    # phase and prevents an automatic restart loop.
                    if self._task_matches_operation(matching, operation_id):
                        self.store.record_recovery_task_transition(
                            operation_id,
                            bound_task_id,
                            self._task_state(matching),
                            task_attempts=getattr(matching, "attempts", None),
                            error_type=getattr(matching, "last_error_type", None),
                            error=getattr(matching, "last_error", None),
                        )
                    continue
                if matching is not None and self._task_state(matching) == "succeeded":
                    if not durable_outbox:
                        self.acknowledge_task(matching)
                    continue
                # The durable row disappeared (for example capacity
                # eviction or an external queue cleanup).  Clear the stale
                # binding before attempting a replacement so the next CAS is
                # auditable and cannot retain an orphan task id.
                if matching is None:
                    if self.store.record_recovery_task_transition(
                        operation_id,
                        bound_task_id,
                        "evicted",
                        task_attempts=None,
                    ):
                        try:
                            refreshed = self.store.get(operation_id, include_items=False)
                        except TypeError:
                            refreshed = self.store.get(operation_id)
                        if refreshed is not None and not refreshed.get("malformed"):
                            record = refreshed
                            payload = record.get("payload")
                            bound_task_id = None

            # A v1/v2 row written before task-id binding may still have a
            # durable succeeded task from an older synchronous recovery pass.
            # Bind/ACK it rather than enqueueing another root rescan.  This is
            # intentionally scoped by operation id and full task identity.
            if not bound_task_id:
                queue_tasks = self._queue_tasks()
                if queue_tasks is None:
                    continue
                matching = next(
                    (
                        task
                        for task in queue_tasks
                        if self._task_matches_operation(task, operation_id)
                        and self._task_state(task) == "succeeded"
                    ),
                    None,
                )
                if matching is not None:
                    task_id = str(getattr(matching, "task_id", ""))
                    if (
                        not durable_outbox
                        and task_id
                        and self._bind_if_unbound(operation_id, task_id)
                    ):
                        self.acknowledge_task(matching)
                    continue

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
                task = self.reconciliation_queue.enqueue_or_merge(
                    path=self.store.library_root,
                    reason="import_manifest_recovery",
                    operation_id=operation_id,
                )
                task_id = str(getattr(task, "task_id", "")) if task is not None else ""
                if task_id:
                    # Do not mark completed here: only the worker's durable
                    # success ACK may make the manifest terminal.
                    if not self.store.bind_recovery_task(
                        claimed, task_id, allow_rebind=True
                    ):
                        self.store.record_recovery_failure(
                            claimed,
                            RuntimeError("recovery task binding CAS failed"),
                        )
                        continue
                    recovered.append(operation_id)
                else:
                    # Compatibility path for pre-queue adapters whose enqueue
                    # call is documented as synchronous.  Production queues
                    # always return a ReconciliationTask and therefore cannot
                    # enter this branch.
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
        self._last_scheduled = tuple(recovered)
        return self._last_scheduled

    @property
    def last_scheduled(self) -> tuple[str, ...]:
        """Operation ids scheduled by the most recent recovery pass."""
        return self._last_scheduled

    def wait_for_ack(
        self,
        operation_ids: tuple[str, ...] | list[str] | None = None,
        *,
        timeout: float = 2.0,
    ) -> bool:
        """Boundedly wait for startup recovery ACKs.

        This is only a startup convenience for tiny, already-queued rescans;
        timeout leaves the manifest pending and never fabricates completion.
        Runtime workers continue asynchronously after the deadline.
        """
        if timeout < 0:
            raise ValueError("timeout must be non-negative")
        ids = tuple(operation_ids or self._last_scheduled)
        if not ids:
            return True
        deadline = time.monotonic() + float(timeout)
        durable_outbox = self._uses_durable_transition_outbox()
        while True:
            if durable_outbox:
                retry_backlog = getattr(
                    self.reconciliation_queue,
                    "retry_transition_backlog",
                    None,
                )
                if callable(retry_backlog):
                    try:
                        retry_backlog()
                    except Exception:
                        _log.warning(
                            "Could not retry reconciliation transition backlog while waiting for ACK",
                            exc_info=True,
                        )
            else:
                self._acknowledge_completed_tasks()
            if all(
                (record := self.store.get(operation_id)) is not None
                and str(record.get("state")) == "completed"
                for operation_id in ids
            ):
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self._ack_event.wait(min(remaining, 0.05))
            self._ack_event.clear()
