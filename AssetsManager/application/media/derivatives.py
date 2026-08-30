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

Lifecycle (migration v41): rows carry ``status`` ('ready' | 'failed'),
``error_code`` and ``invalidated_at``. :meth:`record` keeps the ready
semantics (a recorded row is fresh and live), :meth:`mark_failed` flags an
existing row whose regeneration failed, and :meth:`invalidate` soft-retires
stale rows (payload deleted, row kept). The read side (:meth:`lookup`,
:meth:`payload_path`, :meth:`list_ready`) only serves rows that are
``status='ready'`` AND ``invalidated_at IS NULL``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
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

#: Derivative lifecycle states (migration v41). This whitelist — not the
#: database CHECK — is the source of truth for enum evolution: a future async
#: generator adds 'pending'/'generating' here first and appends them to the
#: v41 CHECK only via a dedicated migration, so the value set is never
#: encoded speculatively into a constraint that SQLite can only change by
#: rebuilding the table.
DERIVATIVE_STATUSES: frozenset[str] = frozenset({"ready", "failed"})

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


@dataclass(frozen=True)
class MediaDerivative:
    """One registered ``asset_derivatives`` row (read-side view).

    ``rel_path`` is the POSIX-slashed payload location under the derivatives
    root; ``""`` for params-only rows (recorded with ``payload=False``) that
    have no file on disk. ``params`` is the parsed JSON mapping (``{}`` when
    the stored JSON is absent or unparsable).
    """

    file_path: str
    kind: str
    rel_path: str
    params: dict[str, object]
    source_mtime: float | None
    created_at: float


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
        payload: bool = True,
    ) -> None:
        """Write one derivative payload and upsert its registry row.

        The payload is ``source_bytes`` verbatim, or a copy of ``source_file``
        when no bytes are given. With the default ``payload=True`` exactly one
        of the two must be provided; otherwise the call is a no-op (a row
        without its payload would break the "every registered derivative
        exists on disk" invariant). ``payload=False`` records a params-only
        row (``rel_path=""``, nothing on disk) for derivatives that live
        entirely in their ``params`` JSON — e.g. the extracted palette — and
        ignores ``source_bytes``/``source_file``. Passing ``data_dir``
        overrides the constructor-injected directory.

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
                payload=payload,
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
        payload: bool,
    ) -> None:
        if kind not in DERIVATIVE_KINDS:
            _log.warning(
                "Unknown media derivative kind %r for %s; not registered",
                kind,
                file_path,
            )
            return
        if payload and source_bytes is None and source_file is None:
            _log.warning(
                "Media derivative %s for %s has no payload (source_bytes or "
                "source_file required); not registered",
                kind,
                file_path,
            )
            return

        base = Path(data_dir) if data_dir is not None else self._data_dir
        path_key = self._path_key(file_path)
        rel_path = self._rel_path(path_key, kind, _normalize_ext(ext)) if payload else ""
        conn = self._connection_provider()
        if conn is None:
            return
        if payload:
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
                "(file_path, kind, rel_path, params, source_mtime, created_at, "
                "status, error_code, invalidated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'ready', NULL, NULL) "
                "ON CONFLICT(file_path, kind) DO UPDATE SET "
                "rel_path=excluded.rel_path, params=excluded.params, "
                "source_mtime=excluded.source_mtime, created_at=excluded.created_at, "
                "status='ready', error_code=NULL, invalidated_at=NULL",
                (
                    path_key,
                    kind,
                    rel_path,
                    json.dumps(dict(params or {}), ensure_ascii=False, sort_keys=True),
                    source_mtime,
                    time(),
                ),
            )
        if stale_rel_path and stale_rel_path != rel_path:
            # Extension changed between generations (or a payload row was
            # downgraded to params-only): drop the stale payload so the
            # derivatives tree never accumulates orphaned variants.
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
            if not rel_path:
                # Params-only rows have no payload file on disk.
                continue
            _resolve_target(base, str(rel_path)).unlink(missing_ok=True)

    # ── Lifecycle (migration v41) ────────────────────────────────────

    def mark_failed(self, file_path: str | Path, kind: str, error_code: str) -> None:
        """Flag an EXISTING registry row as failed; never raises, never inserts.

        ``UPDATE``-only by design: a generation attempt for an asset that has
        no row yet stays rowless (the pre-v41 behavior), so failure rows can
        never pollute ``list_ready``/``lookup`` results — those queries are
        the "already computed" signal for the retry paths. A later successful
        :meth:`record` resets the row to ready.
        """
        try:
            self._mark_failed(file_path, kind, error_code)
        except Exception:
            _log.warning(
                "Media derivative failure marking failed for kind=%s path=%s",
                kind,
                file_path,
                exc_info=True,
            )

    def _mark_failed(self, file_path: str | Path, kind: str, error_code: str) -> None:
        if kind not in DERIVATIVE_KINDS:
            return
        conn = self._connection_provider()
        if conn is None:
            return
        path_key = self._path_key(file_path)
        with self._write_scope(conn, "mark_failed") as scope:
            scope.execute(
                "UPDATE asset_derivatives SET status='failed', error_code=? "
                "WHERE file_path=? AND kind=?",
                (str(error_code or "unknown")[:128], path_key, kind),
            )

    def invalidate(
        self,
        file_path: str | Path,
        kind: str | None = None,
        *,
        data_dir: str | Path | None = None,
    ) -> None:
        """Soft-retire derivative rows: stamp ``invalidated_at``, drop payloads.

        A derivative judged stale (e.g. by the ``source_mtime`` comparison in
        ``analysis.py``) is retired instead of deleted: the payload file goes,
        but the row stays with ``invalidated_at=now`` so the read side — which
        only serves ``invalidated_at IS NULL`` rows — stops using it while the
        row remains observable for diagnostics. With ``kind`` only that
        derivative is retired; with ``kind=None`` every derivative of the
        asset is. Never raises; files already gone are not an error.
        """
        try:
            self._invalidate(file_path, kind, data_dir)
        except Exception:
            _log.warning(
                "Media derivative invalidation failed for kind=%s path=%s",
                kind,
                file_path,
                exc_info=True,
            )

    def _invalidate(
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
            if kind not in DERIVATIVE_KINDS:
                return
            rows = conn.execute(
                "SELECT rel_path FROM asset_derivatives "
                "WHERE file_path=? AND kind=?",
                (path_key, kind),
            ).fetchall()
        with self._write_scope(conn, "invalidate") as scope:
            if kind is None:
                scope.execute(
                    "UPDATE asset_derivatives SET invalidated_at=? "
                    "WHERE file_path=? AND invalidated_at IS NULL",
                    (time(), path_key),
                )
            else:
                scope.execute(
                    "UPDATE asset_derivatives SET invalidated_at=? "
                    "WHERE file_path=? AND kind=? AND invalidated_at IS NULL",
                    (time(), path_key, kind),
                )
        for (rel_path,) in rows:
            if not rel_path:
                # Params-only rows have no payload file on disk.
                continue
            _resolve_target(base, str(rel_path)).unlink(missing_ok=True)

    # ── Read side ────────────────────────────────────────────────────

    def lookup(
        self,
        file_path: str | Path,
        kind: str,
    ) -> MediaDerivative | None:
        """Return the asset's registered row for *kind*, or ``None``.

        The row's existence is the "already computed once" signal for the
        on-demand analysis passes (waveform, palette): consumers must skip
        regeneration whenever this returns a row, even a params-only one.
        Only rows fit to serve are visible — ``status='ready'`` AND
        ``invalidated_at IS NULL`` — so failed and soft-retired rows keep the
        retry paths regenerating instead of trusting stale state. Mirrors the
        write-side contract: failures are logged and swallowed.
        """
        try:
            return self._lookup(file_path, kind)
        except Exception:
            _log.warning(
                "Media derivative lookup failed for kind=%s path=%s",
                kind,
                file_path,
                exc_info=True,
            )
            return None

    def _lookup(
        self,
        file_path: str | Path,
        kind: str,
    ) -> MediaDerivative | None:
        if kind not in DERIVATIVE_KINDS:
            return None
        conn = self._connection_provider()
        if conn is None:
            return None
        path_key = self._path_key(file_path)
        row = conn.execute(
            "SELECT rel_path, params, source_mtime, created_at "
            "FROM asset_derivatives "
            "WHERE file_path=? AND kind=? "
            "AND status='ready' AND invalidated_at IS NULL",
            (path_key, kind),
        ).fetchone()
        if row is None:
            return None
        try:
            params = json.loads(row[1]) if row[1] else {}
            if not isinstance(params, dict):
                params = {}
        except (TypeError, ValueError):
            params = {}
        return MediaDerivative(
            file_path=path_key,
            kind=kind,
            rel_path=str(row[0]),
            params=params,
            source_mtime=row[2],
            created_at=row[3],
        )

    def list_ready(
        self,
        file_path: str | Path | None = None,
        kind: str | None = None,
    ) -> list[MediaDerivative]:
        """List registry rows fit to serve; never raises (errors log, empty).

        Fit to serve means ``status='ready'`` AND ``invalidated_at IS NULL`` —
        failed rows and soft-retired (stale) rows are invisible here. With
        ``file_path`` the list narrows to one asset, with ``kind`` to one
        derivative kind; both filters may combine or be omitted.
        """
        try:
            return self._list_ready(file_path, kind)
        except Exception:
            _log.warning(
                "Media derivative listing failed for kind=%s path=%s",
                kind,
                file_path,
                exc_info=True,
            )
            return []

    def _list_ready(
        self,
        file_path: str | Path | None,
        kind: str | None,
    ) -> list[MediaDerivative]:
        if kind is not None and kind not in DERIVATIVE_KINDS:
            return []
        conn = self._connection_provider()
        if conn is None:
            return []
        clauses = ["status='ready'", "invalidated_at IS NULL"]
        parameters: list[object] = []
        if file_path is not None:
            clauses.append("file_path=?")
            parameters.append(self._path_key(file_path))
        if kind is not None:
            clauses.append("kind=?")
            parameters.append(kind)
        rows = conn.execute(
            "SELECT file_path, kind, rel_path, params, source_mtime, created_at "
            "FROM asset_derivatives WHERE " + " AND ".join(clauses) +
            " ORDER BY file_path, kind",
            tuple(parameters),
        ).fetchall()
        derivatives: list[MediaDerivative] = []
        for row in rows:
            try:
                params = json.loads(row[3]) if row[3] else {}
                if not isinstance(params, dict):
                    params = {}
            except (TypeError, ValueError):
                params = {}
            derivatives.append(
                MediaDerivative(
                    file_path=str(row[0]),
                    kind=str(row[1]),
                    rel_path=str(row[2]),
                    params=params,
                    source_mtime=row[4],
                    created_at=row[5],
                )
            )
        return derivatives

    def payload_path(
        self,
        file_path: str | Path,
        kind: str,
        *,
        data_dir: str | Path | None = None,
    ) -> Path | None:
        """Return the derivative's payload file when it exists on disk.

        ``None`` for params-only rows (``rel_path=""``) and for rows whose
        payload vanished (self-healing: the caller regenerates and
        re-registers instead of serving a dangling row).
        """
        found = self.lookup(file_path, kind)
        if found is None or not found.rel_path:
            return None
        base = Path(data_dir) if data_dir is not None else self._data_dir
        target = _resolve_target(base, found.rel_path)
        return target if target.is_file() else None
