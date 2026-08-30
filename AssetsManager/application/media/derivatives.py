"""Media derivative write side — registry rows plus payload files.

One place that both materializes a regenerable derivative under
``<data_dir>/derivatives/<kind>/`` and upserts its ``asset_derivatives`` row
(migration v37). ``file_path`` is the absolute library-asset key in the
``file_meta`` style (resolved path, no normcase); the on-disk name is
``sha1(path_key)`` so hostile asset names can never escape the derivatives
directory, with an optional caller-chosen extension.

Contract (mirrors ``activity_recorder.py``): derivatives are regenerable
value-adds, never facts, so a recording or clearing failure is logged and
swallowed — it must never fail or delay the operation that produced it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from contextlib import contextmanager
from pathlib import Path
from sqlite3 import Connection
from time import monotonic_ns, time
from typing import Callable, Iterator, Mapping

from AssetsManager.core.database import db_write_lock

_log = logging.getLogger(__name__)

#: Registered derivative kinds — must match the ``asset_derivatives`` CHECK
#: constraint from migration v37. A new kind needs a migration first.
DERIVATIVE_KINDS: frozenset[str] = frozenset(
    {
        "viewer_image",
        "video_poster",
        "contact_sheet",
        "audio_waveform",
        "extracted_palette",
        "sequence_manifest",
    }
)

_DERIVATIVES_DIR_NAME = "derivatives"


def derivatives_root(data_dir: str | Path) -> Path:
    """Return the per-library derivative storage root ``<data_dir>/derivatives``."""
    return Path(data_dir) / _DERIVATIVES_DIR_NAME


def _normalize_ext(ext: str) -> str:
    """Normalize an optional filename extension to the ``.png`` spelling."""
    ext = ext.strip()
    if ext and not ext.startswith("."):
        ext = f".{ext}"
    return ext


def _resolve_target(data_dir: Path, rel_path: str) -> Path:
    # rel_path is stored POSIX-slashed; rebuild it segment-wise so the join
    # stays native on every platform.
    return derivatives_root(data_dir).joinpath(*rel_path.split("/"))


class MediaDerivativesRecorder:
    """Persist media derivatives and register them in ``asset_derivatives``.

    Binds one library: a connection provider into the per-library session
    (same seam as ``ActivityRecorder``) and the library's data directory, so
    payloads land in ``<data_dir>/derivatives/<kind>/<sha1><ext>`` while rows
    go into that library's ``asset_derivatives`` table.
    """

    def __init__(
        self,
        connection_provider: Callable[[], Connection | None],
        data_dir: str | Path,
    ) -> None:
        self._connection_provider = connection_provider
        self._data_dir = Path(data_dir)

    @property
    def data_dir(self) -> Path:
        """The library data directory payloads are written under."""
        return self._data_dir

    def _path_key(self, file_path: str | Path) -> str:
        # file_meta key style: absolute resolved path, no normcase (a
        # normcase would lowercase drive letters on Windows and strand rows
        # written by the other components).
        return str(Path(file_path).resolve())

    def _rel_path(self, path_key: str, kind: str, ext: str) -> str:
        digest = hashlib.sha1(path_key.encode("utf-8")).hexdigest()
        return f"{kind}/{digest}{ext}"

    @contextmanager
    def _write_scope(self, conn: Connection, operation: str) -> Iterator[Connection]:
        """Commit raw writes, but preserve caller transactions when open."""
        with db_write_lock(conn):
            outer_transaction = conn.in_transaction
            savepoint = f"media_derivatives_{operation}_{monotonic_ns():x}"
            conn.execute(f"SAVEPOINT {savepoint}")
            try:
                yield conn
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            except BaseException:
                conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            if not outer_transaction:
                conn.commit()

    def record(
        self,
        file_path: str | Path,
        kind: str,
        source_bytes: bytes | None = None,
        *,
        params: Mapping[str, object] | None = None,
        data_dir: str | Path | None = None,
        source_mtime: float | None = None,
        ext: str = "",
        source_file: str | Path | None = None,
    ) -> None:
        """Write one derivative payload and upsert its registry row.

        The payload is ``source_bytes`` verbatim, or a copy of ``source_file``
        when no bytes are given. Exactly one of the two must be provided;
        otherwise the call is a no-op (a row without its payload would break
        the "every registered derivative exists on disk" invariant). Passing
        ``data_dir`` overrides the constructor-injected directory.

        Re-recording the same (asset, kind) overwrites the file and the row;
        if the extension changed between generations the stale payload file
        is removed. Never raises.
        """
        try:
            self._record(
                file_path,
                kind,
                source_bytes,
                params=params,
                data_dir=data_dir,
                source_mtime=source_mtime,
                ext=ext,
                source_file=source_file,
            )
        except Exception:
            # Derivative bookkeeping must never affect the producing operation.
            _log.warning(
                "Media derivative recording failed for kind=%s path=%s",
                kind,
                file_path,
                exc_info=True,
            )

    def _record(
        self,
        file_path: str | Path,
        kind: str,
        source_bytes: bytes | None,
        *,
        params: Mapping[str, object] | None,
        data_dir: str | Path | None,
        source_mtime: float | None,
        ext: str,
        source_file: str | Path | None,
    ) -> None:
        if kind not in DERIVATIVE_KINDS:
            _log.warning(
                "Unknown media derivative kind %r for %s; not registered",
                kind,
                file_path,
            )
            return
        if source_bytes is None and source_file is None:
            _log.warning(
                "Media derivative %s for %s has no payload (source_bytes or "
                "source_file required); not registered",
                kind,
                file_path,
            )
            return

        base = Path(data_dir) if data_dir is not None else self._data_dir
        path_key = self._path_key(file_path)
        rel_path = self._rel_path(path_key, kind, _normalize_ext(ext))
        conn = self._connection_provider()
        if conn is None:
            return
        target = _resolve_target(base, rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source_bytes is not None:
            target.write_bytes(source_bytes)
        else:
            shutil.copyfile(source_file, target)

        with self._write_scope(conn, "record") as scope:
            row = scope.execute(
                "SELECT rel_path FROM asset_derivatives "
                "WHERE file_path=? AND kind=?",
                (path_key, kind),
            ).fetchone()
            stale_rel_path = str(row[0]) if row is not None else None
            scope.execute(
                "INSERT INTO asset_derivatives "
                "(file_path, kind, rel_path, params, source_mtime, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(file_path, kind) DO UPDATE SET "
                "rel_path=excluded.rel_path, params=excluded.params, "
                "source_mtime=excluded.source_mtime, created_at=excluded.created_at",
                (
                    path_key,
                    kind,
                    rel_path,
                    json.dumps(dict(params or {}), ensure_ascii=False, sort_keys=True),
                    source_mtime,
                    time(),
                ),
            )
        if stale_rel_path is not None and stale_rel_path != rel_path:
            # Extension changed between generations: drop the stale payload
            # so the derivatives tree never accumulates orphaned variants.
            _resolve_target(base, stale_rel_path).unlink(missing_ok=True)

    def clear(
        self,
        file_path: str | Path,
        kind: str | None = None,
        *,
        data_dir: str | Path | None = None,
    ) -> None:
        """Delete derivative payloads and their registry rows; never raises.

        With ``kind`` only that derivative is removed; with ``kind=None`` all
        registered derivatives of the asset go (asset removal). Files already
        gone from disk are not an error.
        """
        try:
            self._clear(file_path, kind, data_dir)
        except Exception:
            _log.warning(
                "Media derivative clearing failed for kind=%s path=%s",
                kind,
                file_path,
                exc_info=True,
            )

    def _clear(
        self,
        file_path: str | Path,
        kind: str | None,
        data_dir: str | Path | None,
    ) -> None:
        base = Path(data_dir) if data_dir is not None else self._data_dir
        path_key = self._path_key(file_path)
        conn = self._connection_provider()
        if conn is None:
            return
        if kind is None:
            rows = conn.execute(
                "SELECT rel_path FROM asset_derivatives WHERE file_path=?",
                (path_key,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT rel_path FROM asset_derivatives "
                "WHERE file_path=? AND kind=?",
                (path_key, kind),
            ).fetchall()
        with self._write_scope(conn, "clear") as scope:
            if kind is None:
                scope.execute(
                    "DELETE FROM asset_derivatives WHERE file_path=?",
                    (path_key,),
                )
            else:
                scope.execute(
                    "DELETE FROM asset_derivatives WHERE file_path=? AND kind=?",
                    (path_key, kind),
                )
        for (rel_path,) in rows:
            _resolve_target(base, str(rel_path)).unlink(missing_ok=True)
