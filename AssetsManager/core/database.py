"""AssetManager database — unified SQLite persistence layer with lifecycle manager.

Provides:
- Per-library SQLite connections with WAL mode
- Schema initialization (file_tags, file_meta, thumbnail_cache)
- Thread-safe connection management
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import logging
import os
import shutil
import sqlite3
import stat
import tempfile
import threading
import time
from pathlib import Path

from AssetsManager.core.performance import PerformanceRecorder
from AssetsManager.core.path_resolver import (
    runtime_root, shared_dir, library_data_dir, library_data_name,
    library_data_identity_path, legacy_library_data_dir, thumb_dir,
    db_path, RootIdentity, root_identity, remap_path_subtree, sql_like_descendant_pattern,
)
from AssetsManager.core.db_migrations import (
    migrate as migrate_db,
    preflight_recorded_version,
)
from AssetsManager.core.singleton import ThreadSafeSingleton

RUNTIME_ROOT = runtime_root()
SHARED_DIR = shared_dir()
_ORPHANED_DIR_NAME = "_orphaned"
_LEGACY_MIGRATION_RESERVED_NAMES = frozenset({"shared", "_orphaned"})

_log = logging.getLogger(__name__)

# One-shot guard: compatibility helpers warn at most once per process about
# routing through the ThreadSafeSingleton DatabaseManager instead of DI.
_compat_singleton_warned = False


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
    last_access  REAL DEFAULT (strftime('%s','now'))
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
                    raise collision(marker)
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
                                )
                            pending_owner = read_marker(pending, label="pending")
                            if pending_owner != expected:
                                raise collision(pending)

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
                        raise collision(marker)
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
                conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
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
    @property
    def db_lock(self):
        return self._write_lock

    @contextmanager
    def write_lock(self):
        """Serialize SQLite writes across GUI, worker, and LAN threads."""
        with self._write_lock:
            yield

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


def get_library_dir(library_root: str) -> Path:
    """Return a prepared legacy-compatible library data directory.

    This helper intentionally remains path-only: it does not construct or open
    a ``DatabaseManager`` connection.  It nevertheless follows the canonical
    identity and legacy-directory preparation protocol so compatibility callers
    cannot create an unguarded hashed directory beside an older RuntimeData
    directory.
    """
    identity = root_identity(library_root, strict=False)
    directory = library_data_dir(identity)
    legacy_dir = legacy_library_data_dir(identity)

    DatabaseManager._ensure_library_data_identity(identity)
    if legacy_dir != directory and legacy_dir.exists():
        if DatabaseManager._is_reserved_legacy_dir(legacy_dir):
            raise RuntimeError(
                "Reserved RuntimeData directory cannot be migrated: "
                f"{legacy_dir}"
            )
        if directory.exists():
            raise RuntimeError(
                "Legacy and hashed RuntimeData directories both exist: "
                f"{legacy_dir} and {directory}"
            )
        try:
            shutil.move(str(legacy_dir), str(directory))
        except OSError as exc:
            if not _legacy_migration_looks_complete(identity, legacy_dir, directory):
                raise RuntimeError(
                    f"Legacy RuntimeData migration failed: {legacy_dir}"
                ) from exc

    directory.mkdir(parents=True, exist_ok=True)
    return directory


def migrate_path_metadata(conn: sqlite3.Connection, thumb_dir: Path,
                          old_path: str | Path, new_path: str | Path):
    """Move metadata between paths using explicit library-owned resources."""
    old = str(Path(old_path).resolve())
    new = str(Path(new_path).resolve())
    if old == new:
        return
    descendant_pattern = sql_like_descendant_pattern(old)

    def remap(path: str) -> str:
        return remap_path_subtree(old, new, path)

    with db_write_lock(conn):
        # A caller-owned outer transaction must never be committed by this
        # cross-projection migration helper. Session-bound file operations
        # reject such a transaction before moving the filesystem path.
        outer_transaction = conn.in_transaction
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
            "SELECT cache_key, source_path FROM thumbnail_cache "
            "WHERE source_path=? OR source_path LIKE ? ESCAPE '\\'",
            (old, descendant_pattern),
        ).fetchall()
        for old_key, source_path in thumb_rows:
            mapped = remap(source_path)
            new_key = _thumbnail_cache_key(mapped)
            old_file = thumb_dir / f"{old_key}.webp"
            new_file = thumb_dir / f"{new_key}.webp"
            if old_file.exists() and old_key != new_key:
                try:
                    if new_file.exists():
                        # The destination thumbnail already exists. Do not
                        # silently delete the old file: its cache row is
                        # repointed to the destination key below, and the old
                        # file is either regenerated from the new path or
                        # cleaned up manually. Deleting it here would discard
                        # a valid thumbnail without regenerating anything.
                        _log.warning(
                            "Thumbnail migration collision: %s already exists "
                            "for %s; keeping %s",
                            new_file, mapped, old_file,
                        )
                    else:
                        old_file.replace(new_file)
                except OSError:
                    pass
            conn.execute(
                "UPDATE OR REPLACE thumbnail_cache SET cache_key=?, source_path=? "
                "WHERE cache_key=?",
                (new_key, mapped, old_key),
            )
        if not outer_transaction:
            conn.commit()


def migrate_path_metadata_for_library(library_root: str | Path,
                                      old_path: str | Path, new_path: str | Path) -> None:
    """Legacy root-based compatibility wrapper for path metadata migration.

    This helper routes through ``ThreadSafeSingleton.get(DatabaseManager)``.
    The application wires its own ``DatabaseManager`` into the DI container
    (see ``AssetsManager.application.bootstrap``), so the singleton instance
    used here can differ from the DI-registered one — two DatabaseManager
    instances may then each own a connection to the same library.  Prefer the
    session-bound ``migrate_path_metadata`` call with an explicit connection;
    unifying the instances requires a DI refactor beyond this module's scope.
    """
    _warn_compat_singleton("migrate_path_metadata_for_library")
    manager = ThreadSafeSingleton.get(DatabaseManager)
    thumb_dir = manager.thumb_dir_for(library_root)
    thumb_dir.mkdir(parents=True, exist_ok=True)
    migrate_path_metadata(
        manager.connection_for(library_root), thumb_dir, old_path, new_path,
    )


def _thumbnail_cache_key(path: str) -> str:
    try:
        mtime = str(os.path.getmtime(path))
    except OSError:
        mtime = ""
    return hashlib.sha256(f"{path}|{mtime}".encode()).hexdigest()[:16]


def _warn_compat_singleton(helper: str) -> None:
    """Warn once per process about singleton-routed compatibility helpers.

    These helpers operate on ``ThreadSafeSingleton.get(DatabaseManager)``,
    which can be a different instance than the DI-registered DatabaseManager
    (see ``AssetsManager.application.bootstrap``).  The warning is emitted at
    most once per process so per-operation compatibility callers (file renames,
    test teardown) do not flood the log.
    """
    global _compat_singleton_warned
    if _compat_singleton_warned:
        return
    _compat_singleton_warned = True
    _log.warning(
        "%s routes through ThreadSafeSingleton.get(DatabaseManager), which may "
        "differ from the DI-registered DatabaseManager instance; prefer an "
        "explicit connection or unify the instances via DI",
        helper,
    )


def close_all_dbs():
    """Deprecated compatibility shutdown helper.

    Same singleton-vs-DI caveat as :func:`migrate_path_metadata_for_library`:
    only the ThreadSafeSingleton instance is closed here.  Callers owning the
    DI-registered manager should close that instance instead.
    """
    _warn_compat_singleton("close_all_dbs")
    ThreadSafeSingleton.get(DatabaseManager).close()


def clean_orphan_dirs(known_roots: list[str]):
    DatabaseManager.clean_orphan_dirs(known_roots)


def get_library_stats(library_root: str):
    """Return cached aggregate statistics for a library root.

    Same singleton-vs-DI caveat as :func:`migrate_path_metadata_for_library`:
    the stats are read through the ThreadSafeSingleton DatabaseManager, which
    may differ from the DI-registered instance owning the caller's connection.
    """
    _warn_compat_singleton("get_library_stats")
    conn = ThreadSafeSingleton.get(DatabaseManager).connection_for(library_root)
    row = conn.execute(
        "SELECT total_size, total_files, total_projects FROM library_stats WHERE library_path = ?",
        (str(Path(library_root).resolve()),)
    ).fetchone()
    if row:
        return {"total_size": row[0], "total_files": row[1], "total_projects": row[2]}
    return {"total_size": 0, "total_files": 0, "total_projects": 0}
