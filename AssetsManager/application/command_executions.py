"""Plan-hash dedup store for batch operations (T8 minimal).

A batch destructive operation records a plan fingerprint — SHA-256 of the
canonical command id + sorted targets + params — in the library's
``command_executions`` table so an accidental double-submit of the same
batch executes at most once.  Design mirrors the Serpent idempotency
store, simplified:

- the plan hash IS the content fingerprint (the same hash with different
  targets is a different plan, because the targets are hashed too);
- only successful executions are remembered; a failed run clears its row
  so the operation can simply be retried;
- the store is best-effort: storage failures never block the operation
  (fail-open, same contract as ``ActivityRecorder``) — they only disable
  dedup for that run;
- rows are capped (FIFO, 4096) so the table cannot grow without bound.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from sqlite3 import Connection
from typing import Callable, Iterable

from AssetsManager.core.database import db_write_lock

_log = logging.getLogger(__name__)

#: FIFO cap for remembered executions (mirrors the Serpent idempotency
#: store default so the table stays small even under heavy batch use).
MAX_ROWS = 4096

#: An ``executing`` row younger than this is a live run (dedup); an older
#: one is a crash orphan and is taken over by the next submit.
_EXECUTING_TTL_SECONDS = 600


def plan_hash(command_id: str, targets: Iterable[str], **params) -> str:
    """Content fingerprint of a batch plan (order-insensitive targets)."""
    payload = {
        "command_id": command_id,
        "targets": sorted(str(target) for target in targets),
        "params": params,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CommandExecutionStore:
    """Dedup + journal rows for batch command executions (T8 minimal)."""

    def __init__(self, connection_provider: Callable[[], Connection]):
        self._connection_provider = connection_provider

    def begin(self, plan_hash_value: str, command_id: str, targets_json: str) -> bool:
        """Open an ``executing`` row; return False when deduped.

        Returns True when the plan may execute (fresh plan, or the previous
        attempt failed), False when the same plan hash already executed
        successfully.  Storage failures fail open (True) with a log entry —
        the dedup is a safety net, not a correctness gate, and a broken
        store must never block deleting files.
        """
        try:
            conn = self._connection_provider()
            with db_write_lock(conn):
                existing = conn.execute(
                    "SELECT status, executed_at FROM command_executions "
                    "WHERE plan_hash = ?",
                    (plan_hash_value,),
                ).fetchone()
                if existing is not None:
                    status, executed_at = existing[0], existing[1]
                    if status == "succeeded":
                        # Same plan already executed — dedup.
                        return False
                    if status == "executing" and (
                        time.time() - executed_at
                    ) < _EXECUTING_TTL_SECONDS:
                        # A run is in flight (double-submit race).
                        return False
                    # 'failed' rows and stale 'executing' rows (crash orphans
                    # past the TTL) fall through and are taken over.
                conn.execute(
                    "INSERT INTO command_executions (plan_hash, command_id, "
                    "targets_json, status, executed_at) "
                    "VALUES (?, ?, ?, 'executing', ?) "
                    "ON CONFLICT(plan_hash) DO UPDATE SET status = 'executing'",
                    (plan_hash_value, command_id, targets_json, time.time()),
                )
                self._trim(conn)
                conn.commit()
            return True
        except Exception:
            _log.exception(
                "command execution dedup store unavailable; proceeding without dedup")
            return True

    def mark_succeeded(self, plan_hash_value: str, result_summary: str = "") -> None:
        """Mark the plan as succeeded (the dedup row is kept)."""
        try:
            conn = self._connection_provider()
            with db_write_lock(conn):
                conn.execute(
                    "UPDATE command_executions SET status = 'succeeded', "
                    "result_summary = ? WHERE plan_hash = ?",
                    (result_summary, plan_hash_value),
                )
                conn.commit()
        except Exception:
            _log.exception("command execution store update failed")

    def clear(self, plan_hash_value: str) -> None:
        """Drop the plan row so a failed run can simply be retried."""
        try:
            conn = self._connection_provider()
            with db_write_lock(conn):
                conn.execute(
                    "DELETE FROM command_executions WHERE plan_hash = ?",
                    (plan_hash_value,),
                )
                conn.commit()
        except Exception:
            _log.exception("command execution store clear failed")

    @staticmethod
    def _trim(conn: Connection) -> None:
        conn.execute(
            "DELETE FROM command_executions WHERE plan_hash NOT IN ("
            "SELECT plan_hash FROM command_executions "
            "ORDER BY executed_at DESC LIMIT ?)",
            (MAX_ROWS,),
        )
