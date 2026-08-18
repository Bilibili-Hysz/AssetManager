"""ProjectData — per-library metadata via SQLite (one DB per library)."""
import json
import logging
import os
import re
import time
import warnings
from pathlib import Path
from sqlite3 import Connection
from typing import Callable

from AssetsManager.core.database import DatabaseManager, db_write_lock
from AssetsManager.core.path_resolver import sql_like_descendant_pattern

logger = logging.getLogger(__name__)

# Directory mtime does not change when a file's content is modified in place,
# so the persisted cache is only trusted for this window after (re)computation.
_SIZE_CACHE_TTL_SECONDS = 30.0

# Traversal budget for compute_dir_size, matching the gallery walk limit
# (gallery_service.max_depth = 64). Subtrees below the limit are omitted so a
# pathologically deep tree cannot exhaust the recursion stack.
_MAX_SIZE_DEPTH = 64


class ProjectData:
    def __init__(
        self,
        library_root: str,
        db_conn: Connection | None = None,
        *,
        session=None,
    ):
        self._root = str(Path(library_root).resolve())
        self._liveness = None
        self._session = None
        self._size_cache_ts: dict[str, float] = {}
        if session is not None and db_conn is None:
            self._db = session.connection_for(self._root)
        elif db_conn is None:
            raise TypeError(f"{type(self).__name__} requires db_conn or a LibrarySession")
        else:
            # Legacy constructor: preserve compatibility with caller-owned raw connections.
            self._db = DatabaseManager.validate_connection_owner(
                self._root, db_conn, allow_unmanaged=True
            )
        if session is not None:
            self._bind_session(session)

    def _bind_liveness(self, liveness) -> None:
        self._liveness = liveness

    def _bind_session(self, session) -> None:
        if self._session is not None and self._session is not session:
            raise RuntimeError("ProjectData is already bound to another LibrarySession")
        session_connection = session.connection_for(self._root)
        if session_connection is not self._db:
            raise ValueError("ProjectData connection does not belong to the LibrarySession")
        self._session = session
        session_liveness = getattr(getattr(session, "context", None), "_liveness", None)
        if session_liveness is not None:
            self._liveness = session_liveness

    def _ensure_live(self) -> None:
        if self._liveness is not None:
            self._liveness.ensure_live()

    def _key(self, path: str) -> str:
        # Deliberately NOT os.path.normcase'd: MetadataRepository — the
        # primary file_meta access path — keys rows with
        # str(Path(...).resolve()) (no case folding). normcase would
        # lowercase the drive letter (C:\ vs c:\), stranding rows written by
        # MetadataService and breaking cross-component reads on Windows.
        # Case dedup for existing files is already provided by
        # Path.resolve(), which canonicalizes to the on-disk case on
        # Windows; only non-existent paths keep their typed case (transient
        # rows, swept by prune_missing()).
        return str(Path(path).resolve())

    # ── Notes ────────────────────────────────────────────────────

    def get_notes(self, path: str) -> str:
        self._ensure_live()
        row = self._db.execute(
            "SELECT notes FROM file_meta WHERE file_path=?", (self._key(path),)
        ).fetchone()
        return row[0] if row else ""

    def set_notes(self, path: str, text: str):
        self._ensure_live()
        key = self._key(path)
        text = text.strip()
        with db_write_lock(self._db):
            if text:
                self._db.execute(
                    "INSERT INTO file_meta (file_path, notes) VALUES (?,?) "
                    "ON CONFLICT(file_path) DO UPDATE SET notes=excluded.notes",
                    (key, text))
            else:
                self._db.execute(
                    "UPDATE file_meta SET notes='' WHERE file_path=?", (key,))
            self._db.commit()

    def has_notes(self, path: str) -> bool:
        self._ensure_live()
        row = self._db.execute(
            "SELECT notes FROM file_meta WHERE file_path=? AND notes!=''",
            (self._key(path),)
        ).fetchone()
        return row is not None

    # ── URLs ─────────────────────────────────────────────────────

    _url_pattern = re.compile(r'^https?://', re.IGNORECASE)

    def get_urls(self, path: str) -> list[str]:
        self._ensure_live()
        row = self._db.execute(
            "SELECT urls FROM file_meta WHERE file_path=?",
            (self._key(path),)
        ).fetchone()
        if not row:
            return []
        try:
            parsed = json.loads(row[0] or "[]")
        except json.JSONDecodeError:
            return []
        # Defend against rows carrying a valid JSON non-list payload (e.g. a
        # dict written by an older version): add_url/remove_url would call
        # append/remove on it and raise AttributeError.
        if not isinstance(parsed, list):
            logger.debug(
                "file_meta.urls for %r is not a JSON list (%r); treating as empty",
                self._key(path), row[0],
            )
            return []
        return parsed

    def add_url(self, path: str, url: str):
        self._ensure_live()
        url = url.strip()
        if not self._url_pattern.match(url):
            raise ValueError(f"URL must start with http:// or https://: {url}")
        with db_write_lock(self._db):
            urls = self.get_urls(path)
            if url not in urls:
                urls.append(url)
                self._save_urls(path, urls)

    def remove_url(self, path: str, url: str):
        self._ensure_live()
        with db_write_lock(self._db):
            urls = self.get_urls(path)
            if url in urls:
                urls.remove(url)
                self._save_urls(path, urls)

    def _save_urls(self, path: str, urls: list[str]):
        key = self._key(path)
        data = json.dumps(urls, ensure_ascii=False)
        with db_write_lock(self._db):
            self._db.execute(
                "INSERT INTO file_meta (file_path, urls) VALUES (?,?) "
                "ON CONFLICT(file_path) DO UPDATE SET urls=excluded.urls",
                (key, data))
            self._db.commit()

    # ── Directory size cache ─────────────────────────────────────

    # Cooperative cancellation is polled once per this many entries so the
    # check itself stays negligible while a cancelled walk still exits within
    # milliseconds on typical directories.
    _SIZE_CANCEL_CHECK_INTERVAL = 100

    @staticmethod
    def compute_dir_size(
        dir_path: str,
        _depth: int = 0,
        cancel_token: Callable[[], bool] | None = None,
    ) -> int:
        """Walk ``dir_path`` summing file sizes, with cooperative cancellation.

        When *cancel_token* starts returning True the walk stops and the
        accumulated partial total is returned.  Callers that write the result
        into a cache must re-check the token first — a partial total must
        never be persisted as an authoritative size.
        """
        total = 0
        try:
            for index, entry in enumerate(os.scandir(dir_path)):
                if (
                    cancel_token is not None
                    and index % ProjectData._SIZE_CANCEL_CHECK_INTERVAL == 0
                    and cancel_token()
                ):
                    return total
                try:
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat(follow_symlinks=False).st_size
                    elif entry.is_dir(follow_symlinks=False):
                        # Depth budget: count files at this level but do not
                        # descend below _MAX_SIZE_DEPTH (avoids RecursionError
                        # on pathologically deep trees). Sizes beyond the
                        # budget are omitted, not double-counted.
                        if _depth < _MAX_SIZE_DEPTH:
                            total += ProjectData.compute_dir_size(
                                entry.path, _depth + 1, cancel_token=cancel_token
                            )
                except OSError:
                    pass
        except OSError:
            pass
        return total

    def get_dir_size(
        self,
        dir_path: str,
        force: bool = False,
        cancel_token: Callable[[], bool] | None = None,
    ) -> tuple[int, bool]:
        self._ensure_live()
        if not os.path.isdir(dir_path):
            return (0, False)
        key = self._key(dir_path)
        if not force:
            row = self._db.execute(
                "SELECT cached_size, cached_mtime FROM file_meta WHERE file_path=?",
                (key,)
            ).fetchone()
            if row and row[0] is not None and row[1] is not None:
                try:
                    current_mtime = os.path.getmtime(dir_path)
                except OSError:
                    return (0, False)
                computed_at = self._size_cache_ts.get(key)
                ttl_fresh = (
                    computed_at is not None
                    and time.time() - computed_at < _SIZE_CACHE_TTL_SECONDS
                )
                # Exact mtime match (not >=): any drift — even a backwards
                # clock skew — invalidates the cache. Directory mtime only
                # tracks child add/remove; in-place content edits leave it
                # untouched and may return a stale size inside the TTL window
                # (accepted, bounded by _SIZE_CACHE_TTL_SECONDS).
                if row[1] == current_mtime and ttl_fresh:
                    return (row[0], True)
        size = self.compute_dir_size(dir_path, cancel_token=cancel_token)
        if cancel_token is not None and cancel_token():
            # A cancelled walk returned a partial total; persisting it would
            # poison the cache with an undercount until the TTL expires.
            return (size, False)
        self._set_cached_size(dir_path, size)
        return (size, False)

    def _set_cached_size(self, path: str, size: int):
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return
        with db_write_lock(self._db):
            self._db.execute(
                "INSERT INTO file_meta (file_path, cached_size, cached_mtime) VALUES (?,?,?) "
                "ON CONFLICT(file_path) DO UPDATE SET cached_size=excluded.cached_size, cached_mtime=excluded.cached_mtime",
                (self._key(path), size, mtime))
            self._db.commit()
        self._size_cache_ts[self._key(path)] = time.time()

    def invalidate_size_cache(self, dir_path: str):
        self._ensure_live()
        prefix = self._key(dir_path)
        descendant_pattern = sql_like_descendant_pattern(prefix)
        with db_write_lock(self._db):
            self._db.execute(
                "UPDATE file_meta SET cached_size=NULL, cached_mtime=NULL, cached_file_count=NULL "
                "WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
                (prefix, descendant_pattern))
            self._db.commit()

    def prune_missing(self):
        self._ensure_live()
        rows = self._db.execute("SELECT file_path FROM file_meta").fetchall()
        removed = 0
        with db_write_lock(self._db):
            for (path,) in rows:
                if not os.path.exists(path):
                    self._db.execute("DELETE FROM file_meta WHERE file_path=?", (path,))
                    removed += 1
            if removed:
                self._db.commit()


def get_project_data(library_root: str, db_conn: Connection | None = None) -> ProjectData:
    """Deprecated compatibility constructor without global store retention."""
    warnings.warn("get_project_data() is deprecated, use ProjectDataService instead", DeprecationWarning, stacklevel=2)
    return ProjectData(str(Path(library_root).resolve()), db_conn=db_conn)
