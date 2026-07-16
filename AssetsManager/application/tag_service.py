"""Tag application service."""
from __future__ import annotations

import logging
from pathlib import Path
from sqlite3 import Connection

from AssetsManager.application.context import ConnectionProvider, LibrarySession, session_operation
from AssetsManager.core.tag_library import get_library
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import TagsChanged
from AssetsManager.repositories.tag_repository import TagRepository

_log = logging.getLogger(__name__)


def _resolve_connection(
    db_conn: Connection | None,
    library_root: str | Path,
    connection_provider: ConnectionProvider | None,
) -> Connection:
    if db_conn is not None:
        return db_conn
    root = str(Path(library_root).resolve())
    if connection_provider is not None:
        return connection_provider(root)
    raise RuntimeError(
        "TagService requires either db_conn or a ConnectionProvider. "
        "Use ApplicationBootstrap.for_library() or pass connection_provider explicitly."
    )


def _get_repo(
    db_conn: Connection | None,
    library_root: str | Path,
    connection_provider: ConnectionProvider | None = None,
) -> TagRepository:
    """Resolve a TagRepository from an explicit connection or library root."""
    return TagRepository(_resolve_connection(db_conn, library_root, connection_provider))


class TagService:
    """Read and mutate tags through a single application-layer API.

    All tag operations go through TagRepository for DB access and
    TagLibrary for canonical name resolution.
    """

    def __init__(self, connection_provider: ConnectionProvider | None = None,
                 session: LibrarySession | None = None):
        self._connection_provider = connection_provider
        self._session = session

    @session_operation
    def list_tags(self, library_root: str | Path, db_conn: Connection | None = None) -> list[dict]:
        """Return all tags with usage counts."""
        conn = _resolve_connection(db_conn, library_root, self._connection_provider)
        rows = conn.execute(
            "SELECT tag, COUNT(*) as cnt FROM file_tags GROUP BY tag ORDER BY tag"
        ).fetchall()
        return [{"name": r[0], "count": r[1]} for r in rows]

    @session_operation
    def get_tags(self, library_root: str | Path, path: str | Path,
                 db_conn: Connection | None = None) -> list[str]:
        """Return tags for a file."""
        repo = _get_repo(db_conn, library_root, self._connection_provider)
        return repo.get_tags(str(Path(path).resolve()))

    @session_operation
    def add_tag(self, library_root: str | Path, path: str | Path, tag: str,
                db_conn: Connection | None = None) -> None:
        """Add a tag to a file, resolving to canonical form."""
        canonical = get_library().canonical(tag)
        if not canonical:
            return
        repo = _get_repo(db_conn, library_root, self._connection_provider)
        key = str(Path(path).resolve())
        existing = {t.lower() for t in repo.get_tags(key)}
        if canonical.lower() in existing:
            return
        repo.add_tag(key, canonical)
        get_event_bus().publish(TagsChanged(file_path=key, new_tags=tuple(repo.get_tags(key))))

    @session_operation
    def remove_tag(self, library_root: str | Path, path: str | Path, tag: str,
                   db_conn: Connection | None = None) -> None:
        """Remove a tag from a file (case-insensitive match)."""
        repo = _get_repo(db_conn, library_root, self._connection_provider)
        key = str(Path(path).resolve())
        existing = repo.get_tags(key)
        match = next((t for t in existing if t.lower() == tag.lower()), None)
        if match:
            repo.remove_tag(key, match)
            get_event_bus().publish(TagsChanged(file_path=key, new_tags=tuple(repo.get_tags(key))))

    @session_operation
    def rename_tag(self, library_root: str | Path, old_name: str, new_name: str,
                   db_conn: Connection | None = None) -> None:
        """Rename a tag across all files."""
        repo = _get_repo(db_conn, library_root, self._connection_provider)
        repo.rename_tag(old_name, new_name)
        get_event_bus().publish(TagsChanged())

    @session_operation
    def delete_tag(self, library_root: str | Path, tag_name: str,
                   db_conn: Connection | None = None) -> None:
        """Delete a tag from all files."""
        repo = _get_repo(db_conn, library_root, self._connection_provider)
        repo.delete_tag(tag_name)
        get_event_bus().publish(TagsChanged())

    @session_operation
    def get_tags_for_tree(self, library_root: str | Path, dir_path: str | Path,
                          db_conn: Connection | None = None) -> list[str]:
        """Return all distinct tags for a directory and its descendants."""
        repo = _get_repo(db_conn, library_root, self._connection_provider)
        return repo.get_tags_for_tree(str(Path(dir_path).resolve()))

    @session_operation
    def get_all_tags(self, library_root: str | Path,
                     db_conn: Connection | None = None) -> list[str]:
        """Return all distinct tags in the library."""
        repo = _get_repo(db_conn, library_root, self._connection_provider)
        return repo.get_all_tags()

    @session_operation
    def get_files_by_tag(self, library_root: str | Path, tag: str,
                         db_conn: Connection | None = None) -> set[str]:
        """Return all file paths that have a given tag."""
        repo = _get_repo(db_conn, library_root, self._connection_provider)
        return set(repo.get_files_by_tag(tag))

    # ── Tag metadata (color, icon, category) ─────────────────────

    @session_operation
    def get_tags_with_metadata(self, library_root: str | Path,
                               db_conn: Connection | None = None) -> list[dict]:
        """Return all tags with their metadata (color, icon, category)."""
        repo = _get_repo(db_conn, library_root, self._connection_provider)
        return repo.get_tags_with_metadata()

    @session_operation
    def set_tag_metadata(self, library_root: str | Path, tag: str,
                         color: str = "", icon: str = "", category: str = "",
                         db_conn: Connection | None = None) -> None:
        """Set metadata for a tag."""
        repo = _get_repo(db_conn, library_root, self._connection_provider)
        repo.set_tag_metadata(tag, color=color, icon=icon, category=category)

    @session_operation
    def get_tag_metadata(self, library_root: str | Path, tag: str,
                         db_conn: Connection | None = None) -> dict[str, str] | None:
        """Return metadata for a tag, or None if not set."""
        repo = _get_repo(db_conn, library_root, self._connection_provider)
        return repo.get_tag_metadata(tag)

    @session_operation
    def save(self, library_root: str | Path | None = None,
             db_conn: Connection | None = None) -> None:
        """Persist pending changes. No-op for TagService (auto-commit).

        Provided for protocol compatibility with TagStore.
        """


class TagServiceAdapter:
    """Adapter that makes TagService conform to TagStoreProtocol.

    ``TagEditorDialog`` expects a ``TagStore``-like object.  This adapter
    wraps ``TagService`` so the dialog can use it without knowing about
    ``library_root``.
    """

    def __init__(self, library_root: str | Path, svc: TagService | None = None):
        self._root = str(Path(library_root).resolve())
        self._svc = svc or TagService()

    def get_tags(self, filepath: str) -> list[str]:
        return self._svc.get_tags(self._root, filepath)

    def get_tags_for_files(self, filepaths: list[str]) -> dict[str, list[str]]:
        repo = _get_repo(None, self._root, self._svc._connection_provider)
        return repo.get_tags_for_files(filepaths)

    def add_tag(self, filepath: str, tag: str) -> None:
        self._svc.add_tag(self._root, filepath, tag)

    def remove_tag(self, filepath: str, tag: str) -> None:
        self._svc.remove_tag(self._root, filepath, tag)

    def remove_file(self, filepath: str) -> None:
        repo = _get_repo(None, self._root, self._svc._connection_provider)
        repo.remove_file(filepath)

    def get_all_tags(self) -> list[str]:
        return self._svc.get_all_tags(self._root)

    def get_files_by_tag(self, tag: str) -> set[str]:
        return self._svc.get_files_by_tag(self._root, tag)

    def save(self) -> None:
        pass  # auto-commit
