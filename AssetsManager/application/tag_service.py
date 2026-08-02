"""Tag application service."""
from __future__ import annotations

import logging
from pathlib import Path
from sqlite3 import Connection

from AssetsManager.application.context import ConnectionProvider, LibrarySession, session_operation
from AssetsManager.core.tag_library import get_library
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.errors import ValidationError
from AssetsManager.domain.events import AssetTagsChanged, TagCatalogChanged, TagsChanged
from AssetsManager.repositories.tag_repository import TagRepository

_log = logging.getLogger(__name__)
_MAX_TAG_NAME_LENGTH = 200


def _validated_tag_name(value: str, *, field: str) -> str:
    """Return one normalized tag name or raise a domain validation error."""
    if not isinstance(value, str):
        raise ValidationError(field, "must be a string")
    clean = value.strip()
    if not clean:
        raise ValidationError(field, "must not be empty")
    if len(clean) > _MAX_TAG_NAME_LENGTH:
        raise ValidationError(field, f"must be at most {_MAX_TAG_NAME_LENGTH} characters")
    return clean


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
    raise RuntimeError("TagService requires an explicit db_conn or ConnectionProvider.")


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

    @staticmethod
    def validate_tag_name(value: str, *, field: str = "tag") -> str:
        """Validate and normalize one tag name without touching persistence."""
        return _validated_tag_name(value, field=field)

    def _publish_asset_tags_changed(
        self, file_path: str, tags: tuple[str, ...], *, publish_catalog: bool = True
    ) -> None:
        if self._session is None:
            return
        get_event_bus().publish(AssetTagsChanged(
            library_root=self._session.root_str,
            session_token=self._session.event_token,
            file_path=file_path,
            new_tags=tags,
        ))
        if publish_catalog:
            self._publish_tag_catalog_changed()

    def _publish_tag_catalog_changed(self) -> None:
        if self._session is None:
            return
        get_event_bus().publish(TagCatalogChanged(
            library_root=self._session.root_str,
            session_token=self._session.event_token,
        ))

    @session_operation
    def list_tags(self, library_root: str | Path, db_conn: Connection | None = None) -> list[dict]:
        """Return all tags with usage counts."""
        repo = _get_repo(db_conn, library_root, self._connection_provider)
        return repo.list_tags_with_counts()

    @session_operation
    def get_tags(self, library_root: str | Path, path: str | Path,
                 db_conn: Connection | None = None) -> list[str]:
        """Return tags for a file."""
        repo = _get_repo(db_conn, library_root, self._connection_provider)
        return repo.get_tags(str(Path(path).resolve()))

    @session_operation
    def get_tags_for_files(self, library_root: str | Path, paths: list[str | Path],
                           db_conn: Connection | None = None) -> dict[str, list[str]]:
        """Return tags keyed by resolved path for many files at once."""
        repo = _get_repo(db_conn, library_root, self._connection_provider)
        return repo.get_tags_for_files([str(Path(path).resolve()) for path in paths])

    @session_operation
    def add_tag(self, library_root: str | Path, path: str | Path, tag: str,
                db_conn: Connection | None = None) -> None:
        """Add a tag to a file, resolving to canonical form."""
        tag = self.validate_tag_name(tag)
        canonical = get_library().canonical(tag)
        repo = _get_repo(db_conn, library_root, self._connection_provider)
        key = str(Path(path).resolve())
        existing = {t.lower() for t in repo.get_tags(key)}
        if canonical.lower() in existing:
            return
        repo.add_tag(key, canonical)
        tags = tuple(repo.get_tags(key))
        get_event_bus().publish(TagsChanged(file_path=key, new_tags=tags))
        self._publish_asset_tags_changed(key, tags)

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
            tags = tuple(repo.get_tags(key))
            get_event_bus().publish(TagsChanged(file_path=key, new_tags=tags))
            self._publish_asset_tags_changed(key, tags)

    @session_operation
    def remove_file(self, library_root: str | Path, path: str | Path,
                    db_conn: Connection | None = None) -> None:
        """Remove all tags for a resolved file path."""
        repo = _get_repo(db_conn, library_root, self._connection_provider)
        repo.remove_file(str(Path(path).resolve()))

    @session_operation
    def rename_tag(self, library_root: str | Path, old_name: str, new_name: str,
                   db_conn: Connection | None = None) -> None:
        """Rename a tag across all files."""
        new_name = self.validate_tag_name(new_name, field="new_name")
        repo = _get_repo(db_conn, library_root, self._connection_provider)
        paths = repo.get_files_by_tag(old_name)
        repo.rename_tag(old_name, new_name)
        get_event_bus().publish(TagsChanged())
        for path in paths:
            self._publish_asset_tags_changed(
                path, tuple(repo.get_tags(path)), publish_catalog=False
            )
        self._publish_tag_catalog_changed()

    @session_operation
    def delete_tag(self, library_root: str | Path, tag_name: str,
                   db_conn: Connection | None = None) -> None:
        """Delete a tag from all files."""
        repo = _get_repo(db_conn, library_root, self._connection_provider)
        paths = repo.get_files_by_tag(tag_name)
        repo.delete_tag(tag_name)
        get_event_bus().publish(TagsChanged())
        for path in paths:
            self._publish_asset_tags_changed(
                path, tuple(repo.get_tags(path)), publish_catalog=False
            )
        self._publish_tag_catalog_changed()

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
        return self._svc.get_tags_for_files(self._root, filepaths)

    def add_tag(self, filepath: str, tag: str) -> None:
        self._svc.add_tag(self._root, filepath, tag)

    def remove_tag(self, filepath: str, tag: str) -> None:
        self._svc.remove_tag(self._root, filepath, tag)

    def remove_file(self, filepath: str) -> None:
        self._svc.remove_file(self._root, filepath)

    def get_all_tags(self) -> list[str]:
        return self._svc.get_all_tags(self._root)

    def get_files_by_tag(self, tag: str) -> set[str]:
        return self._svc.get_files_by_tag(self._root, tag)

    def save(self) -> None:
        pass  # auto-commit
