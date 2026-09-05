"""Persistence access for the lazily populated assets index."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import re
import time
from contextlib import contextmanager
from pathlib import Path
from sqlite3 import Connection, IntegrityError, OperationalError
from typing import Any

from AssetsManager.core.database import DatabaseManager, db_write_lock
from AssetsManager.core.path_resolver import (
    RootIdentity,
    root_identity,
    sql_like_descendant_pattern,
)
from AssetsManager.repositories._common import (
    _SessionBoundRepository,
    _repository_operation,
    _require_session_contract,
    _session_root,
)

_SAVEPOINT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Structured-search ORDER BY whitelist. Column names never come from user
# input directly; only these literals are interpolated into SQL. ``rating``
# reads the optional file_meta join (NULL unrated sorts as 0).
_STRUCTURED_ORDER_COLUMNS = {
    "name": "name",
    "size": "size",
    "mtime": "mtime",
    "rating": "COALESCE(file_meta.rating, 0)",
}


class AssetIndexRevisionConflict(RuntimeError):
    """Raised when a scan publishes against an obsolete root revision."""

    def __init__(self, library_root: str, expected: int, actual: int) -> None:
        self.library_root = library_root
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"Asset index revision conflict for {library_root}: "
            f"expected {expected}, found {actual}"
        )


@dataclass(frozen=True)
class AssetIndexEntry:
    file_path: str
    name: str
    extension: str
    kind: str
    size: int
    mtime: float
    parent_path: str
    library_root: str


class AssetIndexRepository(_SessionBoundRepository):
    """Encapsulate SQL access to the ``assets`` index table.

    ``AssetIndexRepository(conn)`` remains the explicit raw compatibility path.
    Canonical callers should use :meth:`for_session`, which binds connection
    ownership, root containment, operation lifetime, and close semantics to one
    real ``LibrarySession``.
    """

    def __init__(
        self,
        conn: Connection,
        *,
        library_root: str | Path | RootIdentity | None = None,
        session: Any | None = None,
    ):
        # Set before super().__init__ so the base's _apply_root_identity hook
        # can populate it on every binding path.
        self._root_identity: RootIdentity | None = None
        super().__init__(conn, library_root=library_root, session=session)

    def _apply_root_identity(self, identity: RootIdentity) -> None:
        super()._apply_root_identity(identity)
        self._root_identity = identity

    def _bind_session(
        self,
        session: Any,
        *,
        library_root: str | Path | RootIdentity | None = None,
    ) -> None:
        operation, connection_for = _require_session_contract(
            session, "AssetIndexRepository"
        )
        session_identity = _session_root(session, "AssetIndexRepository")
        if library_root is not None:
            explicit_identity = root_identity(library_root, strict=False)
            if explicit_identity.map_key != session_identity.map_key:
                raise ValueError(
                    "AssetIndexRepository library_root does not match the LibrarySession"
                )

        with self._binding_lock:
            if self._session is not None:
                if self._session is session:
                    return
                raise RuntimeError(
                    "AssetIndexRepository is already bound to another LibrarySession"
                )
            if self._raw_operation_started:
                raise RuntimeError(
                    "AssetIndexRepository cannot bind after raw operations have started"
                )
            if (
                self._library_root_key is not None
                and self._library_root_key != session_identity.map_key
            ):
                raise ValueError("AssetIndexRepository belongs to a different library root")

            with operation():
                conn = connection_for(session_identity)
                conn = DatabaseManager.require_managed_connection_owner(
                    session_identity, conn
                )
                if conn is not self._conn:
                    raise ValueError(
                        "AssetIndexRepository connection does not belong to the LibrarySession"
                    )

                def publish_binding() -> None:
                    self._apply_root_identity(session_identity)
                    self._session = session

                session._publish_while_live(publish_binding)

    def _root_key(self, library_root: str | Path | RootIdentity) -> str:
        if self._root_identity is None:
            return str(library_root)
        identity = root_identity(library_root, strict=False)
        if identity.map_key != self._root_identity.map_key:
            raise ValueError(
                "AssetIndexRepository library_root does not belong to the bound LibrarySession"
            )
        return str(self._root_identity.display_path)

    def _path_key(self, path: str | Path) -> str:
        """Return a canonical path and enforce bound-root containment."""
        if self._library_root is None:
            return str(path)
        target = Path(path).resolve()
        if not target.is_relative_to(self._library_root):
            raise ValueError(
                f"asset index path must be under library_root: {target} "
                f"(root {self._library_root})"
            )
        return str(target)


    def _entry_values(
        self,
        entries: list[tuple[str, str, str, str, int, float, str, str, float, float]],
    ) -> list[tuple[str, str, str, str, int, float, str, str, float, float]]:
        if self._root_identity is None:
            return entries
        normalized = []
        for entry in entries:
            file_path, name, extension, kind, size, mtime, parent_path, library_root, created, updated = entry
            normalized.append(
                (
                    self._path_key(file_path), name, extension, kind, size, mtime,
                    self._path_key(parent_path), self._root_key(library_root), created, updated,
                )
            )
        return normalized

    def _revision_root(
        self, library_root: str | Path | RootIdentity | None = None
    ) -> str | None:
        if library_root is None:
            if self._root_identity is None:
                return None
            return str(self._root_identity.display_path)
        return self._root_key(library_root)

    def _read_revision(self, library_root: str) -> int:
        row = self._conn.execute(
            "SELECT revision FROM asset_index_state WHERE library_root=?",
            (library_root,),
        ).fetchone()
        return int(row[0]) if row else 0

    @staticmethod
    def _validate_revision(revision: int | None) -> int | None:
        if revision is None:
            return None
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ValueError("asset index revision must be a non-negative integer")
        return revision

    def _advance_revision(
        self,
        library_root: str | Path | RootIdentity | None = None,
        *,
        expected: int | None = None,
    ) -> int | None:
        root_key = self._revision_root(library_root)
        if root_key is None:
            return None
        expected = self._validate_revision(expected)
        now = time.time()
        if expected is None:
            cur = self._conn.execute(
                "UPDATE asset_index_state SET revision=revision+1, updated_at=? "
                "WHERE library_root=?",
                (now, root_key),
            )
            if cur.rowcount == 0:
                try:
                    self._conn.execute(
                        "INSERT INTO asset_index_state "
                        "(library_root, revision, updated_at) VALUES (?, 1, ?)",
                        (root_key, now),
                    )
                    return 1
                except IntegrityError:
                    # A concurrent writer may have created the row between the
                    # UPDATE and INSERT. Re-read and continue with one strict
                    # revision transition rather than silently overwriting it.
                    pass
            return self._read_revision(root_key)

        cur = self._conn.execute(
            "UPDATE asset_index_state SET revision=revision+1, updated_at=? "
            "WHERE library_root=? AND revision=?",
            (now, root_key, expected),
        )
        if cur.rowcount == 1:
            return expected + 1
        if expected == 0:
            try:
                self._conn.execute(
                    "INSERT INTO asset_index_state "
                    "(library_root, revision, updated_at) VALUES (?, 1, ?)",
                    (root_key, now),
                )
                return 1
            except IntegrityError:
                pass
        raise AssetIndexRevisionConflict(
            root_key, expected, self._read_revision(root_key)
        )

    @_repository_operation
    def current_revision(
        self, library_root: str | Path | RootIdentity | None = None
    ) -> int:
        """Return the committed root revision, using zero for an unseen root."""
        root_key = self._revision_root(library_root)
        if root_key is None:
            raise TypeError("asset index revision requires a bound or explicit library root")
        return self._read_revision(root_key)

    def _matching_revision_roots(
        self, path: str, *, subtree: str | None = None
    ) -> tuple[str, ...]:
        """Find raw rows' roots so legacy deletes still advance revisions."""
        if self._root_identity is not None:
            return (str(self._root_identity.display_path),)
        if subtree is None:
            sql = "SELECT DISTINCT library_root FROM assets WHERE file_path=?"
            params = (path,)
        else:
            sql = (
                "SELECT DISTINCT library_root FROM assets WHERE "
                "file_path=? OR file_path LIKE ? ESCAPE '\\' "
                "OR parent_path=? OR parent_path LIKE ? ESCAPE '\\'"
            )
            params = (path, subtree, path, subtree)
        try:
            rows = self._conn.execute(sql, params).fetchall()
        except OperationalError as exc:
            if "no such table" in str(exc).lower():
                # Legacy raw databases may predate the revision table. Keep the
                # compatibility delete behavior; canonical migrated sessions do
                # not take this branch.
                return ()
            raise
        return tuple(sorted({str(row[0]) for row in rows if row[0] is not None}))

    @contextmanager
    def transaction_scope(
        self, *, commit: bool = True, savepoint: str | None = None
    ):
        """Own a repository-level transaction/savepoint with fail-closed cleanup."""
        with self._operation_scope():
            if savepoint is not None and not _SAVEPOINT_NAME.fullmatch(savepoint):
                raise ValueError("savepoint must be a simple SQLite identifier")
            outer_transaction = self._conn.in_transaction
            owns_transaction = not outer_transaction
            # An existing caller transaction always remains caller-owned.  The
            # raw compatibility path must not commit unrelated caller writes
            # merely because this repository has no bound session object.
            should_commit = commit and not outer_transaction
            with db_write_lock(self._conn):
                if savepoint is None:
                    commit_attempted = False
                    try:
                        yield
                        if should_commit:
                            commit_attempted = True
                            self._conn.commit()
                    except BaseException:
                        if (commit_attempted or owns_transaction) and self._conn.in_transaction:
                            try:
                                self._conn.rollback()
                            except BaseException:
                                pass
                        raise
                    return

                if not outer_transaction:
                    # An outermost SQLite SAVEPOINT commits when it is released.
                    # Start an explicit transaction first so the savepoint release
                    # remains rollbackable until the final commit below.
                    self._conn.execute("BEGIN")
                self._conn.execute(f"SAVEPOINT {savepoint}")
                active = True
                commit_attempted = False
                try:
                    yield
                    if should_commit:
                        commit_attempted = True
                        self._conn.commit()
                        active = False
                    else:
                        self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                        active = False
                except BaseException:
                    if commit_attempted:
                        try:
                            self._conn.rollback()
                        except BaseException:
                            pass
                    elif active:
                        try:
                            self._conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                        except BaseException:
                            pass
                        try:
                            self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                        except BaseException:
                            pass
                        if owns_transaction and self._conn.in_transaction:
                            try:
                                self._conn.rollback()
                            except BaseException:
                                pass
                    raise

    @_repository_operation
    def count_by_parent(self, parent_path: str, library_root: str) -> int:
        parent_path = self._path_key(parent_path)
        library_root = self._root_key(library_root)
        row = self._conn.execute(
            "SELECT COUNT(*) FROM assets WHERE parent_path=? AND library_root=?",
            (parent_path, library_root),
        ).fetchone()
        return int(row[0]) if row else 0

    @_repository_operation
    def get_dir_mtime(self, library_root: str, dir_path: str) -> float | None:
        """Return the recorded directory-mtime snapshot (None when unknown)."""
        row = self._conn.execute(
            "SELECT mtime FROM asset_dir_snapshot "
            "WHERE dir_path=? AND library_root=?",
            (self._path_key(dir_path), self._root_key(library_root)),
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return float(row[0])

    @_repository_operation
    def upsert_dir_snapshot(
        self, library_root: str, dir_path: str, mtime: float
    ) -> None:
        """Record (or refresh) the directory-mtime snapshot for one directory."""
        with self.transaction_scope(commit=True):
            self._conn.execute(
                "INSERT INTO asset_dir_snapshot (dir_path, library_root, mtime) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(dir_path) DO UPDATE SET "
                "mtime=excluded.mtime, updated_at=strftime('%s','now')",
                (self._path_key(dir_path), self._root_key(library_root), mtime),
            )

    @_repository_operation
    def clear_subtree(
        self, path: str, library_root: str, *, commit: bool = False
    ) -> int:
        """Remove indexed descendants before publishing a complete tree snapshot."""
        path = self._path_key(path)
        root_key = self._root_key(library_root)
        subtree = sql_like_descendant_pattern(path)
        with self.transaction_scope(commit=commit):
            if self._root_identity is None:
                cur = self._conn.execute(
                    "DELETE FROM assets WHERE "
                    "file_path LIKE ? ESCAPE '\\' "
                    "OR parent_path=? OR parent_path LIKE ? ESCAPE '\\'",
                    (subtree, path, subtree),
                )
            else:
                cur = self._conn.execute(
                    "DELETE FROM assets WHERE library_root=? AND ("
                    "file_path LIKE ? ESCAPE '\\' "
                    "OR parent_path=? OR parent_path LIKE ? ESCAPE '\\')",
                    (root_key, subtree, path, subtree),
                )
            return cur.rowcount

    @_repository_operation
    def replace_parent_entries(
        self,
        parent_path: str,
        library_root: str,
        entries: list[tuple[str, str, str, str, int, float, str, str, float, float]],
        *,
        clear_existing: bool,
        commit: bool = True,
        expected_revision: int | None = None,
        advance_revision: bool = True,
    ) -> None:
        parent_path = self._path_key(parent_path)
        library_root = self._root_key(library_root)
        entries = self._entry_values(entries)
        if not advance_revision and expected_revision is not None:
            raise ValueError("expected_revision requires advance_revision=True")
        with self.transaction_scope(commit=commit):
            if advance_revision:
                self._advance_revision(library_root, expected=expected_revision)
            if clear_existing:
                self._conn.execute(
                    "DELETE FROM assets WHERE parent_path=? AND library_root=?",
                    (parent_path, library_root),
                )
            if entries:
                self._conn.executemany(
                    "INSERT INTO assets (file_path, name, extension, kind, size, mtime, "
                    "parent_path, library_root, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(file_path) DO UPDATE SET "
                    "name=excluded.name, extension=excluded.extension, kind=excluded.kind, "
                    "size=excluded.size, mtime=excluded.mtime, "
                    "parent_path=excluded.parent_path, library_root=excluded.library_root, "
                    "updated_at=excluded.updated_at",
                    entries,
                )

    @_repository_operation
    def query_by_parent(self, library_root: str, parent_path: str) -> list[AssetIndexEntry]:
        return self._entries(
            "FROM assets WHERE parent_path=? AND library_root=? ORDER BY name",
            (self._path_key(parent_path), self._root_key(library_root)),
        )

    @_repository_operation
    def query_by_extension(self, library_root: str, extension: str) -> list[AssetIndexEntry]:
        return self._entries(
            "FROM assets WHERE extension=? AND library_root=? ORDER BY name",
            (extension.lower(), self._root_key(library_root)),
        )

    @_repository_operation
    def search_by_name(self, library_root: str, query: str, limit: int) -> list[AssetIndexEntry]:
        escaped = query.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return self._entries(
            "FROM assets WHERE library_root=? AND LOWER(name) LIKE ? ESCAPE '\\' "
            "ORDER BY name LIMIT ?",
            (self._root_key(library_root), f"%{escaped}%", limit),
        )

    def _structured_predicates(
        self,
        library_root: str | Path,
        *,
        name_substring: str | None,
        extensions: Sequence[str] | None,
        size_min: int | None,
        size_max: int | None,
        mtime_after: float | None,
        mtime_before: float | None,
        rating_min: int | None,
        rating_max: int | None,
        favorite: bool,
        favorite_owner_key: str | None,
    ) -> tuple[list[str], list[object], bool]:
        """Build the WHERE clauses and params shared by the structured
        search and count queries.

        Returns ``(clauses, params, needs_meta_join)``. ``library_root`` is
        always the first clause; every user value is bound as a parameter.
        """
        clauses = ["library_root=?"]
        params: list[object] = [self._root_key(library_root)]

        if name_substring:
            escaped = (
                name_substring.lower()
                .replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            clauses.append("LOWER(name) LIKE ? ESCAPE '\\'")
            params.append(f"%{escaped}%")

        if extensions:
            # The scanner stores lowercase extensions with a leading dot
            # ("" for directories), so normalize candidate input the same way.
            normalized = sorted({
                "." + str(ext).strip().lower().lstrip(".")
                for ext in extensions
                if str(ext).strip().lstrip(".")
            })
            if normalized:
                placeholders = ", ".join("?" for _ in normalized)
                clauses.append(f"extension IN ({placeholders})")
                params.extend(normalized)

        if size_min is not None:
            clauses.append("size>=?")
            params.append(size_min)
        if size_max is not None:
            clauses.append("size<=?")
            params.append(size_max)
        if mtime_after is not None:
            clauses.append("mtime>=?")
            params.append(mtime_after)
        if mtime_before is not None:
            clauses.append("mtime<=?")
            params.append(mtime_before)

        needs_meta = rating_min is not None or rating_max is not None
        if rating_min is not None:
            # NULL rating means "unrated" (migration v37 keeps no backfill),
            # so a positive rating filter excludes unrated rows: the NULL
            # comparison below is never true for them.
            clauses.append("file_meta.rating>=?")
            params.append(rating_min)
        if rating_max is not None:
            clauses.append("file_meta.rating<=?")
            params.append(rating_max)
        if favorite:
            # Viewer-scoped dimension: the owner key is resolved by the
            # caller (request principal) and bound as a parameter.
            if not favorite_owner_key:
                raise ValueError(
                    "favorite_owner_key is required when favorite=True"
                )
            clauses.append(
                "EXISTS (SELECT 1 FROM library_favorites AS fav "
                "WHERE fav.owner_key=? AND fav.file_path=assets.file_path)"
            )
            params.append(favorite_owner_key)
        return clauses, params, needs_meta

    def _validate_rating_bound(self, value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{field} must be an integer")
        return value

    @_repository_operation
    def search_structured(
        self,
        library_root: str | Path,
        *,
        name_substring: str | None = None,
        extensions: Sequence[str] | None = None,
        size_min: int | None = None,
        size_max: int | None = None,
        mtime_after: float | None = None,
        mtime_before: float | None = None,
        rating_min: int | None = None,
        rating_max: int | None = None,
        favorite: bool = False,
        favorite_owner_key: str | None = None,
        order_by: str = "name",
        descending: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> list[AssetIndexEntry]:
        """Combined structured query over the ``assets`` index.

        All predicates are AND-combined in one parameterized SQL statement.
        ``mtime`` is epoch seconds (``stat.st_mtime``), matching the column
        the scanner publishes; ``size`` is bytes. Range bounds are inclusive.
        ``rating_min``/``rating_max`` filter on ``file_meta.rating`` (0-5)
        through a LEFT JOIN; NULL ratings mean "unrated" and are excluded by
        any positive rating filter. ``favorite``/``favorite_owner_key`` keep
        only rows favorited by the given principal in ``library_favorites``.

        Only whitelisted literals reach the ORDER BY clause; every user
        value is bound as a parameter, and the name substring keeps the
        LIKE/ESCAPE escaping used by :meth:`search_by_name`.

        Note on indexing: the ``assets`` table carries indices on
        ``library_root``, ``extension``, ``name`` and ``parent_path`` only
        (no size/mtime index). Every combination therefore drives at least
        one existing index (``idx_assets_library`` or ``idx_assets_ext``)
        with size/mtime/LIKE as residual filters, and ORDER BY uses a TEMP
        B-TREE. Adding further indices is explicitly out of scope, so
        callers should keep ``limit`` bounded.
        """
        column = _STRUCTURED_ORDER_COLUMNS.get(order_by)
        if column is None:
            raise ValueError(
                f"order_by must be one of {sorted(_STRUCTURED_ORDER_COLUMNS)}, got {order_by!r}"
            )
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError("limit must be a positive integer")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        if rating_min is not None:
            rating_min = self._validate_rating_bound(rating_min, "rating_min")
        if rating_max is not None:
            rating_max = self._validate_rating_bound(rating_max, "rating_max")

        clauses, params, needs_meta = self._structured_predicates(
            library_root,
            name_substring=name_substring,
            extensions=extensions,
            size_min=size_min,
            size_max=size_max,
            mtime_after=mtime_after,
            mtime_before=mtime_before,
            rating_min=rating_min,
            rating_max=rating_max,
            favorite=favorite,
            favorite_owner_key=favorite_owner_key,
        )

        direction = "DESC" if descending else "ASC"
        params.append(limit)
        params.append(offset)
        # The rating column has few distinct values, so a name tiebreaker
        # keeps pagination deterministic (unlike the raw columns, whose
        # pre-existing order contract stays untouched).
        tiebreak = ", assets.name ASC" if order_by == "rating" else ""
        join = (
            " LEFT JOIN file_meta ON file_meta.file_path = assets.file_path"
            if (needs_meta or order_by == "rating")
            else ""
        )
        return self._entries(
            "FROM assets" + join + " WHERE " + " AND ".join(clauses)
            + f" ORDER BY {column} {direction}{tiebreak} LIMIT ? OFFSET ?",
            tuple(params),
        )

    @_repository_operation
    def count_structured(
        self,
        library_root: str | Path,
        *,
        name_substring: str | None = None,
        extensions: Sequence[str] | None = None,
        size_min: int | None = None,
        size_max: int | None = None,
        mtime_after: float | None = None,
        mtime_before: float | None = None,
        rating_min: int | None = None,
        rating_max: int | None = None,
        favorite: bool = False,
        favorite_owner_key: str | None = None,
    ) -> int:
        """Count the rows a structured query would return (no paging).

        Runs the same predicates as :meth:`search_structured` in one
        COUNT(*) — used for the live smart-collection asset counts, where
        paging the whole index would cost a sort per page.
        """
        if rating_min is not None:
            rating_min = self._validate_rating_bound(rating_min, "rating_min")
        if rating_max is not None:
            rating_max = self._validate_rating_bound(rating_max, "rating_max")
        clauses, params, needs_meta = self._structured_predicates(
            library_root,
            name_substring=name_substring,
            extensions=extensions,
            size_min=size_min,
            size_max=size_max,
            mtime_after=mtime_after,
            mtime_before=mtime_before,
            rating_min=rating_min,
            rating_max=rating_max,
            favorite=favorite,
            favorite_owner_key=favorite_owner_key,
        )
        join = (
            " LEFT JOIN file_meta ON file_meta.file_path = assets.file_path"
            if needs_meta
            else ""
        )
        row = self._conn.execute(
            "SELECT COUNT(*) FROM assets" + join + " WHERE " + " AND ".join(clauses),
            tuple(params),
        ).fetchone()
        return int(row[0]) if row else 0

    @_repository_operation
    def delete_entry(self, file_path: str, *, commit: bool = True) -> int:
        path = self._path_key(file_path)
        if self._root_identity is None:
            # M9-Bug9: an unbounded raw delete would remove the same path
            # from every indexed library root sharing this connection.
            # Require an explicit library_root (or a bound repository).
            raise ValueError(
                "asset index delete_entry requires a bound library_root; "
                "raw root-less deletes are not allowed"
            )
        with self.transaction_scope(commit=commit):
            revision_roots = self._matching_revision_roots(path)
            for revision_root in revision_roots:
                self._advance_revision(revision_root)
            cur = self._conn.execute(
                "DELETE FROM assets WHERE file_path=? AND library_root=?",
                (path, self._root_key(self._root_identity)),
            )
            return cur.rowcount

    @_repository_operation
    def repoint_file(self, old_path: str, new_path: str, *, commit: bool = True) -> int:
        """Repoint one indexed asset row after a verified external move (H2-b).

        Rewrites ``file_path``/``parent_path`` plus the derived name and
        extension, and re-stats the new location so ``size``/``mtime`` stay
        truthful without a rescan. Bound-root containment and the revision
        advance follow :meth:`delete_entry`; a root-less raw repoint is
        rejected. When the new path is already indexed the UNIQUE
        ``file_path`` constraint fails and the caller's transaction rolls
        back. Returns the number of rows repointed (0 when the old path was
        never indexed — relinking metadata alone is still worthwhile).
        """
        old = self._path_key(old_path)
        new = self._path_key(new_path)
        if old == new:
            return 0
        if self._root_identity is None:
            raise ValueError(
                "asset index repoint_file requires a bound library_root; "
                "raw root-less repoints are not allowed"
            )
        root_key = self._root_key(self._root_identity)
        new_path_obj = Path(new)
        name = new_path_obj.name
        extension = new_path_obj.suffix.lower()
        parent_path = str(new_path_obj.parent)
        try:
            stat = new_path_obj.stat()
            size, mtime = int(stat.st_size), float(stat.st_mtime)
        except OSError:
            size, mtime = 0, 0.0
        with self.transaction_scope(commit=commit):
            self._advance_revision(root_key)
            cur = self._conn.execute(
                "UPDATE assets SET file_path=?, name=?, extension=?, parent_path=?, "
                "size=?, mtime=?, updated_at=? "
                "WHERE file_path=? AND library_root=?",
                (new, name, extension, parent_path, size, mtime, time.time(),
                 old, root_key),
            )
            return cur.rowcount

    @_repository_operation
    def delete_path(self, path: str, *, commit: bool = True) -> int:
        path = self._path_key(path)
        if self._root_identity is None:
            # M9-Bug9: same root-less cross-library hazard as delete_entry.
            raise ValueError(
                "asset index delete_path requires a bound library_root; "
                "raw root-less deletes are not allowed"
            )
        subtree = sql_like_descendant_pattern(path)
        with self.transaction_scope(commit=commit):
            revision_roots = self._matching_revision_roots(path, subtree=subtree)
            for revision_root in revision_roots:
                self._advance_revision(revision_root)
            cur = self._conn.execute(
                "DELETE FROM assets WHERE library_root=? AND "
                "(file_path=? OR file_path LIKE ? ESCAPE '\\' "
                "OR parent_path=? OR parent_path LIKE ? ESCAPE '\\')",
                (self._root_key(self._root_identity), path, subtree, path, subtree),
            )
            return cur.rowcount

    @_repository_operation
    def count(self, library_root: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM assets WHERE library_root=?",
            (self._root_key(library_root),),
        ).fetchone()
        return int(row[0]) if row else 0

    @_repository_operation
    def get_entry(self, file_path: str) -> AssetIndexEntry | None:
        path = self._path_key(file_path)
        if self._root_identity is None:
            entries = self._entries("FROM assets WHERE file_path=?", (path,))
        else:
            entries = self._entries(
                "FROM assets WHERE file_path=? AND library_root=?",
                (path, self._root_key(self._root_identity)),
            )
        return entries[0] if entries else None

    def _entries(self, clause: str, params: tuple[object, ...]) -> list[AssetIndexEntry]:
        # Columns are table-qualified: structured queries LEFT JOIN
        # file_meta, which also carries a file_path column.
        rows = self._conn.execute(
            "SELECT assets.file_path, assets.name, assets.extension, assets.kind, "
            "assets.size, assets.mtime, assets.parent_path, assets.library_root " + clause,
            params,
        ).fetchall()
        return [AssetIndexEntry(*row) for row in rows]
