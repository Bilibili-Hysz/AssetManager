"""Tag repository — CRUD operations for the physical tag tables."""
from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from sqlite3 import Connection
from typing import Any, Callable, Literal, TypeVar

from AssetsManager.core.database import DatabaseManager, db_write_lock, locked_read
from AssetsManager.core.path_resolver import (
    RootIdentity,
    path_key_separator,
    remap_path_subtree,
    root_identity,
    sql_like_descendant_pattern,
)
from AssetsManager.core.session_contract import require_library_session
from AssetsManager.domain.errors import DuplicateError

_R = TypeVar("_R")

# Tag provenance partitions. ``file_tags`` remains the human-curated catalog;
# ``ai_asset_tags`` / ``plugin_derived_fields`` (migration v36) are physical
# mirrors reserved for future AI/plugin writers so non-human rows can never
# leak into human tag queries.
TagSource = Literal["human", "ai", "plugin"]

_SOURCE_TABLES: dict[str, str] = {
    "human": "file_tags",
    "ai": "ai_asset_tags",
    "plugin": "plugin_derived_fields",
}


def _tag_table(source: str) -> str:
    """Resolve a tag source to its physical table name.

    SQLite cannot bind table names as SQL parameters, so ``source`` must be
    routed through this controlled whitelist before its result is
    interpolated into a statement. Unknown sources are rejected instead of
    silently falling back to ``file_tags``.
    """
    try:
        return _SOURCE_TABLES[source]
    except (KeyError, TypeError):
        raise ValueError(f"unknown tag source: {source!r}") from None


def _repository_operation(method: Callable[..., _R]) -> Callable[..., _R]:
    """Lease a canonical session for one complete repository operation."""
    @wraps(method)
    def wrapped(self: Any, *args: Any, **kwargs: Any) -> _R:
        with self._operation_scope():
            return method(self, *args, **kwargs)

    return wrapped


def _session_root(session: Any) -> RootIdentity:
    identity = getattr(getattr(session, "context", None), "root_identity", None)
    if isinstance(identity, RootIdentity):
        return identity
    raise TypeError(
        "TagRepository canonical session must expose a captured root identity"
    )


def _require_session_contract(
    session: Any,
) -> tuple[Callable[..., Any], Callable[..., Any]]:
    """Validate the real-session marker and the lifecycle/provider surface."""
    require_library_session(session)
    operation = getattr(session, "operation", None)
    if not callable(operation):
        raise TypeError(
            "TagRepository canonical session requires callable operation()"
        )
    connection_for = getattr(session, "connection_for", None)
    if not callable(connection_for):
        raise TypeError(
            "TagRepository canonical session requires callable connection_for()"
        )
    return operation, connection_for


class TagRepository:
    """Encapsulate all tag-related database operations.

    ``TagRepository(conn)`` remains the explicit raw compatibility path.
    Canonical callers should use :meth:`for_session`, which binds connection
    ownership, root containment, transaction lifetime, and close semantics to
    one real ``LibrarySession``.
    """

    def __init__(
        self,
        conn: Connection,
        *,
        library_root: str | Path | RootIdentity | None = None,
        session: Any | None = None,
    ):
        self._conn = conn
        self._session: Any | None = None
        self._library_root_key: str | None = None
        self._library_root: Path | None = None
        self._binding_lock = threading.RLock()
        self._raw_operation_started = False
        if library_root is not None:
            identity = root_identity(library_root, strict=False)
            self._library_root_key = identity.map_key
            self._library_root = identity.display_path
            DatabaseManager.validate_connection_owner(
                identity, conn, allow_unmanaged=True
            )
        if session is not None:
            self._bind_session(session, library_root=library_root)

    @classmethod
    def for_session(
        cls,
        session: Any,
        *,
        library_root: str | Path | RootIdentity | None = None,
    ) -> "TagRepository":
        """Build a strictly session/root-bound tag repository."""
        operation, connection_for = _require_session_contract(session)
        with operation():
            session_root = _session_root(session)
            conn = connection_for(session_root)
            conn = DatabaseManager.require_managed_connection_owner(
                session_root, conn
            )
            repository = cls(conn)
            repository._bind_session(session, library_root=library_root)
            return repository

    @contextmanager
    def _operation_scope(self):
        with self._binding_lock:
            session = self._session
            if session is None:
                self._raw_operation_started = True
        if session is None:
            yield
            return
        with session.operation():
            yield

    def _bind_session(
        self,
        session: Any,
        *,
        library_root: str | Path | RootIdentity | None = None,
    ) -> None:
        operation, connection_for = _require_session_contract(session)
        session_identity = _session_root(session)
        if library_root is not None:
            explicit_identity = root_identity(library_root, strict=False)
            if explicit_identity.map_key != session_identity.map_key:
                raise ValueError(
                    "TagRepository library_root does not match the LibrarySession"
                )

        with self._binding_lock:
            if self._session is not None:
                if self._session is session:
                    return
                raise RuntimeError(
                    "TagRepository is already bound to another LibrarySession"
                )
            if self._raw_operation_started:
                raise RuntimeError(
                    "TagRepository cannot bind after raw operations have started"
                )
            if (
                self._library_root_key is not None
                and self._library_root_key != session_identity.map_key
            ):
                raise ValueError("TagRepository belongs to a different library root")

            with operation():
                conn = connection_for(session_identity)
                conn = DatabaseManager.require_managed_connection_owner(
                    session_identity, conn
                )
                if conn is not self._conn:
                    raise ValueError(
                        "TagRepository connection does not belong to the LibrarySession"
                    )

                def publish_binding() -> None:
                    self._library_root_key = session_identity.map_key
                    self._library_root = session_identity.display_path
                    self._session = session

                session._publish_while_live(publish_binding)

    def _path_key(self, file_path: str | Path) -> str:
        """Return a canonical path and enforce bound-root containment."""
        if self._library_root is None:
            return str(file_path)
        target = Path(file_path).resolve()
        if not target.is_relative_to(self._library_root):
            raise ValueError(
                f"tag path must be under library_root: {target} "
                f"(root {self._library_root})"
            )
        return str(target)

    def _path_keys(self, file_paths: list[str]) -> list[str]:
        return [self._path_key(file_path) for file_path in file_paths]

    @contextmanager
    def _write_scope(
        self, operation_name: str, *, require_clean_transaction: bool = False
    ):
        """Commit raw writes, but preserve caller transactions when bound."""
        with db_write_lock(self._conn):
            if self._session is None:
                yield
                self._conn.commit()
                return

            if require_clean_transaction and self._conn.in_transaction:
                raise RuntimeError(
                    "TagRepository mutation requires a clean transaction boundary"
                )
            outer_transaction = self._conn.in_transaction
            savepoint = (
                f"tag_{operation_name}_{id(self):x}_{time.monotonic_ns():x}"
            )
            savepoint_active = False
            try:
                self._conn.execute(f"SAVEPOINT {savepoint}")
                savepoint_active = True
                yield
                self._conn.execute(f"RELEASE SAVEPOINT {savepoint}")
                savepoint_active = False
                if not outer_transaction:
                    self._conn.commit()
            except BaseException as exc:
                cleanup_errors: list[BaseException] = []
                if savepoint_active:
                    for statement in (
                        f"ROLLBACK TO SAVEPOINT {savepoint}",
                        f"RELEASE SAVEPOINT {savepoint}",
                    ):
                        try:
                            self._conn.execute(statement)
                        except BaseException as cleanup_exc:
                            cleanup_errors.append(cleanup_exc)
                if not outer_transaction and self._conn.in_transaction:
                    try:
                        self._conn.rollback()
                    except BaseException as cleanup_exc:
                        cleanup_errors.append(cleanup_exc)
                if cleanup_errors:
                    exc.add_note(
                        "TagRepository transaction cleanup also failed: "
                        + "; ".join(str(error) for error in cleanup_errors)
                    )
                raise

    # ── Reads ─────────────────────────────────────────────────────

    @_repository_operation
    @locked_read
    def get_tags(self, file_path: str, *, source: TagSource = "human") -> list[str]:
        """Return all tags for a file path, sorted alphabetically."""
        file_path = self._path_key(file_path)
        rows = self._conn.execute(
            f"SELECT tag FROM {_tag_table(source)} WHERE file_path=? ORDER BY tag",
            (file_path,),
        ).fetchall()
        return [r[0] for r in rows]

    @_repository_operation
    @locked_read
    def list_tags_with_counts(
        self, *, source: TagSource = "human"
    ) -> list[dict[str, int | str]]:
        """Return all tags with their usage counts, sorted by tag."""
        rows = self._conn.execute(
            f"SELECT tag, COUNT(*) as cnt FROM {_tag_table(source)} "
            "GROUP BY tag ORDER BY tag"
        ).fetchall()
        return [{"name": row[0], "count": row[1]} for row in rows]

    @_repository_operation
    @locked_read
    def get_tags_for_files(self, file_paths: list[str]) -> dict[str, list[str]]:
        """Return tags for multiple files, keyed by canonical file path."""
        if not file_paths:
            return {}
        canonical_paths = self._path_keys(file_paths)
        unique_paths = list(dict.fromkeys(canonical_paths))
        result: dict[str, list[str]] = {p: [] for p in unique_paths}
        for start in range(0, len(unique_paths), 900):
            chunk = unique_paths[start:start + 900]
            placeholders = ",".join("?" * len(chunk))
            rows = self._conn.execute(
                f"SELECT file_path, tag FROM file_tags WHERE file_path IN ({placeholders}) "
                "ORDER BY file_path, tag",
                chunk,
            ).fetchall()
            for path, tag in rows:
                result.setdefault(path, []).append(tag)
        return result

    @_repository_operation
    @locked_read
    def list_file_tags(self) -> list[tuple[str, str]]:
        """Return every file/tag pair in deterministic order."""
        rows = self._conn.execute(
            "SELECT file_path, tag FROM file_tags ORDER BY file_path, tag"
        ).fetchall()
        return [(str(file_path), str(tag)) for file_path, tag in rows]

    @_repository_operation
    @locked_read
    def get_all_tags(self, *, source: TagSource = "human") -> list[str]:
        """Return all unique tags across all files."""
        rows = self._conn.execute(
            f"SELECT DISTINCT tag FROM {_tag_table(source)} ORDER BY tag"
        ).fetchall()
        return [r[0] for r in rows]

    @_repository_operation
    @locked_read
    def get_files_by_tag(
        self, tag: str, *, source: TagSource = "human"
    ) -> list[str]:
        """Return all file paths that have a given tag."""
        rows = self._conn.execute(
            f"SELECT file_path FROM {_tag_table(source)} WHERE tag=?",
            (tag,),
        ).fetchall()
        return [r[0] for r in rows]

    @_repository_operation
    @locked_read
    def get_files_by_tag_case_insensitive(self, tag: str) -> list[str]:
        """Return file paths for a tag using SQLite's case-insensitive match."""
        rows = self._conn.execute(
            "SELECT file_path FROM file_tags WHERE LOWER(tag)=LOWER(?)",
            (tag,),
        ).fetchall()
        return [row[0] for row in rows]

    @_repository_operation
    @locked_read
    def get_tags_for_tree(self, dir_path: str) -> list[str]:
        """Return all unique tags for files under a directory prefix."""
        dir_path = self._path_key(dir_path)
        descendant_pattern = sql_like_descendant_pattern(dir_path)
        rows = self._conn.execute(
            "SELECT DISTINCT tag FROM file_tags WHERE file_path LIKE ? ESCAPE '\\' ORDER BY tag",
            (descendant_pattern,),
        ).fetchall()
        return [r[0] for r in rows]

    @_repository_operation
    @locked_read
    def get_tag_metadata(self, tag: str) -> dict[str, str] | None:
        """Return metadata for a tag, or None if not set."""
        row = self._conn.execute(
            "SELECT color, icon, category FROM tag_metadata WHERE tag=?",
            (tag,),
        ).fetchone()
        if row is None:
            return None
        return {"color": row[0], "icon": row[1], "category": row[2]}

    @_repository_operation
    @locked_read
    def get_tags_with_metadata(self) -> list[dict]:
        """Return all tags with their metadata."""
        rows = self._conn.execute(
            "SELECT t.tag, COUNT(*) as cnt, COALESCE(m.color, '') as color, "
            "COALESCE(m.icon, '') as icon, COALESCE(m.category, '') as category "
            "FROM file_tags t LEFT JOIN tag_metadata m ON t.tag = m.tag "
            "GROUP BY t.tag ORDER BY t.tag"
        ).fetchall()
        return [
            {"name": r[0], "count": r[1], "color": r[2], "icon": r[3], "category": r[4]}
            for r in rows
        ]

    # ── Writes ────────────────────────────────────────────────────

    @_repository_operation
    def add_tag(
        self, file_path: str, tag: str, *,
        source: TagSource = "human",
        commit: bool = True,
        require_clean_transaction: bool = False,
    ) -> bool:
        """Add a tag; duplicate rows remain an idempotent successful no-op."""
        file_path = self._path_key(file_path)
        table = _tag_table(source)

        def insert() -> None:
            self._conn.execute(
                f"INSERT OR IGNORE INTO {table} (file_path, tag) VALUES (?, ?)",
                (file_path, tag),
            )

        if commit:
            with self._write_scope(
                "add_tag", require_clean_transaction=require_clean_transaction
            ):
                insert()
        else:
            with db_write_lock(self._conn):
                insert()
        return True

    @_repository_operation
    def remove_tag(
        self, file_path: str, tag: str, *,
        source: TagSource = "human",
        commit: bool = True,
        require_clean_transaction: bool = False,
    ) -> bool:
        """Remove a tag; missing rows remain an idempotent successful no-op."""
        file_path = self._path_key(file_path)
        table = _tag_table(source)

        def remove() -> None:
            self._conn.execute(
                f"DELETE FROM {table} WHERE file_path=? AND tag=?",
                (file_path, tag),
            )

        if commit:
            with self._write_scope(
                "remove_tag", require_clean_transaction=require_clean_transaction
            ):
                remove()
        else:
            with db_write_lock(self._conn):
                remove()
        return True

    @_repository_operation
    def remove_file(
        self, file_path: str, *, commit: bool = True,
        require_clean_transaction: bool = False,
    ) -> int:
        """Remove all tags for a file and return the number removed."""
        file_path = self._path_key(file_path)

        def remove() -> int:
            cur = self._conn.execute(
                "DELETE FROM file_tags WHERE file_path=?",
                (file_path,),
            )
            return cur.rowcount

        if commit:
            with self._write_scope(
                "remove_file", require_clean_transaction=require_clean_transaction
            ):
                return remove()
        with db_write_lock(self._conn):
            return remove()

    @_repository_operation
    def delete_path(
        self, file_path: str, *, commit: bool = True,
        require_clean_transaction: bool = False,
    ) -> int:
        """Delete tags for a path and its descendants."""
        file_path = self._path_key(file_path)
        descendant_pattern = sql_like_descendant_pattern(file_path)

        def delete() -> int:
            cur = self._conn.execute(
                "DELETE FROM file_tags WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
                (file_path, descendant_pattern),
            )
            return cur.rowcount

        if commit:
            with self._write_scope(
                "delete_path", require_clean_transaction=require_clean_transaction
            ):
                return delete()
        with db_write_lock(self._conn):
            return delete()

    @_repository_operation
    def rename_tag(
        self, old_name: str, new_name: str, *, commit: bool = True,
        require_clean_transaction: bool = False,
    ) -> int:
        """Rename a tag across all files and return rows affected.

        ``tag_metadata`` follows the rename: if the target tag already has
        its own metadata row, the target row wins (the old row is dropped).
        Renaming onto a tag that already exists on one of the affected files
        raises :class:`DuplicateError` instead of leaking a UNIQUE
        ``(file_path, tag)`` constraint failure.
        """
        if old_name == new_name:
            return 0

        def rename() -> int:
            conflicting = self._conn.execute(
                "SELECT file_path FROM file_tags WHERE tag=? AND file_path IN "
                "(SELECT file_path FROM file_tags WHERE tag=?) LIMIT 1",
                (new_name, old_name),
            ).fetchone()
            if conflicting is not None:
                raise DuplicateError("tag", new_name)
            cur = self._conn.execute(
                "UPDATE file_tags SET tag=? WHERE tag=?",
                (new_name, old_name),
            )
            # Migrate tag metadata; an existing target row keeps its values.
            moved = self._conn.execute(
                "UPDATE tag_metadata SET tag=? WHERE tag=? AND NOT EXISTS "
                "(SELECT 1 FROM tag_metadata WHERE tag=?)",
                (new_name, old_name, new_name),
            ).rowcount
            if not moved:
                self._conn.execute("DELETE FROM tag_metadata WHERE tag=?", (old_name,))
            return cur.rowcount

        if commit:
            with self._write_scope(
                "rename_tag", require_clean_transaction=require_clean_transaction
            ):
                return rename()
        with db_write_lock(self._conn):
            return rename()

    @_repository_operation
    def delete_tag(
        self, tag_name: str, *, commit: bool = True,
        require_clean_transaction: bool = False,
    ) -> int:
        """Delete a tag from all files and return rows affected."""
        def delete() -> int:
            cur = self._conn.execute(
                "DELETE FROM file_tags WHERE tag=?",
                (tag_name,),
            )
            self._conn.execute("DELETE FROM tag_metadata WHERE tag=?", (tag_name,))
            return cur.rowcount

        if commit:
            with self._write_scope(
                "delete_tag", require_clean_transaction=require_clean_transaction
            ):
                return delete()
        with db_write_lock(self._conn):
            return delete()

    @_repository_operation
    def migrate_path(
        self, old_path: str, new_path: str, *, commit: bool = True,
        require_clean_transaction: bool = False,
    ) -> int:
        """Move all tags from old_path to new_path. Returns rows affected."""
        old_path = self._path_key(old_path)
        new_path = self._path_key(new_path)
        if old_path == new_path:
            return 0
        if new_path.startswith(old_path + path_key_separator(old_path)):
            raise ValueError("tag migration target cannot be inside source subtree")
        descendant_pattern = sql_like_descendant_pattern(old_path)

        def migrate() -> int:
            rows = self._conn.execute(
                "SELECT file_path, tag FROM file_tags "
                "WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
                (old_path, descendant_pattern),
            ).fetchall()
            count = 0
            for path, tag in rows:
                mapped = remap_path_subtree(old_path, new_path, path)
                self._conn.execute(
                    "INSERT OR IGNORE INTO file_tags (file_path, tag) VALUES (?, ?)",
                    (mapped, tag),
                )
                count += 1
            if rows:
                self._conn.execute(
                    "DELETE FROM file_tags WHERE file_path=? OR file_path LIKE ? ESCAPE '\\'",
                    (old_path, descendant_pattern),
                )
            return count

        if commit:
            with self._write_scope(
                "migrate_path", require_clean_transaction=require_clean_transaction
            ):
                return migrate()
        with db_write_lock(self._conn):
            return migrate()

    @_repository_operation
    def set_tag_metadata(
        self,
        tag: str,
        color: str = "",
        icon: str = "",
        category: str = "",
        *,
        commit: bool = True,
        require_clean_transaction: bool = False,
    ) -> None:
        """Set metadata for a tag."""
        def set_metadata() -> None:
            self._conn.execute(
                "INSERT INTO tag_metadata (tag, color, icon, category) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(tag) DO UPDATE SET "
                "color=excluded.color, icon=excluded.icon, category=excluded.category",
                (tag, color, icon, category),
            )

        if commit:
            with self._write_scope(
                "set_tag_metadata", require_clean_transaction=require_clean_transaction
            ):
                set_metadata()
        else:
            with db_write_lock(self._conn):
                set_metadata()

    @_repository_operation
    def delete_tag_metadata(
        self, tag: str, *, commit: bool = True,
        require_clean_transaction: bool = False,
    ) -> None:
        """Delete metadata for a tag."""
        def delete_metadata() -> None:
            self._conn.execute("DELETE FROM tag_metadata WHERE tag=?", (tag,))

        if commit:
            with self._write_scope(
                "delete_tag_metadata", require_clean_transaction=require_clean_transaction
            ):
                delete_metadata()
        else:
            with db_write_lock(self._conn):
                delete_metadata()
