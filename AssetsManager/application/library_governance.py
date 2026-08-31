"""Library scale governance: health observation and retention enforcement.

H2 "scale observation and governance" batch. Two related concerns:

- :class:`LibraryHealthSnapshot` / :func:`collect_library_health` — the
  observation surface behind the settings maintenance tab's health card
  (H2-a1). Pure stdlib filesystem walking plus read-only SQL counts, so it
  runs on a worker thread without touching Qt. Reads go through the shared
  connection's write lock (same discipline as ``ActivityRecorder.recent``):
  the library shares one ``check_same_thread=False`` connection across
  surfaces, so an unguarded read could race an in-flight write.

Retention enforcement (thumbnail cache capacity cap, ``activity_log``
pruning) lives in this module too — see :func:`run_startup_governance` and
:func:`schedule_startup_governance`.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from AssetsManager.core.constants import (
    THUMBNAIL_CACHE_DEFAULT_MAX_BYTES,
    THUMBNAIL_CACHE_WARNING_BYTES,
    WAL_FILE_WARNING_BYTES,
)
from AssetsManager.core.settings import AppSettings

_log = logging.getLogger(__name__)

_DAY_SECONDS = 86400.0


@dataclass(frozen=True)
class LibraryHealthSnapshot:
    """One point-in-time observation of a library's scale-relevant metrics.

    ``None`` means "could not be observed" (missing file, unreadable table);
    the card renders those as placeholders instead of inventing a zero.
    """

    db_bytes: int | None = None
    wal_bytes: int | None = None
    thumbnail_bytes: int = 0
    thumbnail_files: int = 0
    derivatives_bytes: int = 0
    derivatives_files: int = 0
    activity_rows: int | None = None
    activity_oldest_age_days: float | None = None
    favorites_count: int | None = None
    asset_rows: int | None = None

    @property
    def warnings(self) -> tuple[str, ...]:
        """Tokens for metrics at/above their H2 observation threshold."""
        warnings: list[str] = []
        if self.wal_bytes is not None and self.wal_bytes >= WAL_FILE_WARNING_BYTES:
            warnings.append("wal")
        if self.thumbnail_bytes >= THUMBNAIL_CACHE_WARNING_BYTES:
            warnings.append("thumbnail_cache")
        return tuple(warnings)


def _dir_size(path: Path) -> tuple[int, int]:
    """Return ``(total_bytes, file_count)`` under *path*; missing → ``(0, 0)``."""
    total = 0
    files = 0
    try:
        if not path.is_dir():
            return (0, 0)
        for root, _dirs, names in os.walk(path):
            for name in names:
                try:
                    total += os.stat(os.path.join(root, name)).st_size
                    files += 1
                except OSError:
                    continue
    except OSError:
        # A partially unreadable tree still yields the counts gathered so far.
        return (total, files)
    return (total, files)


def _file_size(path: Path) -> int | None:
    """Return the file size, or ``None`` when the file is missing/unreadable."""
    try:
        return path.stat().st_size if path.is_file() else None
    except OSError:
        return None


def collect_library_health(
    conn,
    *,
    db_path: Path,
    thumb_dir: Path,
    derivatives_dir: Path,
) -> LibraryHealthSnapshot:
    """Collect the H2-a1 health card metrics for one open library.

    Heavy IO (recursive directory walks) plus three read-only ``SELECT``
    statements — callers run this on a worker thread. Every metric degrades
    independently: a failure in one table or directory never hides the others.
    """
    from AssetsManager.core.database import db_write_lock

    activity_rows: int | None = None
    oldest_age_days: float | None = None
    favorites_count: int | None = None
    asset_rows: int | None = None
    try:
        with db_write_lock(conn):
            row = conn.execute(
                "SELECT COUNT(*), MIN(timestamp) FROM activity_log"
            ).fetchone()
            if row is not None:
                activity_rows = int(row[0])
                if row[1] is not None:
                    age = (time.time() - float(row[1])) / _DAY_SECONDS
                    oldest_age_days = max(0.0, age)
            favorites_count = _count_rows(conn, "SELECT COUNT(*) FROM library_favorites")
            asset_rows = _count_rows(conn, "SELECT COUNT(*) FROM assets")
    except Exception:
        # Swallow-on-error keeps the card renderable; individual metrics that
        # never got assigned stay None and render as placeholders.
        _log.exception("Library health DB metrics collection failed")

    thumbnail_bytes, thumbnail_files = _dir_size(Path(thumb_dir))
    derivatives_bytes, derivatives_files = _dir_size(Path(derivatives_dir))
    return LibraryHealthSnapshot(
        db_bytes=_file_size(Path(db_path)),
        wal_bytes=_file_size(Path(str(db_path) + "-wal")),
        thumbnail_bytes=thumbnail_bytes,
        thumbnail_files=thumbnail_files,
        derivatives_bytes=derivatives_bytes,
        derivatives_files=derivatives_files,
        activity_rows=activity_rows,
        activity_oldest_age_days=oldest_age_days,
        favorites_count=favorites_count,
        asset_rows=asset_rows,
    )


def _count_rows(conn, sql: str) -> int | None:
    """Run one read-only count; ``None`` when the table is unavailable."""
    try:
        row = conn.execute(sql).fetchone()
        return int(row[0]) if row is not None else None
    except Exception:
        return None


# ── Startup retention governance (H2-a2) ─────────────────────────

_governed_tokens: set[str] = set()
_governed_tokens_lock = threading.Lock()


def run_startup_governance(
    *,
    thumbnail_service=None,
    library_root,
    thumb_dir,
    max_bytes: int,
) -> None:
    """Run one silent thumbnail-cache capacity pass against an open library.

    Low-priority chore that keeps a large library bounded without user
    attention: evict thumbnail artifacts down to the configured capacity
    cap, preserving the most recently accessed (H2-a2). Every failure is
    logged and swallowed — governance must never turn a library open into
    an error surface. ``max_bytes <= 0`` means the user disabled the cap
    ("unlimited") and the pass becomes a no-op.
    """
    if thumbnail_service is None or max_bytes <= 0:
        return
    try:
        evicted, reclaimed = thumbnail_service.enforce_cache_capacity(
            library_root, thumb_dir, max_bytes=max_bytes,
        )
        if evicted:
            _log.info(
                "Startup thumbnail cache eviction removed %d artifacts "
                "(%d bytes reclaimed)",
                evicted, reclaimed,
            )
    except Exception:
        _log.exception("Thumbnail cache capacity enforcement failed")


def schedule_startup_governance(scoped) -> bool:
    """Schedule the silent retention pass once per library session.

    Called from the window's scoped-services binding (the same point that
    schedules the automatic integrity check). Spawns one daemon thread so a
    library open never blocks on governance, and runs at most once per
    session. Returns ``False`` when the session was already governed or
    exposes no governable service (e.g. UI-level fakes).
    """
    session = getattr(scoped, "session", None)
    if session is None or getattr(session, "is_closed", True):
        return False
    token = str(getattr(session, "event_token", "") or id(session))
    with _governed_tokens_lock:
        if token in _governed_tokens:
            return False
        _governed_tokens.add(token)
    thumbnail_service = getattr(scoped, "thumbnail_service", None)
    library_root = getattr(session, "root", None)
    thumb_dir = getattr(session, "thumb_dir", None)
    if thumbnail_service is None or library_root is None or thumb_dir is None:
        return False

    def _run() -> None:
        try:
            max_bytes = AppSettings.instance().get_thumbnail_cache_max_bytes()
        except Exception:
            _log.exception("Thumbnail cache cap lookup failed; using default")
            max_bytes = THUMBNAIL_CACHE_DEFAULT_MAX_BYTES
        run_startup_governance(
            thumbnail_service=thumbnail_service,
            library_root=library_root,
            thumb_dir=thumb_dir,
            max_bytes=max_bytes,
        )

    worker = threading.Thread(
        target=_run, name="AssetsManager-StartupGovernance", daemon=True,
    )
    worker.start()
    return True
