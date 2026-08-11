"""Tag application service."""
from __future__ import annotations

import logging
from pathlib import Path
from sqlite3 import Connection

from AssetsManager.application.context import ConnectionProvider, LibrarySession, session_operation
from AssetsManager.core import icons
from AssetsManager.core.database import DatabaseManager
from AssetsManager.core.path_resolver import root_identity
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


def _resolve_under_root(library_root: str | Path, path: str | Path) -> str:
    """Resolve a path and reject values outside the requested library root."""
    root = Path(library_root).resolve()
    target = Path(path).resolve()
    if not target.is_relative_to(root):
        raise ValueError(
            f"path must be under library_root: {target} (root {root})"
        )
    return str(target)


def _resolve_many_under_root(
    library_root: str | Path, paths: list[str | Path]
) -> list[str]:
    return [_resolve_under_root(library_root, path) for path in paths]


def _resolve_connection(
    db_conn: Connection | None,
    library_root: str | Path,
    connection_provider: ConnectionProvider | None,
) -> Connection:
    root = str(Path(library_root).resolve())
    if db_conn is not None:
        return DatabaseManager.validate_connection_owner(root, db_conn, allow_unmanaged=True)
    if connection_provider is not None:
        conn = connection_provider(root)
        return DatabaseManager.validate_connection_owner(root, conn, allow_unmanaged=True)
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
        self._session = session
        self._repository: TagRepository | None = None
        self._root_identity = None
        if isinstance(session, LibrarySession):
            expected_provider = session.connection_for
            provider = connection_provider or expected_provider
            provider_self = getattr(provider, "__self__", None)
            provider_func = getattr(provider, "__func__", None)
            expected_func = getattr(expected_provider, "__func__", None)
            if not (
                provider == expected_provider
                or (provider_self is session and provider_func is expected_func)
            ):
                raise ValueError(
                    "TagService connection provider does not belong to "
                    "the LibrarySession"
                )
            self._connection_provider = expected_provider
            self._root_identity = session.context.root_identity
            self._repository = TagRepository.for_session(session)
        else:
            # Provider-only fake sessions remain on the raw compatibility path.
            self._connection_provider = connection_provider

    @classmethod
    def for_session(cls, session: LibrarySession) -> "TagService":
        """Build the canonical tag service for one real session."""
        if not isinstance(session, LibrarySession):
            raise TypeError("TagService.for_session requires a real LibrarySession")
        return cls(connection_provider=session.connection_for, session=session)

    def _repo(
        self,
        db_conn: Connection | None,
        library_root: str | Path,
    ) -> TagRepository:
        if isinstance(self._session, LibrarySession):
            requested = root_identity(library_root, strict=False)
            captured = self._root_identity
            if captured is None or requested.map_key != captured.map_key:
                raise ValueError(
                    "TagService library_root does not match the bound LibrarySession"
                )
            expected = self._session.connection_for(captured)
            if db_conn is not None and db_conn is not expected:
                raise ValueError(
                    "TagService connection does not belong to the bound LibrarySession"
                )
            if self._repository is None or self._repository._conn is not expected:
                raise RuntimeError("TagService repository binding is unavailable")
            return self._repository
        return _get_repo(db_conn, library_root, self._connection_provider)

    def _require_event_safe_transaction(self, repo: TagRepository) -> None:
        """Reject outer transactions before publishing unscoped/scoped tag events."""
        if isinstance(self._session, LibrarySession) and repo._conn.in_transaction:
            raise RuntimeError(
                "TagService tag mutations require a clean transaction boundary"
            )

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
        repo = self._repo(db_conn, library_root)
        return repo.list_tags_with_counts()

    @session_operation
    def get_tags(self, library_root: str | Path, path: str | Path,
                 db_conn: Connection | None = None) -> list[str]:
        """Return tags for a file."""
        key = _resolve_under_root(library_root, path)
        repo = self._repo(db_conn, library_root)
        return repo.get_tags(key)

    @session_operation
    def get_tags_for_files(self, library_root: str | Path, paths: list[str | Path],
                           db_conn: Connection | None = None) -> dict[str, list[str]]:
        """Return tags keyed by resolved path for many files at once."""
        keys = _resolve_many_under_root(library_root, paths)
        repo = self._repo(db_conn, library_root)
        return repo.get_tags_for_files(keys)

    @session_operation
    def add_tag(self, library_root: str | Path, path: str | Path, tag: str,
                db_conn: Connection | None = None) -> None:
        """Add a tag to a file, resolving to canonical form."""
        tag = self.validate_tag_name(tag)
        canonical = get_library().canonical(tag)
        key = _resolve_under_root(library_root, path)
        repo = self._repo(db_conn, library_root)
        self._require_event_safe_transaction(repo)
        existing = {t.lower() for t in repo.get_tags(key)}
        if canonical.lower() in existing:
            return
        repo.add_tag(key, canonical, require_clean_transaction=True)
        tags = tuple(repo.get_tags(key))
        get_event_bus().publish(TagsChanged(file_path=key, new_tags=tags))
        self._publish_asset_tags_changed(key, tags)

    @session_operation
    def remove_tag(self, library_root: str | Path, path: str | Path, tag: str,
                   db_conn: Connection | None = None) -> None:
        """Remove a tag from a file (case-insensitive match)."""
        key = _resolve_under_root(library_root, path)
        repo = self._repo(db_conn, library_root)
        self._require_event_safe_transaction(repo)
        existing = repo.get_tags(key)
        match = next((t for t in existing if t.lower() == tag.lower()), None)
        if match:
            repo.remove_tag(key, match, require_clean_transaction=True)
            tags = tuple(repo.get_tags(key))
            get_event_bus().publish(TagsChanged(file_path=key, new_tags=tags))
            self._publish_asset_tags_changed(key, tags)

    @session_operation
    def remove_file(self, library_root: str | Path, path: str | Path,
                    db_conn: Connection | None = None) -> None:
        """Remove all tags for a resolved file path and publish its empty state."""
        key = _resolve_under_root(library_root, path)
        repo = self._repo(db_conn, library_root)
        self._require_event_safe_transaction(repo)
        removed = repo.remove_file(key, require_clean_transaction=True)
        if removed:
            get_event_bus().publish(TagsChanged(file_path=key, new_tags=()))
            self._publish_asset_tags_changed(key, (), publish_catalog=True)

    @session_operation
    def rename_tag(self, library_root: str | Path, old_name: str, new_name: str,
                   db_conn: Connection | None = None) -> None:
        """Rename a tag across all files."""
        new_name = self.validate_tag_name(new_name, field="new_name")
        repo = self._repo(db_conn, library_root)
        self._require_event_safe_transaction(repo)
        paths = repo.get_files_by_tag(old_name)
        repo.rename_tag(old_name, new_name, require_clean_transaction=True)
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
        repo = self._repo(db_conn, library_root)
        self._require_event_safe_transaction(repo)
        paths = repo.get_files_by_tag(tag_name)
        repo.delete_tag(tag_name, require_clean_transaction=True)
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
        key = _resolve_under_root(library_root, dir_path)
        repo = self._repo(db_conn, library_root)
        return repo.get_tags_for_tree(key)

    @session_operation
    def get_all_tags(self, library_root: str | Path,
                     db_conn: Connection | None = None) -> list[str]:
        """Return all distinct tags in the library."""
        repo = self._repo(db_conn, library_root)
        return repo.get_all_tags()

    @session_operation
    def get_files_by_tag(self, library_root: str | Path, tag: str,
                         db_conn: Connection | None = None) -> set[str]:
        """Return all file paths that have a given tag."""
        repo = self._repo(db_conn, library_root)
        return set(repo.get_files_by_tag(tag))

    # ── Tag metadata (color, icon, category) ─────────────────────

    @session_operation
    def get_tags_with_metadata(self, library_root: str | Path,
                               db_conn: Connection | None = None) -> list[dict]:
        """Return all tags with their metadata (color, icon, category)."""
        repo = self._repo(db_conn, library_root)
        return repo.get_tags_with_metadata()

    @session_operation
    def set_tag_metadata(self, library_root: str | Path, tag: str,
                         color: str = "", icon: str = "", category: str = "",
                         db_conn: Connection | None = None) -> None:
        """Set metadata for a tag and invalidate the scoped tag catalog."""
        repo = self._repo(db_conn, library_root)
        icon = "" if not icon else icons.normalize(icon, fallback="tag")
        expected = {"color": color, "icon": icon, "category": category}
        if repo.get_tag_metadata(tag) == expected:
            return
        self._require_event_safe_transaction(repo)
        repo.set_tag_metadata(
            tag, color=color, icon=icon, category=category,
            require_clean_transaction=True,
        )
        self._publish_tag_catalog_changed()

    @session_operation
    def delete_tag_metadata(
        self, library_root: str | Path, tag: str,
        db_conn: Connection | None = None,
    ) -> None:
        """Delete metadata for a tag and invalidate the scoped tag catalog."""
        repo = self._repo(db_conn, library_root)
        if repo.get_tag_metadata(tag) is None:
            return
        self._require_event_safe_transaction(repo)
        repo.delete_tag_metadata(tag, require_clean_transaction=True)
        self._publish_tag_catalog_changed()

    @session_operation
    def get_tag_metadata(self, library_root: str | Path, tag: str,
                         db_conn: Connection | None = None) -> dict[str, str] | None:
        """Return metadata for a tag, or None if not set."""
        repo = self._repo(db_conn, library_root)
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
