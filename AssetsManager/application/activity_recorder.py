"""Thin application-layer writer for the per-library ``activity_log`` table.

The LAN layer keeps its own richer ``ActivityLog`` (``lan/routes/_helpers.py``)
that backs the web admin activity feed; desktop file/tag/import operations only
need to append rows into the same table so those operations become traceable
there too. Each per-library database owns its ``activity_log`` table, so the
recorder writes through the bound session's connection provider.

Contract (mirrors the LAN writer's swallow-on-error semantics): a recording
failure is logged and swallowed — an activity bookkeeping problem must never
fail or delay the operation it describes.
"""
from __future__ import annotations

import logging
from pathlib import Path
from sqlite3 import Connection
from time import time
from typing import Callable, Iterable

from AssetsManager.core.constants import ACTIVITY_RETENTION_DAYS
from AssetsManager.core.database import db_write_lock

_log = logging.getLogger(__name__)

#: Username recorded for desktop-originated operations. The desktop is a
#: single local surface; LAN rows keep their real principal names.
DESKTOP_USER = "desktop"

#: IP value for operations that did not arrive over the network.
LOCAL_IP = "local"

# Bounded details text: list at most this many target paths and never exceed
# this many characters, so a 500-file batch delete cannot produce a
# megabyte-wide activity row.
_MAX_LISTED_TARGETS = 5
_MAX_DETAIL_CHARS = 512


def summarize_targets(targets: Iterable[Path | str]) -> str:
    """Render target paths as one bounded details string.

    A single target renders as its path; a batch renders as the target count
    plus the first paths (truncated) — one activity row per batch operation.
    """
    paths = [str(target) for target in targets]
    if not paths:
        return ""
    if len(paths) == 1:
        text = paths[0]
    else:
        listed = ", ".join(paths[:_MAX_LISTED_TARGETS])
        if len(paths) > _MAX_LISTED_TARGETS:
            listed += ", …"
        text = f"{len(paths)} targets: {listed}"
    if len(text) > _MAX_DETAIL_CHARS:
        text = text[:_MAX_DETAIL_CHARS - 1] + "…"
    return text


class ActivityRecorder:
    """Append rows into the library's ``activity_log`` via its session."""

    def __init__(self, connection_provider: Callable[[], Connection]):
        self._connection_provider = connection_provider

    def recent(
        self,
        *,
        cutoff: float | None = None,
        limit: int = 200,
    ) -> list[tuple] | None:
        """Return the newest ``activity_log`` rows, newest first.

        Read side of the desktop activity panel (H1-b): same lock
        discipline as :meth:`record` — the library shares one
        ``check_same_thread=False`` connection across surfaces, so an
        unguarded read could race an in-flight write. ``cutoff`` is a
        ``timestamp >`` floor (``None`` = all rows). Same
        swallow-on-error contract as the write side: a viewer never
        escalates a read failure, ``None`` signals one.
        """
        try:
            conn = self._connection_provider()
            sql = "SELECT timestamp, action, username, details FROM activity_log "
            parameters: list = []
            if cutoff is not None:
                sql += "WHERE timestamp > ? "
                parameters.append(cutoff)
            sql += "ORDER BY timestamp DESC, id DESC LIMIT ?"
            parameters.append(limit)
            with db_write_lock(conn):
                return conn.execute(sql, tuple(parameters)).fetchall()
        except Exception:
            _log.exception("Activity log read failed")
            return None

    def record(
        self,
        action: str,
        details: str = "",
        *,
        username: str = DESKTOP_USER,
        ip: str = LOCAL_IP,
    ) -> None:
        """Write one activity row; never raises.

        Mirrors the LAN ``ActivityLog.add`` insert shape
        (username/action/details/ip/timestamp) against the same table, so the
        LAN ``recent()`` reader serves desktop rows unchanged.
        """
        try:
            conn = self._connection_provider()
            if conn is None:
                return
            with db_write_lock(conn):
                conn.execute(
                    "INSERT INTO activity_log "
                    "(username, action, details, ip, timestamp) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (username or "guest", action, details, ip or "unknown", time()),
                )
                conn.commit()
        except Exception:
            # Activity recording must never affect the operation itself.
            _log.warning(
                "Activity recording failed for action=%s", action, exc_info=True
            )

    def prune(self, retention_days: int = ACTIVITY_RETENTION_DAYS) -> int:
        """Delete activity rows older than the retention window.

        H2-a3 retention enforcement entry point: the per-library
        ``activity_log`` previously grew without bound. One
        ``DELETE ... WHERE timestamp < now - days * 86400`` statement, run
        under the shared write lock; ``retention_days`` is clamped to >= 0
        and defaults to :data:`ACTIVITY_RETENTION_DAYS`. Returns the deleted
        row count. Same swallow-on-error contract as the write side —
        retention must never break a library open (the startup governance
        pass calls this from a daemon thread).
        """
        try:
            conn = self._connection_provider()
            if conn is None:
                return 0
            cutoff = time() - max(0, int(retention_days)) * 86400
            with db_write_lock(conn):
                cursor = conn.execute(
                    "DELETE FROM activity_log WHERE timestamp < ?", (cutoff,)
                )
                deleted = max(cursor.rowcount, 0)
                conn.commit()
                return deleted
        except Exception:
            # Retention enforcement must never affect the operation itself.
            _log.warning("Activity log prune failed", exc_info=True)
            return 0
