"""AssetManager database — unified SQLite persistence layer with lifecycle manager.

Provides:
- Per-library SQLite connections with WAL mode
- Schema initialization (file_tags, file_meta, thumbnail_cache)
- Thread-safe connection management
"""
from contextlib import contextmanager
import hashlib
import os
import shutil
import sqlite3
import threading
from pathlib import Path

from AssetsManager.core.path_resolver import (
    runtime_root, shared_dir, library_data_dir, library_data_name,
    legacy_library_data_dir, thumb_dir,
    favorites_path, recent_path, db_path,
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
"""


class DatabaseManager:
    """App-level manager for all library data. Singleton via get_manager()."""

    def __init__(self):
        self._connections: dict[str, sqlite3.Connection] = {}
        self._current_key: str = ""
        self._current_root: str = ""
        self._write_lock = threading.RLock()

    def open_library(self, root_path: str):
        with self._write_lock:
            key = str(Path(root_path).resolve())
            if key == self._current_key:
                return
            self._current_key = key
            self._current_root = key

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
        with self._write_lock:
            for conn in self._connections.values():
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
            self._connections.clear()
            self._current_key = ""
            self._current_root = ""

    @property
    def data_dir(self) -> Path:
        return library_data_dir(self._current_root)

    @property
    def thumb_dir(self) -> Path:
        return thumb_dir(self._current_root)

    @property
    def db_conn(self) -> sqlite3.Connection | None:
        return self._connections.get(self._current_key)

    def favorites_path(self) -> Path:
        return favorites_path(self._current_root)

    def recent_path(self) -> Path:
        return recent_path(self._current_root)

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
        for entry in RUNTIME_ROOT.iterdir():
            if entry.is_dir() and entry.name != "Shared" and entry.name not in known_names:
                try:
                    shutil.rmtree(str(entry), ignore_errors=True)
                except OSError:
                    pass


# ── Singleton ─────────────────────────────────────────────────────

def get_manager() -> DatabaseManager:
    """Deprecated: use ApplicationBootstrap.resolve(DatabaseManager) instead."""
    import warnings
    warnings.warn("get_manager() is deprecated", DeprecationWarning, stacklevel=2)
    return ThreadSafeSingleton.get(DatabaseManager)


@contextmanager
def db_write_lock():
    """Return the process-wide database write lock context."""
    with get_manager().write_lock():
        yield


# ── Legacy API (backward-compatible) ──────────────────────────────

def get_lib_db(library_root: str) -> sqlite3.Connection:
    return get_manager().connection_for(library_root)


def get_library_dir(library_root: str) -> Path:
    return get_manager().data_dir_for(library_root)


def migrate_path_metadata(library_root: str, old_path: str, new_path: str):
    """Move DB metadata from old_path to new_path, including children for directories."""
    old = str(Path(old_path).resolve())
    new = str(Path(new_path).resolve())
    if old == new:
        return
    conn = get_lib_db(library_root)
    old_prefix = old + os.sep
    mgr = get_manager()
    thumbs = mgr.thumb_dir_for(library_root)

    def remap(path: str) -> str:
        if path == old:
            return new
        if path.startswith(old_prefix):
            return new + path[len(old):]
        return path

    escaped_prefix = old_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    with db_write_lock():
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
            old_file = thumbs / f"{old_key}.webp"
            new_file = thumbs / f"{new_key}.webp"
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


def _thumbnail_cache_key(path: str) -> str:
    try:
        mtime = str(os.path.getmtime(path))
    except OSError:
        mtime = ""
    return hashlib.sha256(f"{path}|{mtime}".encode()).hexdigest()[:16]


def close_all_dbs():
    get_manager().close()


def clean_orphan_dirs(known_roots: list[str]):
    DatabaseManager.clean_orphan_dirs(known_roots)


# ── Library statistics ─────────────────────────────────────────

def update_library_stats(library_root: str, total_size: int = 0,
                         total_files: int = 0, total_projects: int = 0):
    conn = get_lib_db(library_root)
    with db_write_lock():
        conn.execute(
            "INSERT OR REPLACE INTO library_stats (library_path, total_size, total_files, total_projects, updated_at) "
            "VALUES (?, ?, ?, ?, strftime('%s','now'))",
            (str(Path(library_root).resolve()), total_size, total_files, total_projects))
        conn.commit()


def get_library_stats(library_root: str):
    conn = get_lib_db(library_root)
    row = conn.execute(
        "SELECT total_size, total_files, total_projects FROM library_stats WHERE library_path = ?",
        (str(Path(library_root).resolve()),)
    ).fetchone()
    if row:
        return {"total_size": row[0], "total_files": row[1], "total_projects": row[2]}
    return {"total_size": 0, "total_files": 0, "total_projects": 0}
