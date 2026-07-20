"""AssetManager database — unified SQLite persistence layer with lifecycle manager.

Provides:
- Per-library SQLite connections with WAL mode
- Schema initialization (file_tags, file_meta, thumbnail_cache)
- Thread-safe connection management
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import os
import shutil
import sqlite3
import threading
import time
from pathlib import Path

from AssetsManager.core.performance import PerformanceRecorder
from AssetsManager.core.path_resolver import (
    runtime_root, shared_dir, library_data_dir, library_data_name,
    legacy_library_data_dir, thumb_dir,
    db_path,
)
from AssetsManager.core.db_migrations import migrate as migrate_db
from AssetsManager.core.singleton import ThreadSafeSingleton

RUNTIME_ROOT = runtime_root()
SHARED_DIR = shared_dir()

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
CREATE INDEX IF NOT EXISTS idx_thumb_source ON thumbnail_cache(source_path);

CREATE TABLE IF NOT EXISTS library_stats (
    library_path   TEXT PRIMARY KEY,
    total_size     INTEGER DEFAULT 0,
    total_files    INTEGER DEFAULT 0,
    total_projects INTEGER DEFAULT 0,
    updated_at     REAL DEFAULT (strftime('%s','now'))
);

CREATE TABLE IF NOT EXISTS directory_cache (
    dir_path     TEXT PRIMARY KEY,
    item_count   INTEGER NOT NULL DEFAULT 0,
    preview_path TEXT,
    mtime        REAL NOT NULL,
    scanned_at   REAL NOT NULL DEFAULT (strftime('%s','now'))
);
"""


@dataclass
class _ConnectionWriteState:
    lock: threading.RLock
    closed: bool = False
    library_root: str | None = None
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


class DatabaseManager:
    """App-level manager for explicit per-library database resources."""

    def __init__(self, performance_recorder: PerformanceRecorder | None = None):
        self._connections: dict[str, sqlite3.Connection] = {}
        self._connection_locks: dict[str, _ConnectionWriteState] = {}
        self._write_lock = threading.RLock()
        self._performance_recorder = (
            performance_recorder if performance_recorder is not None and performance_recorder.enabled else None
        )

    def open_library(self, root_path: str):
        with self._write_lock:
            key = str(Path(root_path).resolve())
            lib_dir = library_data_dir(key)
            legacy_dir = legacy_library_data_dir(key)
            if legacy_dir != lib_dir and legacy_dir.exists() and not lib_dir.exists():
                try:
                    shutil.move(str(legacy_dir), str(lib_dir))
                except OSError:
                    pass
            lib_dir.mkdir(parents=True, exist_ok=True)

            if key not in self._connections:
                path = db_path(key)
                conn = sqlite3.connect(str(path), check_same_thread=False)
                conn.executescript(_SCHEMA)
                migrate_db(conn)
                conn.commit()
                self._connections[key] = conn
                state = _ConnectionWriteState(
                    threading.RLock(), library_root=key, performance_recorder=self._performance_recorder
                )
                self._connection_locks[key] = state
                with _connection_locks_guard:
                    _connection_locks[id(conn)] = state

            thumb_dir(key).mkdir(parents=True, exist_ok=True)

    def connection_for(self, root_path: str | Path) -> sqlite3.Connection:
        """Return the SQLite connection for a library root explicitly."""
        key = str(Path(root_path).resolve())
        self.open_library(key)
        conn = self._connections.get(key)
        if conn is None:
            raise RuntimeError(f"Failed to open library database: {key}")
        return conn

    def data_dir_for(self, root_path: str | Path) -> Path:
        """Return the RuntimeData directory for a library root explicitly."""
        key = str(Path(root_path).resolve())
        self.open_library(key)
        return library_data_dir(key)

    def thumb_dir_for(self, root_path: str | Path) -> Path:
        """Return the thumbnail directory for a library root explicitly."""
        key = str(Path(root_path).resolve())
        self.open_library(key)
        return thumb_dir(key)

    def close(self):
        # Publish rejection before waiting for globally admitted writers so a
        # writer queued on a connection lock cannot start after close begins.
        with self._write_lock:
            for state in self._connection_locks.values():
                state.closed = True
        with _write_gate.write():
            with self._write_lock:
                for key, conn in tuple(self._connections.items()):
                    state = self._connection_locks.pop(
                        key, _ConnectionWriteState(self._write_lock, closed=True)
                    )
                    with state.lock:
                        try:
                            conn.close()
                        except sqlite3.Error:
                            pass
                        finally:
                            with _connection_locks_guard:
                                if _connection_locks.get(id(conn)) is state:
                                    _connection_locks.pop(id(conn), None)
                self._connections.clear()

    def close_library(self, root_path: str | Path) -> None:
        """Close the SQLite connection for a single library root."""
        key = str(Path(root_path).resolve())
        # Preserve the state registry until teardown completes, but reject
        # writers that were already queued behind a currently active holder.
        with self._write_lock:
            state = self._connection_locks.get(key)
            if state is not None:
                state.closed = True
        with _write_gate.write():
            with self._write_lock:
                conn = self._connections.pop(key, None)
                if conn is not None:
                    state = self._connection_locks.pop(
                        key, _ConnectionWriteState(self._write_lock, closed=True)
                    )
                    with state.lock:
                        try:
                            conn.close()
                        except sqlite3.Error:
                            pass
                        finally:
                            with _connection_locks_guard:
                                if _connection_locks.get(id(conn)) is state:
                                    _connection_locks.pop(id(conn), None)
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
        legacy_names = {Path(r).resolve().name for r in known_roots if r and Path(r).exists()}
        known_names.update(legacy_names)
        cutoff = time.time() - 7 * 86400
        for entry in RUNTIME_ROOT.iterdir():
            if entry.is_dir() and entry.name != "Shared" and entry.name not in known_names:
                try:
                    if entry.stat().st_mtime < cutoff:
                        shutil.rmtree(str(entry), ignore_errors=True)
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
    """Deprecated path helper that does not open a database connection."""
    directory = library_data_dir(str(Path(library_root).resolve()))
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def migrate_path_metadata(conn: sqlite3.Connection, thumb_dir: Path,
                          old_path: str | Path, new_path: str | Path):
    """Move metadata between paths using explicit library-owned resources."""
    old = str(Path(old_path).resolve())
    new = str(Path(new_path).resolve())
    if old == new:
        return
    old_prefix = old + os.sep

    def remap(path: str) -> str:
        if path == old:
            return new
        if path.startswith(old_prefix):
            return new + path[len(old):]
        return path

    escaped_prefix = old_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    with db_write_lock(conn):
        tag_rows = conn.execute(
            "SELECT file_path, tag FROM file_tags WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
            (old, escaped_prefix + "%"),
        ).fetchall()
        for path, tag in tag_rows:
            conn.execute(
                "INSERT OR IGNORE INTO file_tags (file_path, tag) VALUES (?,?)",
                (remap(path), tag),
            )
        if tag_rows:
            conn.execute(
                "DELETE FROM file_tags WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
                (old, escaped_prefix + "%"),
            )

        meta_rows = conn.execute(
            "SELECT file_path, notes, cached_size, cached_mtime, cached_file_count, urls "
            "FROM file_meta WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
            (old, escaped_prefix + "%"),
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
        if meta_rows:
            conn.execute(
                "DELETE FROM file_meta WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
                (old, escaped_prefix + "%"),
            )

        thumb_rows = conn.execute(
            "SELECT cache_key, source_path FROM thumbnail_cache "
            "WHERE source_path=? OR source_path LIKE ? ESCAPE '\\'",
            (old, escaped_prefix + "%"),
        ).fetchall()
        for old_key, source_path in thumb_rows:
            mapped = remap(source_path)
            new_key = _thumbnail_cache_key(mapped)
            old_file = thumb_dir / f"{old_key}.webp"
            new_file = thumb_dir / f"{new_key}.webp"
            if old_file.exists() and old_key != new_key:
                try:
                    if new_file.exists():
                        old_file.unlink()
                    else:
                        old_file.replace(new_file)
                except OSError:
                    pass
            conn.execute(
                "UPDATE OR REPLACE thumbnail_cache SET cache_key=?, source_path=? "
                "WHERE cache_key=?",
                (new_key, mapped, old_key),
            )
        conn.commit()


def migrate_path_metadata_for_library(library_root: str | Path,
                                      old_path: str | Path, new_path: str | Path) -> None:
    """Legacy root-based compatibility wrapper for path metadata migration."""
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


def close_all_dbs():
    """Deprecated compatibility shutdown helper."""
    ThreadSafeSingleton.get(DatabaseManager).close()


def clean_orphan_dirs(known_roots: list[str]):
    DatabaseManager.clean_orphan_dirs(known_roots)


def get_library_stats(library_root: str):
    conn = ThreadSafeSingleton.get(DatabaseManager).connection_for(library_root)
    row = conn.execute(
        "SELECT total_size, total_files, total_projects FROM library_stats WHERE library_path = ?",
        (str(Path(library_root).resolve()),)
    ).fetchone()
    if row:
        return {"total_size": row[0], "total_files": row[1], "total_projects": row[2]}
    return {"total_size": 0, "total_files": 0, "total_projects": 0}
