"""AssetManager database — unified SQLite persistence layer with lifecycle manager.

Provides:
- Per-library SQLite connections with WAL mode
- Schema initialization (file_tags, file_meta, thumbnail_cache)
- Thread-safe connection management
"""
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
import functools
import logging
import os
import shutil
import sqlite3
import stat
import tempfile
import threading
import time
import traceback
from pathlib import Path
from types import TracebackType
from typing import Any, Callable, Self

from AssetsManager.core.performance import PerformanceRecorder
from AssetsManager.core.thumbnail_key import (
    normalize_webp_render_profile,
    profiled_thumbnail_cache_key_v3,
    thumbnail_cache_key,
)
from AssetsManager.core.path_resolver import (
    runtime_root, SHARED_DIR as _PATH_SHARED_DIR, library_data_dir,
    library_data_name, library_data_identity_path, legacy_library_data_dir,
    thumb_dir, db_path, RootIdentity, root_identity, remap_path_subtree,
    sql_like_descendant_pattern,
)
from AssetsManager.core.db_migrations import (
    migrate as migrate_db,
    preflight_recorded_version,
)

RUNTIME_ROOT = runtime_root()
# Compatibility re-export: historical consumers imported the shared-data path
# from core.database.  The canonical definition lives in path_resolver so the
# settings/database module cycle stays broken.
SHARED_DIR = _PATH_SHARED_DIR
_ORPHANED_DIR_NAME = "_orphaned"
_LEGACY_MIGRATION_RESERVED_NAMES = frozenset({"shared", "_orphaned"})

_log = logging.getLogger(__name__)

# ── SQL slow-query instrumentation ──────────────────────────────────
# SQLite exposes no statement timing of its own and repositories reach the
# database through ``sqlite3.Connection.execute`` / ``executemany`` on the raw
# connection, so slow-query telemetry is layered on the connection object
# rather than on a Database wrapper class.  Wrapping a connection in
# :class:`SlowQueryConnection` (see :func:`slow_query_wrapper`) intercepts
# exactly those two statement entry points with zero changes to repository
# call sites.

# Default slow-query threshold in milliseconds.  The SLOW_QUERY_THRESHOLD_MS
# environment variable is honored at call time (see :func:`slow_query_threshold_ms`).
SLOW_QUERY_THRESHOLD_MS = 100.0

# Directory segments that identify a legitimate application-layer caller for
# slow-query attribution.
_SLOW_QUERY_CALLER_MARKERS = ("/repositories/", "/application/")

_OWN_FILE = os.path.normcase(os.path.abspath(os.fspath(__file__)))

SQLITE_BUSY_TIMEOUT_MS = 30_000
SQLITE_BUSY_RETRY_ATTEMPTS = 3
SQLITE_BUSY_RETRY_BASE_DELAY = 0.01


def is_sqlite_busy_error(error: BaseException) -> bool:
    """Return whether an SQLite error is retryable lock contention."""
    if not isinstance(error, sqlite3.OperationalError):
        return False
    message = str(error).lower()
    return "database is locked" in message or "database is busy" in message


def sqlite_busy_retry_delay(attempt: int) -> float:
    """Return bounded exponential backoff for one retry attempt."""
    return min(0.25, SQLITE_BUSY_RETRY_BASE_DELAY * (2 ** max(0, attempt)))


def slow_query_threshold_ms(override: float | None = None) -> float:
    """Resolve the slow-query threshold in milliseconds.

    Precedence: an explicit ``override`` argument, then the
    ``SLOW_QUERY_THRESHOLD_MS`` environment variable, then the module default
    :data:`SLOW_QUERY_THRESHOLD_MS`.  A malformed environment value falls back
    to the default instead of surfacing on a hot database path.
    """
    if override is not None:
        return float(override)
    raw = os.environ.get("SLOW_QUERY_THRESHOLD_MS")
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            _log.warning(
                "Invalid SLOW_QUERY_THRESHOLD_MS=%r; falling back to %.1fms",
                raw,
                SLOW_QUERY_THRESHOLD_MS,
            )
    return SLOW_QUERY_THRESHOLD_MS


def _slow_query_caller() -> tuple[str, int] | None:
    """Attribute a slow statement to the nearest application-layer caller.

    Walks the current stack innermost-first, skipping frames from this module,
    and prefers the first frame under a ``repositories/`` or ``application/``
    directory; falls back to the nearest frame that is not this module (e.g. a
    service issuing a raw statement).  Returns ``(basename, lineno)`` ready for
    a ``caller: file.py:lineno`` label.
    """
    try:
        frames = traceback.extract_stack(limit=5)
    except Exception:
        return None
    immediate: tuple[str, int] | None = None
    for frame in reversed(frames):  # innermost frame first
        raw_filename = frame.filename or ""
        filename = os.path.normcase(os.path.abspath(raw_filename))
        if filename == _OWN_FILE:
            continue
        label = (
            raw_filename.replace("\\", "/").rsplit("/", 1)[-1] or "?",
            frame.lineno or 0,
        )
        if immediate is None:
            immediate = label
        if any(
            marker in filename.replace("\\", "/")
            for marker in _SLOW_QUERY_CALLER_MARKERS
        ):
            return label
    return immediate


def _format_query_parameters(parameters: object) -> str:
    """Render bound parameters for a slow-query log line (truncated)."""
    if parameters is None or parameters is ...:
        return ""
    try:
        text = repr(parameters)
    except Exception:
        text = "<unprintable>"
    if len(text) > 200:
        text = f"{text[:197]}..."
    return f" | params: {text}"


def _report_slow_query(sql: str, parameters: object, elapsed_ms: float) -> None:
    """Emit one slow-query WARNING in the canonical ``[SLOW QUERY]`` format."""
    caller = _slow_query_caller()
    caller_label = f"{caller[0]}:{caller[1]}" if caller else "unknown"
    _log.warning(
        "[SLOW QUERY] %.1fms: %s%s | caller: %s",
        elapsed_ms,
        " ".join(str(sql).split()),
        _format_query_parameters(parameters),
        caller_label,
    )


def _timed_call(
    run: Callable[[], Any],
    sql: str,
    parameters: object,
    threshold_ms: float | None,
) -> Any:
    """Run one statement and warn when its wall time exceeds the threshold."""
    started = time.perf_counter()
    try:
        return run()
    finally:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if elapsed_ms >= slow_query_threshold_ms(threshold_ms):
            _report_slow_query(sql, parameters, elapsed_ms)


def execute(conn: Any, sql: str, parameters: object = ...) -> Any:
    """Execute ``sql`` on ``conn`` with slow-query instrumentation.

    Equivalent to ``conn.execute(sql, parameters)`` plus timing.  This is the
    statement-level interceptor mirroring a ``Database.execute`` API; code
    that already calls ``conn.execute`` directly can instead wrap the
    connection with :func:`slow_query_wrapper`.
    """

    def run() -> Any:
        if parameters is ...:
            return conn.execute(sql)
        return conn.execute(sql, parameters)

    return _timed_call(run, sql, parameters, None)


def executemany(conn: Any, sql: str, seq_of_parameters: object) -> Any:
    """Execute ``executemany`` on ``conn`` with slow-query instrumentation."""

    def run() -> Any:
        return conn.executemany(sql, seq_of_parameters)

    return _timed_call(run, sql, seq_of_parameters, None)


class SlowQueryConnection:
    """Connection middleware that times statements against a slow threshold.

    Wrapping an object exposing ``execute`` / ``executemany`` (normally a
    :class:`sqlite3.Connection`) in this proxy times each statement and
    reports statements that exceed the threshold through the ``database``
    logger at WARNING level (see :func:`slow_query_threshold_ms`).  All other
    attributes delegate to the wrapped connection, so a wrapped connection is
    usable anywhere the raw one was.

    Note: this proxy deliberately is not a ``sqlite3.Connection`` subclass, so
    code that dispatches on ``isinstance(conn, sqlite3.Connection)`` (e.g. the
    ``locked_read`` decorator) treats it like a stub connection and skips lock
    acquisition.  Wrap a connection only when the caller already serializes
    access to that connection.
    """

    __slots__ = ("_conn", "_threshold_ms")

    def __init__(self, conn: Any, threshold_ms: float | None = None) -> None:
        self._conn = conn
        self._threshold_ms = threshold_ms

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def __enter__(self) -> Self:
        self._conn.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        # sqlite3.Connection.__exit__ commits/rolls back and returns None.
        return self._conn.__exit__(exc_type, exc_value, exc_tb)

    def execute(self, sql: str, parameters: object = ...) -> Any:
        """Delegate to ``conn.execute`` with slow-query instrumentation."""

        def run() -> Any:
            if parameters is ...:
                return self._conn.execute(sql)
            return self._conn.execute(sql, parameters)

        return _timed_call(run, sql, parameters, self._threshold_ms)

    def executemany(self, sql: str, seq_of_parameters: object) -> Any:
        """Delegate to ``conn.executemany`` with slow-query instrumentation."""

        def run() -> Any:
            return self._conn.executemany(sql, seq_of_parameters)

        return _timed_call(run, sql, seq_of_parameters, self._threshold_ms)


def slow_query_wrapper(conn: Any, threshold_ms: float | None = None) -> Any:
    """Wrap ``conn`` in slow-query middleware, idempotently.

    Returns ``conn`` unchanged when it is already a :class:`SlowQueryConnection`.
    """
    if isinstance(conn, SlowQueryConnection):
        return conn
    return SlowQueryConnection(conn, threshold_ms)


# One-shot guard: compatibility helpers warn at most once per process about
# routing through the ThreadSafeSingleton DatabaseManager instead of DI.
def _flush_directory_durable(directory: Path) -> None:
    """Flush a directory entry update, or fail instead of claiming durability.

    The identity marker is published with ``os.link``.  Flushing the marker
    file before that operation only makes its contents durable; the directory
    entry itself still needs to be flushed.  POSIX exposes that operation via
    a directory file descriptor.  Windows requires a directory handle opened
    with ``FILE_FLAG_BACKUP_SEMANTICS`` and ``FlushFileBuffers``.

    This helper deliberately raises on unsupported or failed operations.  A
    caller may then keep the already-published marker while reporting the
    current open as failed closed.
    """
    if os.name != "nt":
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        fd = os.open(directory, flags)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        return

    import ctypes
    from ctypes import wintypes

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except (AttributeError, OSError) as exc:
        raise OSError("Windows directory flush API is unavailable") from exc

    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    flush_file_buffers = kernel32.FlushFileBuffers
    flush_file_buffers.argtypes = [wintypes.HANDLE]
    flush_file_buffers.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    handle = create_file(
        str(directory),
        0x40000000,  # GENERIC_WRITE
        0x00000001 | 0x00000002 | 0x00000004,  # share read/write/delete
        None,
        0x00000003,  # OPEN_EXISTING
        0x02000000,  # FILE_FLAG_BACKUP_SEMANTICS
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        raise ctypes.WinError(ctypes.get_last_error())

    try:
        if not flush_file_buffers(handle):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        close_handle(handle)



def _ensure_directory_chain(directory: Path) -> tuple[Path, ...]:
    """Create a directory chain and return directories created by this call."""
    missing: list[Path] = []
    current = directory
    while True:
        try:
            if current.is_dir():
                break
            if current.exists() or current.is_symlink():
                raise NotADirectoryError(f"RuntimeData path is not a directory: {current}")
        except OSError:
            raise
        missing.append(current)
        parent = current.parent
        if parent == current:
            raise OSError(f"Cannot find a directory parent for RuntimeData path: {current}")
        current = parent

    created: list[Path] = []
    for candidate in reversed(missing):
        try:
            candidate.mkdir()
        except FileExistsError:
            if not candidate.is_dir():
                raise
        else:
            created.append(candidate)
    return tuple(created)


def _flush_directory_chain_durable(
    directory: Path, created: tuple[Path, ...]
) -> None:
    """Flush a directory entry and any newly created ancestors to their parent."""
    candidates = [directory]
    if created:
        candidates.extend(reversed(created))
        candidates.append(created[0].parent)
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(os.path.abspath(os.fspath(candidate)))
        if key in seen:
            continue
        seen.add(key)
        _flush_directory_durable(candidate)


_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS file_tags (
    file_path TEXT NOT NULL,
    tag       TEXT NOT NULL,
    PRIMARY KEY (file_path, tag)
);
CREATE INDEX IF NOT EXISTS idx_file_tags_tag ON file_tags(tag);

CREATE TABLE IF NOT EXISTS file_meta (
    file_path         TEXT PRIMARY KEY,
    notes             TEXT NOT NULL DEFAULT '',
    cached_size       INTEGER,
    cached_mtime      REAL,
    cached_file_count INTEGER,
    urls              TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS thumbnail_cache (
    cache_key    TEXT PRIMARY KEY,
    source_path  TEXT NOT NULL,
    source_mtime REAL NOT NULL,
    source_size  INTEGER DEFAULT 0,
    baked_size   INTEGER DEFAULT 256,
    cache_size   INTEGER DEFAULT 0,
    created_at   REAL DEFAULT (strftime('%s','now')),
    last_access  REAL DEFAULT (strftime('%s','now')),
    source_mtime_ns INTEGER,
    artifact_kind TEXT NOT NULL DEFAULT 'webp',
    render_profile TEXT
);

CREATE TABLE IF NOT EXISTS gallery_home (
    id         INTEGER NOT NULL PRIMARY KEY CHECK (id = 1),
    saved_at   REAL NOT NULL,
    projection TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_thumb_source ON thumbnail_cache(source_path);

CREATE TABLE IF NOT EXISTS library_stats (
    library_path   TEXT PRIMARY KEY,
    total_size     INTEGER DEFAULT 0,
    total_files    INTEGER DEFAULT 0,
    total_projects INTEGER DEFAULT 0,
    updated_at     REAL DEFAULT (strftime('%s','now'))
);
"""


@dataclass
class _ConnectionWriteState:
    lock: threading.RLock
    closed: bool = False
    library_root: str | None = None
    library_root_key: str | None = None
    performance_recorder: PerformanceRecorder | None = None
    owner_thread: int | None = None
    owner_depth: int = 0
    owner_state_lock: threading.Lock = field(default_factory=threading.Lock)


class _WriteGate:
    """Reader/writer gate for explicit writes and legacy global writes."""

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.Lock())
        self._readers = 0
        self._writer = False
        self._writer_thread: int | None = None
        self._writer_depth = 0
        self._waiting_writers = 0
        self._reader_local = threading.local()

    def current_thread_is_reader(self) -> bool:
        """Return whether the current thread holds a read admission."""
        return bool(getattr(self._reader_local, "depth", 0))

    def current_thread_is_writer(self) -> bool:
        """Return whether the current thread holds the writer admission."""
        with self._condition:
            return self._writer and self._writer_thread == threading.get_ident()

    @contextmanager
    def read(self):
        depth = getattr(self._reader_local, "depth", 0)
        if depth:
            self._reader_local.depth = depth + 1
            try:
                yield
            finally:
                self._reader_local.depth -= 1
            return
        with self._condition:
            self._condition.wait_for(lambda: not self._writer and self._waiting_writers == 0)
            self._readers += 1
            self._reader_local.depth = 1
        try:
            yield
        finally:
            with self._condition:
                self._reader_local.depth = 0
                self._readers -= 1
                if self._readers == 0:
                    self._condition.notify_all()

    @contextmanager
    def write(self):
        thread_id = threading.get_ident()
        with self._condition:
            if self._writer_thread == thread_id:
                self._writer_depth += 1
                reentrant = True
            else:
                reentrant = False
        if reentrant:
            try:
                yield
            finally:
                with self._condition:
                    self._writer_depth -= 1
            return
        with self._condition:
            self._waiting_writers += 1
            self._condition.wait_for(lambda: not self._writer and self._readers == 0)
            self._waiting_writers -= 1
            self._writer = True
            self._writer_thread = thread_id
            self._writer_depth = 1
        try:
            yield
        finally:
            with self._condition:
                self._writer_depth -= 1
                if self._writer_depth == 0:
                    self._writer = False
                    self._writer_thread = None
                    self._condition.notify_all()


# sqlite3.Connection objects cannot be weak-referenced. Managed connections are
# keyed by object id and removed on close, so their lock state cannot retain a
# closed connection. Unmanaged compatibility connections share one fallback
# lock because they have no lifecycle owner to register a per-library lock.
_connection_locks: dict[int, _ConnectionWriteState] = {}
_connection_locks_guard = threading.RLock()
_unmanaged_write_state = _ConnectionWriteState(threading.RLock())
_write_gate = _WriteGate()


def _write_lock_for(conn: sqlite3.Connection) -> _ConnectionWriteState:
    """Return the stable write lock associated with one SQLite connection."""
    with _connection_locks_guard:
        state = _connection_locks.get(id(conn))
        if state is None:
            try:
                conn.execute("SELECT 1")
            except sqlite3.ProgrammingError as exc:
                raise RuntimeError("Cannot write through a closed database connection") from exc
            return _unmanaged_write_state
        return state


@contextmanager
def _identity_claim_lock(lock_path: Path):
    """Acquire a crash-releasing lock for one hashed identity slot.

    The lock file is intentionally retained after release.  Its filesystem
    entry is harmless; the OS lock itself is what coordinates claimants and is
    released automatically when a process exits.  This lets a new opener
    distinguish an active pending claimant from a crashed claimant without
    guessing from file age or PID reuse.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = lock_path.open("a+b")
    except OSError as exc:
        raise RuntimeError(
            f"Cannot open RuntimeData identity claim lock: {lock_path}"
        ) from exc

    acquired = False
    unlock = None
    try:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)

        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                yield False
                return

            def release_windows_lock() -> None:
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass

            unlock = release_windows_lock
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                yield False
                return

            def release_posix_lock() -> None:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass

            unlock = release_posix_lock

        acquired = True
        yield True
    finally:
        if acquired and unlock is not None:
            unlock()
        handle.close()


def _legacy_migration_looks_complete(identity: RootIdentity, legacy_dir: Path,
                                     lib_dir: Path) -> bool:
    """Return whether a failed legacy move may be treated as already done.

    ``shutil.move`` of a directory raises a spurious OSError when a concurrent
    opener has already performed the rename (the source vanished) or when the
    destination already received the database payload.  Both states are
    idempotently complete: failing the open afterwards would poison a healthy
    library over a harmless race.
    """
    if not lib_dir.exists():
        return False
    if not legacy_dir.exists():
        # The source vanished: another opener completed the rename.
        return True
    # Both directories still exist: accept only the essential payload arrival.
    return db_path(identity).exists()


def _persisted_library_roots() -> list[str]:
    """Return library roots recorded in application settings.

    ``recent_libraries`` is the only persisted registry of library roots the
    application maintains.  Offline roots cannot pass ``Path.exists()``, so
    orphan cleanup consults this registry instead of the filesystem to keep
    their RuntimeData slots protected while their drive is disconnected.
    """
    try:
        from AssetsManager.core.settings import AppSettings

        roots = AppSettings.instance().get_list("recent_libraries")
    except Exception:
        # A settings failure must never turn orphan cleanup into a destructive
        # sweep. AppSettings already logs its own load failures; falling back
        # to an empty registry keeps marker-based protection intact.
        return []
    return [root for root in roots if root] if isinstance(roots, list) else []


class DatabaseManager:
    """App-level manager for explicit per-library database resources."""

    @staticmethod
    def _identity(root_path: str | Path | RootIdentity) -> RootIdentity:
        """Preserve captured identities; only legacy raw paths are resolved."""
        if isinstance(root_path, RootIdentity):
            return root_path
        return root_identity(root_path, strict=False)

    def __init__(self, performance_recorder: PerformanceRecorder | None = None):
        self._connections: dict[str, sqlite3.Connection] = {}
        self._connection_locks: dict[str, _ConnectionWriteState] = {}
        self._write_lock = threading.RLock()
        self._performance_recorder = (
            performance_recorder if performance_recorder is not None and performance_recorder.enabled else None
        )

    @staticmethod
    def _is_reserved_legacy_dir(path: Path) -> bool:
        """Return whether ``path`` is a RuntimeData directory we must not move.

        Legacy migration is intentionally fail-closed for the runtime
        coordination directories. A library whose basename happens to match
        one of these names must not be allowed to move shared/quarantine state.
        """
        return path.name.casefold() in _LEGACY_MIGRATION_RESERVED_NAMES

    @staticmethod
    def _ensure_library_data_identity(identity: RootIdentity) -> bool:
        """Atomically claim and validate the hashed RuntimeData slot."""
        marker = library_data_identity_path(identity)
        pending = marker.with_name(marker.name + ".pending")
        claim_lock = marker.with_name(marker.name + ".pending.lock")
        try:
            created_directories = _ensure_directory_chain(marker.parent)
        except OSError as exc:
            raise RuntimeError(
                f"Cannot prepare RuntimeData identity marker directory: {marker.parent}"
            ) from exc
        expected = identity.map_key

        def collision(path: Path) -> RuntimeError:
            return RuntimeError(
                "RuntimeData identity collision detected: "
                f"{identity.display_path} conflicts with {path}"
            )

        def read_marker(path: Path, *, label: str) -> str:
            """Read a regular identity marker without following symlinks."""
            try:
                info = path.lstat()
            except FileNotFoundError:
                raise
            except OSError as exc:
                raise RuntimeError(
                    f"Cannot inspect {label} RuntimeData identity marker: {path}"
                ) from exc
            if not stat.S_ISREG(info.st_mode):
                raise RuntimeError(
                    f"Invalid {label} RuntimeData identity marker: {path}"
                )
            try:
                return path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise RuntimeError(
                    f"Cannot read {label} RuntimeData identity marker: {path}"
                ) from exc

        def publish_no_clobber(source: Path) -> bool:
            """Publish ``source`` without ever replacing an existing marker.

            ``os.link`` is the no-clobber primitive: it creates the formal
            marker only when the destination does not yet exist. A losing
            publisher inspects the winner rather than overwriting it.
            """
            try:
                os.link(source, marker)
            except FileExistsError:
                actual = read_marker(marker, label="formal")
                if actual != expected:
                    raise collision(marker) from None
                if created_directories:
                    try:
                        _flush_directory_chain_durable(marker.parent, created_directories)
                    except OSError as exc:
                        raise RuntimeError(
                            "RuntimeData identity marker published but directory "
                            f"durability could not be confirmed: {marker.parent}"
                        ) from exc
                return False
            except OSError as exc:
                raise RuntimeError(
                    f"Cannot publish RuntimeData identity marker: {marker}"
                ) from exc
            try:
                _flush_directory_chain_durable(marker.parent, created_directories)
            except OSError as exc:
                # The formal marker is intentionally retained.  It has won
                # the no-clobber race and must never be removed by a loser or
                # by the publisher after other processes may have observed it.
                raise RuntimeError(
                    "RuntimeData identity marker published but directory "
                    f"durability could not be confirmed: {marker.parent}"
                ) from exc
            return True

        def publish_from_unique_temp() -> bool:
            """Publish a fresh marker without aliasing a fixed pending file."""
            temp_marker: Path | None = None
            fd: int | None = None
            try:
                fd, temp_name = tempfile.mkstemp(
                    prefix=f".{marker.name}.",
                    suffix=".tmp",
                    dir=marker.parent,
                )
                temp_marker = Path(temp_name)
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    fd = None
                    stream.write(expected)
                    stream.flush()
                    os.fsync(stream.fileno())
                return publish_no_clobber(temp_marker)
            except (OSError, UnicodeError) as exc:
                raise RuntimeError(
                    f"Cannot publish RuntimeData identity marker: {marker}"
                ) from exc
            finally:
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                if temp_marker is not None:
                    try:
                        temp_marker.unlink()
                    except FileNotFoundError:
                        pass
                    except OSError:
                        # Never remove an unrelated path if cleanup itself
                        # encounters an error.
                        pass

        for _ in range(100):
            try:
                actual = read_marker(marker, label="formal")
            except FileNotFoundError:
                with _identity_claim_lock(claim_lock) as acquired:
                    if not acquired:
                        time.sleep(0.01)
                        continue
                    # Re-read after acquiring the slot lock. A claimant may
                    # have published the marker while this opener was waiting.
                    try:
                        actual = read_marker(marker, label="formal")
                    except FileNotFoundError:
                        try:
                            pending_info = pending.lstat()
                        except FileNotFoundError:
                            pending_info = None
                        except OSError as exc:
                            raise RuntimeError(
                                f"Cannot inspect pending RuntimeData identity marker: {pending}"
                            ) from exc

                        if pending_info is not None:
                            if not stat.S_ISREG(pending_info.st_mode):
                                raise RuntimeError(
                                    f"Invalid pending RuntimeData identity marker: {pending}"
                                ) from None
                            pending_owner = read_marker(pending, label="pending")
                            if pending_owner != expected:
                                raise collision(pending) from None

                            # A matching fixed pending marker is a recoverable
                            # prior claim. Publish a fresh copy so the formal
                            # marker never aliases a file another call may
                            # rewrite during recovery.
                            return publish_from_unique_temp()

                        return publish_from_unique_temp()
                    except (OSError, UnicodeError) as exc:
                        raise RuntimeError(
                            f"Cannot read RuntimeData identity marker: {marker}"
                        ) from exc

                    if actual != expected:
                        raise collision(marker) from None
                    return False
            except (OSError, UnicodeError) as exc:
                raise RuntimeError(
                    f"Cannot read RuntimeData identity marker: {marker}"
                ) from exc

            if actual != expected:
                raise collision(marker)
            return False

        raise RuntimeError(
            f"RuntimeData identity marker creation is pending: {pending}"
        )

    def open_library(self, root_path: str | Path | RootIdentity):
        with self._write_lock:
            identity = self._identity(root_path)
            key = identity.map_key
            lib_dir = library_data_dir(identity)
            legacy_dir = legacy_library_data_dir(identity)
            # Once the formal marker is published, retain it across all later
            # preparation failures. Removing it after a legacy move or directory
            # side effect can leave data without its collision guard, allowing a
            # different identity to claim the same truncated RuntimeData slot.
            self._ensure_library_data_identity(identity)
            if legacy_dir != lib_dir and legacy_dir.exists():
                if self._is_reserved_legacy_dir(legacy_dir):
                    # A basename collision with RuntimeData coordination state is
                    # ambiguous. Refuse to open rather than creating a fresh,
                    # empty database beside metadata we cannot safely migrate.
                    raise RuntimeError(
                        "Reserved RuntimeData directory cannot be migrated: "
                        f"{legacy_dir}"
                    )
                elif lib_dir.exists():
                    raise RuntimeError(
                        "Legacy and hashed RuntimeData directories both exist: "
                        f"{legacy_dir} and {lib_dir}"
                    )
                else:
                    try:
                        shutil.move(str(legacy_dir), str(lib_dir))
                    except OSError as exc:
                        if not _legacy_migration_looks_complete(
                            identity, legacy_dir, lib_dir
                        ):
                            raise RuntimeError(
                                f"Legacy RuntimeData migration failed: {legacy_dir}"
                            ) from exc
            lib_dir.mkdir(parents=True, exist_ok=True)
            # Prepare all per-library filesystem resources before publishing
            # a managed SQLite connection. A thumbnail-directory failure
            # must not leave a live connection in the manager registries.
            thumb_dir(identity).mkdir(parents=True, exist_ok=True)

            if key not in self._connections:
                path = db_path(identity)
                conn = sqlite3.connect(
                    str(path),
                    check_same_thread=False,
                    timeout=SQLITE_BUSY_TIMEOUT_MS / 1000,
                )
                conn.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
                state = _ConnectionWriteState(
                    threading.RLock(),
                    library_root=str(identity.display_path),
                    library_root_key=identity.map_key,
                    performance_recorder=self._performance_recorder,
                )
                # Register the connection before schema/migration work so a
                # failed initialization remains part of the same retryable
                # close contract as an already-published library connection.
                self._connections[key] = conn
                self._connection_locks[key] = state
                with _connection_locks_guard:
                    _connection_locks[id(conn)] = state
                try:
                    preflight_recorded_version(conn)
                    conn.executescript(_SCHEMA)
                    migrate_db(conn)
                    conn.commit()
                except BaseException as error:
                    state.closed = True
                    try:
                        self._close_managed_connection(key, conn, state)
                    except BaseException as close_error:
                        try:
                            error.add_note(
                                f"Database initialization cleanup is pending: {close_error}"
                            )
                        except (AttributeError, TypeError):
                            pass
                    raise
            else:
                state = self._connection_locks.get(key)
                if state is None or state.closed:
                    raise RuntimeError(
                        f"Database connection cleanup is pending: {key}"
                    )

    @classmethod
    def require_managed_connection_owner(
        cls,
        root_path: str | Path | RootIdentity,
        conn: sqlite3.Connection,
    ) -> sqlite3.Connection:
        """Require a registered connection owned by the requested library root.

        This is the strict ownership boundary for canonical service assembly.
        Unlike :meth:`validate_connection_owner`, unmanaged raw connections are
        rejected instead of being preserved for legacy compatibility callers.
        """
        requested = cls._identity(root_path)
        with _connection_locks_guard:
            state = _connection_locks.get(id(conn))
            if state is None:
                raise RuntimeError(
                    "Canonical database provider returned an unmanaged connection"
                )
            if state.closed:
                raise RuntimeError(
                    "Database connection cleanup is pending"
                )
            owner_key = state.library_root_key
            owner_root = state.library_root

        if owner_key is None or owner_root is None:
            raise RuntimeError(
                "Managed database connection is missing library root ownership metadata"
            )
        if owner_key != requested.map_key:
            raise ValueError(
                "Managed database connection belongs to a different library root: "
                f"{owner_root} (requested {requested.display_path})"
            )
        return conn

    @classmethod
    def validate_connection_owner(
        cls,
        root_path: str | Path | RootIdentity,
        conn: sqlite3.Connection,
        *,
        allow_unmanaged: bool = True,
    ) -> sqlite3.Connection:
        """Validate a connection's library-root ownership.

        Connections registered by any ``DatabaseManager`` instance are bound to
        the root captured when they were opened. Unregistered connections are
        accepted only when ``allow_unmanaged`` is true, which preserves the
        explicit legacy/raw compatibility path. Canonical assembly should use
        :meth:`require_managed_connection_owner` instead.
        """
        requested = cls._identity(root_path)
        with _connection_locks_guard:
            state = _connection_locks.get(id(conn))
            if state is None:
                if allow_unmanaged:
                    return conn
                raise RuntimeError(
                    "Database connection is not managed by DatabaseManager"
                )
            if state.closed:
                raise RuntimeError(
                    "Database connection cleanup is pending"
                )
            owner_key = state.library_root_key
            owner_root = state.library_root

        if owner_key is None or owner_root is None:
            raise RuntimeError(
                "Managed database connection is missing library root ownership metadata"
            )
        if owner_key != requested.map_key:
            raise ValueError(
                "Managed database connection belongs to a different library root: "
                f"{owner_root} (requested {requested.display_path})"
            )
        return conn

    def connection_for(self, root_path: str | Path | RootIdentity) -> sqlite3.Connection:
        """Return the SQLite connection for a library root explicitly."""
        identity = self._identity(root_path)
        key = identity.map_key
        with self._write_lock:
            self.open_library(identity)
            conn = self._connections.get(key)
            state = self._connection_locks.get(key)
            if conn is None or state is None or state.closed:
                raise RuntimeError(f"Database connection cleanup is pending: {key}")
            return conn

    def data_dir_for(self, root_path: str | Path | RootIdentity) -> Path:
        """Return the RuntimeData directory for a library root explicitly."""
        identity = self._identity(root_path)
        self.open_library(identity)
        return library_data_dir(identity)

    def thumb_dir_for(self, root_path: str | Path | RootIdentity) -> Path:
        """Return the thumbnail directory for a library root explicitly."""
        identity = self._identity(root_path)
        self.open_library(identity)
        return thumb_dir(identity)

    def _close_managed_connection(
        self, key: str, conn: sqlite3.Connection, state: _ConnectionWriteState
    ) -> None:
        """Close one connection without losing retry ownership on failure."""
        with state.lock:
            # Do not remove either registry entry until SQLite confirms that
            # the underlying connection actually closed.  A close failure must
            # leave the connection and its closed write state available for an
            # explicit teardown retry.
            conn.close()
        if self._connections.get(key) is conn:
            self._connections.pop(key, None)
        if self._connection_locks.get(key) is state:
            self._connection_locks.pop(key, None)
        with _connection_locks_guard:
            if _connection_locks.get(id(conn)) is state:
                _connection_locks.pop(id(conn), None)

    def close(self):
        # Publish rejection before waiting for globally admitted writers so a
        # writer queued on a connection lock cannot start after close begins.
        with self._write_lock:
            if _write_gate.current_thread_is_reader():
                raise RuntimeError(
                    "Cannot close databases while the current thread holds db_write_lock"
                )
            for state in self._connection_locks.values():
                with state.owner_state_lock:
                    if state.owner_thread == threading.get_ident() and state.owner_depth:
                        raise RuntimeError(
                            "Cannot close a database while the current thread holds db_write_lock"
                        )
            for state in self._connection_locks.values():
                state.closed = True
        with _write_gate.write():
            with self._write_lock:
                for key, conn in tuple(self._connections.items()):
                    state = self._connection_locks.get(key)
                    if state is None:
                        state = _ConnectionWriteState(self._write_lock, closed=True)
                    self._close_managed_connection(key, conn, state)

    def close_library(self, root_path: str | Path | RootIdentity) -> None:
        """Close the SQLite connection for a single library root."""
        identity = self._identity(root_path)
        key = identity.map_key
        # Preserve the state registry until teardown completes, but reject
        # writers that were already queued behind a currently active holder.
        with self._write_lock:
            if _write_gate.current_thread_is_reader():
                raise RuntimeError(
                    "Cannot close a database while the current thread holds db_write_lock"
                )
            state = self._connection_locks.get(key)
            if state is not None:
                with state.owner_state_lock:
                    if state.owner_thread == threading.get_ident() and state.owner_depth:
                        raise RuntimeError(
                            "Cannot close a database while the current thread holds db_write_lock"
                        )
                state.closed = True
        with _write_gate.write():
            with self._write_lock:
                conn = self._connections.get(key)
                if conn is None:
                    return
                state = self._connection_locks.get(key)
                if state is None:
                    state = _ConnectionWriteState(self._write_lock, closed=True)
                self._close_managed_connection(key, conn, state)
    @staticmethod
    def clean_orphan_dirs(known_roots: list[str]):
        if not RUNTIME_ROOT.exists():
            return
        known_names = {library_data_name(r) for r in known_roots if r and Path(r).exists()}
        legacy_names = {Path(r).resolve().name for r in known_roots if r}
        known_names.update(legacy_names)
        # Offline library roots never satisfy Path.exists(), so their hashed
        # and legacy RuntimeData slots would be swept as orphans. Extend the
        # protection to the persisted recent_libraries registry as well; a
        # library is recorded there on open regardless of current availability.
        persisted_roots = _persisted_library_roots()
        known_names.update(library_data_name(r) for r in persisted_roots)
        known_names.update(Path(r).resolve().name for r in persisted_roots)
        shared_root = RUNTIME_ROOT / "Shared"
        marked_names: set[str] = set()
        try:
            if shared_root.is_dir():
                marked_names = {
                    marker.name[:-len(".identity")]
                    for marker in shared_root.iterdir()
                    if marker.name.endswith(".identity")
                    and (marker.is_file() or marker.is_symlink())
                }
        except OSError:
            # If the marker index cannot be inspected, do not make any cleanup
            # decision: a marker-bearing directory may be metadata-bearing.
            return
        known_names.update(marked_names)
        cutoff = time.time() - 7 * 86400
        orphan_candidates = []
        for entry in RUNTIME_ROOT.iterdir():
            if (
                not entry.is_dir()
                or entry.is_symlink()
                or entry.name.casefold() in {"shared", _ORPHANED_DIR_NAME}
                or entry.name in known_names
            ):
                continue
            try:
                if entry.stat().st_mtime < cutoff:
                    orphan_candidates.append(entry)
            except OSError:
                continue

        if not orphan_candidates:
            return
        quarantine_root = RUNTIME_ROOT / _ORPHANED_DIR_NAME
        try:
            quarantine_root.mkdir(parents=True, exist_ok=True)
        except OSError:
            return

        for entry in orphan_candidates:
            target = quarantine_root / entry.name
            if target.exists() or target.is_symlink():
                stamp = time.strftime("%Y%m%d-%H%M%S")
                target = quarantine_root / f"{entry.name}_{stamp}"
                counter = 1
                while target.exists() or target.is_symlink():
                    target = quarantine_root / f"{entry.name}_{stamp}_{counter}"
                    counter += 1
            try:
                entry.replace(target)
            except OSError:
                try:
                    shutil.move(str(entry), str(target))
                except OSError:
                    pass

@contextmanager
def db_write_lock(conn: sqlite3.Connection | None = None):
    """Serialize writes through the lock that owns ``conn``.

    New repository code must pass its explicit connection so the lock and
    connection share one ``DatabaseManager`` runtime. The no-argument form is
    a legacy reentrant lock only; it is not bound to any library connection.
    """
    if conn is not None:
        state = _write_lock_for(conn)
        thread_id = threading.get_ident()
        with state.owner_state_lock:
            outermost = state.owner_thread != thread_id
        # A thread already holding the legacy global write admission would
        # deadlock inside _WriteGate.read (its own writer flag blocks the
        # reader wait). Fail fast instead of hanging forever.
        if _write_gate.current_thread_is_writer():
            raise RuntimeError(
                "Cannot acquire a connection-owned db_write_lock while the "
                "current thread holds the legacy global db_write_lock "
                "(this would deadlock)"
            )
        with _write_gate.read():
            recorder = state.performance_recorder
            wait_started = time.perf_counter() if recorder is not None and outermost else None
            with state.lock:
                acquired_at = time.perf_counter() if wait_started is not None else None
                if state.closed:
                    _record_write_lock(
                        state, "rejected", wait_started, acquired_at, None
                    )
                    raise RuntimeError("Cannot write through a closed database connection")
                with state.owner_state_lock:
                    state.owner_thread = thread_id
                    state.owner_depth += 1
                outcome = "completed"
                try:
                    yield
                except BaseException:
                    outcome = "error"
                    raise
                finally:
                    with state.owner_state_lock:
                        state.owner_depth -= 1
                        if state.owner_depth == 0:
                            state.owner_thread = None
                    if outermost:
                        released_at = time.perf_counter() if recorder is not None else None
                        _record_write_lock(state, outcome, wait_started, acquired_at, released_at)
        return
    # A thread already holding a connection-owned read admission (acquired in
    # the branch above) would deadlock inside _WriteGate.write: its own reader
    # count keeps the writer wait from ever being satisfied. Fail fast instead
    # of hanging forever.
    if _write_gate.current_thread_is_reader():
        raise RuntimeError(
            "Cannot acquire the legacy global db_write_lock while the current "
            "thread holds a connection-owned db_write_lock (this would deadlock)"
        )
    with _write_gate.write():
        yield


def locked_read(method):
    """Serialize a repository read through its connection's write lock.

    Every repository in the LAN path shares one ``check_same_thread=False``
    connection across the aiohttp event-loop thread, ``to_thread`` workers
    (analytics, downloads) and the gallery build threads; an unguarded
    SELECT racing an in-flight write transaction surfaces as intermittent
    ``sqlite3.OperationalError`` (database is locked) or recursive-cursor
    errors.  The connection lock is reentrant, so nesting under an existing
    ``db_write_lock``/``_transaction``/``_write_scope`` is safe.
    """
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        conn = getattr(self, "_conn", None)
        if conn is None or not isinstance(conn, sqlite3.Connection):
            # Fake/stub connections (unit tests) have no lock state; run the
            # read unchanged.
            return method(self, *args, **kwargs)
        # The guard below must cover only *acquiring* the lock, never the
        # method body: ``db_write_lock`` runs its fail-fast checks
        # (lock-order hazards, closed connection) inside ``__enter__``, so
        # entering through an ExitStack is the acquisition step. A
        # RuntimeError raised by ``method`` itself is a business error and
        # must propagate once from the locked run instead of being mistaken
        # for a rejected acquisition and silently re-running the read
        # without the lock.
        with ExitStack() as lock_stack:
            try:
                lock_stack.enter_context(db_write_lock(conn))
            except RuntimeError:
                # db_write_lock rejects closed connections (and fails fast on
                # lock-order hazards); the read must still run so the original
                # sqlite3 error semantics (e.g. ProgrammingError on a closed
                # connection) propagate unchanged.
                return method(self, *args, **kwargs)
            return method(self, *args, **kwargs)
    return wrapper


def _record_write_lock(
    state: _ConnectionWriteState,
    outcome: str,
    wait_started: float | None,
    acquired_at: float | None,
    released_at: float | None,
) -> None:
    """Record lock timing after a connection-owned admission decision."""
    recorder = state.performance_recorder
    if recorder is None or wait_started is None:
        return
    try:
        if acquired_at is not None:
            recorder.record(
                "db.write_lock.wait",
                (acquired_at - wait_started) * 1000,
                path=state.library_root,
                attributes={"outcome": outcome},
            )
        if outcome in {"completed", "error"} and acquired_at is not None and released_at is not None:
            recorder.record(
                "db.write_lock.hold",
                (released_at - acquired_at) * 1000,
                path=state.library_root,
                attributes={"outcome": outcome},
            )
    except Exception:
        # Telemetry must not affect write admission, commit, or close coordination.
        pass


def _migrate_path_metadata_impl(conn: sqlite3.Connection, thumb_dir: Path,
                                old_path: str | Path, new_path: str):
    """Move metadata between paths using explicit library-owned resources."""
    old = str(Path(old_path).resolve())
    new = str(Path(new_path).resolve())
    if old == new:
        return
    descendant_pattern = sql_like_descendant_pattern(old)

    def remap(path: str) -> str:
        return remap_path_subtree(old, new, path)

    with db_write_lock(conn):
        # Case semantics: the SELECT below matches with ``=`` (case-sensitive)
        # or LIKE (case-insensitive for ASCII), while ``remap_path_subtree``
        # is a case-sensitive prefix remap.  A row the LIKE arm selected but
        # remap does not change (e.g. a differently-cased spelling of the
        # subtree) is therefore skipped from both INSERT and DELETE: it must
        # never be deleted, and on case-insensitive filesystems its stored
        # path still resolves to the same file.  Only rows remap actually
        # rewrites are deleted, and only by exact match, so a row remap left
        # alone can never be removed by this migration.
        tag_rows = conn.execute(
            "SELECT file_path, tag FROM file_tags WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
            (old, descendant_pattern),
        ).fetchall()
        for path, tag in tag_rows:
            conn.execute(
                "INSERT OR IGNORE INTO file_tags (file_path, tag) VALUES (?,?)",
                (remap(path), tag),
            )
        stale_tag_paths = sorted({
            path for path, _tag in tag_rows if remap(path) != path
        })
        if stale_tag_paths:
            conn.executemany(
                "DELETE FROM file_tags WHERE file_path=?",
                [(path,) for path in stale_tag_paths],
            )

        meta_rows = conn.execute(
            "SELECT file_path, notes, cached_size, cached_mtime, cached_file_count, urls "
            "FROM file_meta WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
            (old, descendant_pattern),
        ).fetchall()
        for path, notes, cached_size, cached_mtime, cached_file_count, urls in meta_rows:
            conn.execute(
                "INSERT INTO file_meta "
                "(file_path, notes, cached_size, cached_mtime, cached_file_count, urls) "
                "VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(file_path) DO UPDATE SET "
                "notes=CASE WHEN excluded.notes!='' THEN excluded.notes ELSE file_meta.notes END, "
                "cached_size=COALESCE(excluded.cached_size, file_meta.cached_size), "
                "cached_mtime=COALESCE(excluded.cached_mtime, file_meta.cached_mtime), "
                "cached_file_count=COALESCE(excluded.cached_file_count, file_meta.cached_file_count), "
                "urls=CASE WHEN excluded.urls!='[]' THEN excluded.urls ELSE file_meta.urls END",
                (remap(path), notes, cached_size, cached_mtime, cached_file_count, urls),
            )
        stale_meta_paths = sorted({
            path for path, _notes, _size, _mtime, _count, _urls in meta_rows
            if remap(path) != path
        })
        if stale_meta_paths:
            conn.executemany(
                "DELETE FROM file_meta WHERE file_path=?",
                [(path,) for path in stale_meta_paths],
            )

        favorites_table = conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='library_favorites'"
        ).fetchone()
        if favorites_table is not None:
            favorite_rows = conn.execute(
                "SELECT owner_key, file_path, created_at FROM library_favorites "
                "WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
                (old, descendant_pattern),
            ).fetchall()
            for owner_key, path, created_at in favorite_rows:
                conn.execute(
                    "INSERT OR IGNORE INTO library_favorites "
                    "(owner_key, file_path, created_at) VALUES (?, ?, ?)",
                    (owner_key, remap(path), created_at),
                )
            stale_favorite_paths = sorted({
                path for _owner_key, path, _created_at in favorite_rows
                if remap(path) != path
            })
            if stale_favorite_paths:
                conn.executemany(
                    "DELETE FROM library_favorites WHERE file_path=?",
                    [(path,) for path in stale_favorite_paths],
                )

        thumb_rows = conn.execute(
            "SELECT cache_key, source_path, artifact_kind, render_profile "
            "FROM thumbnail_cache WHERE source_path=? OR source_path LIKE ? ESCAPE '\\'",
            (old, descendant_pattern),
        ).fetchall()
        for old_key, source_path, artifact_kind, render_profile in thumb_rows:
            mapped = remap(source_path)
            extension = "jpg" if artifact_kind == "jpg" else "webp"
            if render_profile and artifact_kind == "webp":
                try:
                    new_key = profiled_thumbnail_cache_key_v3(mapped, normalize_webp_render_profile(render_profile))
                except ValueError:
                    _log.warning("Unknown thumbnail render profile during path migration: %s", render_profile)
                    new_key = _thumbnail_cache_key(mapped)
            else:
                new_key = _thumbnail_cache_key(mapped)
            old_file = thumb_dir / f"{old_key}.{extension}"
            new_file = thumb_dir / f"{new_key}.{extension}"
            collision = old_key != new_key and old_file.exists() and new_file.exists()
            if collision:
                _log.warning(
                    "Thumbnail migration collision: %s already exists for %s; keeping %s",
                    new_file, mapped, old_file,
                )
            # Decide the rename from the destination row BEFORE moving any
            # file. ``cache_key`` is derived from the source path, so an
            # existing ``new_key`` row whose artifact is already missing is a
            # stale entry; renaming ``old_file`` onto ``new_file`` anyway
            # would leave the retained ``old_key`` row (kept below) pointing
            # at a file that no longer exists — a guaranteed miss. Skipping
            # the rename matches this function's existing idempotent
            # destination-row semantics (keep the old_key row, touch no
            # file, never delete rows): the stale ``new_key`` row stays a
            # dead entry that regenerates its artifact on its next lookup
            # miss, while the old artifact remains valid under ``old_key``.
            destination_row = conn.execute(
                "SELECT 1 FROM thumbnail_cache WHERE cache_key=?",
                (new_key,),
            ).fetchone() if new_key != old_key else None
            if destination_row is not None:
                conn.execute(
                    "UPDATE thumbnail_cache SET source_path=? WHERE cache_key=?",
                    (mapped, old_key),
                )
                continue
            if old_file.exists() and old_key != new_key:
                try:
                    if not new_file.exists():
                        old_file.replace(new_file)
                except OSError:
                    _log.exception("Thumbnail migration failed: %s -> %s", old_file, new_file)
                    raise
            conn.execute(
                "UPDATE thumbnail_cache SET cache_key=?, source_path=? WHERE cache_key=?",
                (new_key, mapped, old_key),
            )


def migrate_path_metadata(conn: sqlite3.Connection, thumb_dir: Path,
                          old_path: str | Path, new_path: str | Path):
    """Atomically move path projections within the caller's transaction boundary.

    The SQLite savepoint rolls back all database projections on failure while
    preserving any caller-owned outer transaction. Thumbnail file renames are
    external side effects and cannot be rolled back by SQLite.
    """
    old = str(Path(old_path).resolve())
    new = str(Path(new_path).resolve())
    if old == new:
        return

    savepoint = "path_metadata_migration"
    with db_write_lock(conn):
        outer_transaction = conn.in_transaction
        conn.execute(f"SAVEPOINT {savepoint}")
        try:
            _migrate_path_metadata_impl(conn, thumb_dir, old, new)
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            if not outer_transaction:
                conn.commit()
        except BaseException as exc:
            cleanup_error = None
            try:
                conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            except BaseException as cleanup_exc:
                cleanup_error = cleanup_exc
            if not outer_transaction and conn.in_transaction:
                try:
                    conn.rollback()
                except BaseException as rollback_exc:
                    if cleanup_error is None:
                        cleanup_error = rollback_exc
            if cleanup_error is not None:
                try:
                    exc.add_note(
                        "path metadata migration transaction cleanup failed: "
                        f"{type(cleanup_error).__name__}: {cleanup_error}"
                    )
                except Exception:
                    pass
            raise


def _thumbnail_cache_key(path: str) -> str:
    """Compatibility wrapper for the shared versioned thumbnail key."""
    return thumbnail_cache_key(path)


def clean_orphan_dirs(known_roots: list[str]):
    DatabaseManager.clean_orphan_dirs(known_roots)
