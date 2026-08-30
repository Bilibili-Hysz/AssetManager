"""Tag application service."""
from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from pathlib import Path
from sqlite3 import Connection
from threading import Lock
from typing import TYPE_CHECKING, Callable

from AssetsManager.application.activity_recorder import ActivityRecorder, summarize_targets
from AssetsManager.application.context import ConnectionProvider, LibrarySession, session_operation
from AssetsManager.application.tag_canonicalizer import canonical_tag
from AssetsManager.core import icons
from AssetsManager.core.database import DatabaseManager
from AssetsManager.core.path_resolver import root_identity
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.errors import OperationNotPermitted, PathEscapeError, ValidationError
from AssetsManager.domain.events import AssetTagsChanged, TagCatalogChanged
from AssetsManager.repositories.tag_repository import TagRepository, TagSource

if TYPE_CHECKING:
    from AssetsManager.application.search_index_service import SearchIndexService

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


# Path resolution moved onto the TagService instance (cached methods
# ``_resolve_under_root`` / ``_resolve_many_under_root``) so batch tag reads
# for large directories reuse one bounded resolve cache instead of paying a
# ``Path.resolve()`` syscall per file per refresh.  See ``get_resolved_path``.


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

    # Bounded resolve caches mirror TagStore._resolve_cache semantics: capped
    # size, cleared wholesale on overflow, lock-protected.  A resolved file
    # path is independent of the library root, so path entries are keyed by
    # the raw path string; the root-containment check still runs on every
    # call and uses its own (much smaller) root cache.
    _RESOLVE_CACHE_MAX = 10000
    _ROOT_RESOLVE_CACHE_MAX = 64

    def __init__(self, connection_provider: ConnectionProvider | None = None,
                 session: LibrarySession | None = None,
                 canonicalize: Callable[[str], str] | None = None,
                 activity_recorder: ActivityRecorder | None = None,
                 search_index_service: SearchIndexService | None = None):
        self._session = session
        self._canonicalize = canonicalize if canonicalize is not None else canonical_tag
        self._activity_recorder = activity_recorder
        self._search_index_service = search_index_service
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
        self._resolve_cache: dict[str, str] = {}
        self._root_resolve_cache: dict[str, str] = {}
        self._resolve_lock = Lock()

    @classmethod
    def for_session(cls, session: LibrarySession,
                    *, activity_recorder: ActivityRecorder | None = None,
                    search_index_service: SearchIndexService | None = None) -> "TagService":
        """Build the canonical tag service for one real session."""
        if not isinstance(session, LibrarySession):
            raise TypeError("TagService.for_session requires a real LibrarySession")
        return cls(connection_provider=session.connection_for, session=session,
                   activity_recorder=activity_recorder,
                   search_index_service=search_index_service)

    def _resolve_root(self, library_root: str | Path) -> str:
        """Cached Path.resolve() for library roots."""
        key = os.fspath(library_root)
        if not isinstance(key, str):
            key = os.fsdecode(key)
        with self._resolve_lock:
            cached = self._root_resolve_cache.get(key)
            if cached is not None:
                return cached
            if len(self._root_resolve_cache) >= self._ROOT_RESOLVE_CACHE_MAX:
                self._root_resolve_cache.clear()
            resolved = str(Path(library_root).resolve())
            self._root_resolve_cache[key] = resolved
            return resolved

    def _resolve_path(self, path: str | Path) -> str:
        """Cached Path.resolve() for file paths."""
        key = os.fspath(path)
        if not isinstance(key, str):
            key = os.fsdecode(key)
        with self._resolve_lock:
            cached = self._resolve_cache.get(key)
            if cached is not None:
                return cached
            if len(self._resolve_cache) >= self._RESOLVE_CACHE_MAX:
                self._resolve_cache.clear()
            resolved = str(Path(path).resolve())
            self._resolve_cache[key] = resolved
            return resolved

    def _resolve_under_root(self, library_root: str | Path, path: str | Path) -> str:
        """Resolve a path and reject values outside the requested library root."""
        root = self._resolve_root(library_root)
        target = self._resolve_path(path)
        if not Path(target).is_relative_to(Path(root)):
            # Domain escape error so the LAN error contract maps it to a 400
            # instead of an unmapped 500 (minimal ValueError migration).
            raise PathEscapeError(str(target), root)
        return target

    def _resolve_many_under_root(
        self, library_root: str | Path, paths: list[str | Path]
    ) -> list[str]:
        """Resolve many paths, resolving the root exactly once per batch."""
        root = self._resolve_root(library_root)
        keys = []
        for path in paths:
            target = self._resolve_path(path)
            if not Path(target).is_relative_to(Path(root)):
                raise PathEscapeError(str(target), root)
            keys.append(target)
        return keys

    def get_resolved_path(self, library_root: str | Path, path: str | Path) -> str:
        """Return the resolved storage key for ``path`` via the shared resolve cache.

        Consumers like the Details view reuse this instead of paying a second
        ``Path.resolve()`` syscall per file on the UI thread; the result is
        identical to the keys produced by :meth:`get_tags_for_files`.
        Deliberately not decorated with :func:`session_operation` — pure path
        computation touches no database.
        """
        return self._resolve_under_root(library_root, path)

    def _repo(
        self,
        db_conn: Connection | None,
        library_root: str | Path,
    ) -> TagRepository:
        if isinstance(self._session, LibrarySession):
            requested = root_identity(library_root, strict=False)
            captured = self._root_identity
            if captured is None or requested.map_key != captured.map_key:
                # Domain error so the LAN error contract maps binding
                # mismatches to a mapped status instead of an unmapped 500
                # (minimal ValueError migration; message text preserved).
                raise OperationNotPermitted(
                    "TagService library_root does not match the bound LibrarySession"
                )
            expected = self._session.connection_for(captured)
            if db_conn is not None and db_conn is not expected:
                raise OperationNotPermitted(
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

    def _publish_asset_tags_batch_changed(self, paths: tuple[str, ...]) -> None:
        """Publish exactly one batch AssetTagsChanged for every affected path.

        Catalog-wide operations (rename/delete of a tag) previously emitted
        one event per file, which floods the bus for popular tags.  The batch
        event carries all paths and no per-asset tag snapshot; consumers
        re-read state (the runtime router only needs the path set).
        """
        if self._session is None or not paths:
            return
        get_event_bus().publish(AssetTagsChanged(
            library_root=self._session.root_str,
            session_token=self._session.event_token,
            file_path="",
            new_tags=(),
            paths=paths,
        ))

    def _reindex_search_documents(self, paths: Iterable[str]) -> None:
        """Refresh ``asset_search`` documents for changed paths; never raises.

        The FTS index (migration v39) aggregates name/tags/notes per path,
        so every tag mutation dirties at least one document. The maintainer
        swallows its own failures (ActivityRecorder contract); this outer
        guard keeps the bookkeeping strictly non-essential even if that
        wiring changes.
        """
        service = self._search_index_service
        if service is None:
            return
        keys = [path for path in paths if path]
        if not keys:
            return
        try:
            service.reindex_files(keys)
        except Exception:  # pragma: no cover - defensive, service never raises
            _log.warning("Search index reindex hook failed", exc_info=True)

    @session_operation
    def list_tags(self, library_root: str | Path, db_conn: Connection | None = None,
                  *, source: TagSource = "human") -> list[dict]:
        """Return all tags with usage counts."""
        repo = self._repo(db_conn, library_root)
        return repo.list_tags_with_counts(source=source)

    @session_operation
    def get_tags(self, library_root: str | Path, path: str | Path,
                 db_conn: Connection | None = None,
                 *, source: TagSource = "human") -> list[str]:
        """Return tags for a file."""
        key = self._resolve_under_root(library_root, path)
        repo = self._repo(db_conn, library_root)
        return repo.get_tags(key, source=source)

    @session_operation
    def get_tags_for_files(self, library_root: str | Path, paths: list[str | Path],
                           db_conn: Connection | None = None) -> dict[str, list[str]]:
        """Return tags keyed by resolved path for many files at once."""
        keys = self._resolve_many_under_root(library_root, paths)
        repo = self._repo(db_conn, library_root)
        return repo.get_tags_for_files(keys)

    @session_operation
    def add_tag(self, library_root: str | Path, path: str | Path, tag: str,
                db_conn: Connection | None = None,
                *, source: TagSource = "human") -> bool:
        """Add a tag to a file, resolving to canonical form.

        Returns True when the tag was newly added, False when the file
        already carried it (a no-op).

        The ``human`` default keeps the historical behavior byte-for-byte.
        Non-human sources write to their own physical partition and publish
        only ``AssetTagsChanged`` (no catalog event): the tag catalog is the
        human curation surface, so AI/plugin rows must not appear to have
        changed it. Non-human writes never enter the undo stack because undo
        recording lives in the (human-only) UI controllers.
        """
        tag = self.validate_tag_name(tag)
        canonical = self._canonicalize(tag)
        key = self._resolve_under_root(library_root, path)
        repo = self._repo(db_conn, library_root)
        self._require_event_safe_transaction(repo)
        existing = {t.lower() for t in repo.get_tags(key, source=source)}
        if canonical.lower() in existing:
            return False
        repo.add_tag(key, canonical, source=source, require_clean_transaction=True)
        tags = tuple(repo.get_tags(key, source=source))
        self._publish_asset_tags_changed(
            key, tags, publish_catalog=(source == "human")
        )
        self._reindex_search_documents((key,))
        return True

    @session_operation
    def add_tag_to_files(self, library_root: str | Path,
                         paths: list[str | Path], tag: str,
                         db_conn: Connection | None = None) -> int:
        """Apply one tag to many files and record exactly one activity row.

        Desktop batch-tagging surface (file list multi-selection). Each file
        goes through :meth:`add_tag` (per-file validation, canonicalization,
        and change events stay unchanged); the batch shares a single
        ``activity_log`` row instead of one per file. Returns the number of
        files the tag was newly added to.
        """
        tag = self.validate_tag_name(tag)
        canonical = self._canonicalize(tag)
        keys = self._resolve_many_under_root(library_root, paths)
        added: list[str] = []
        for key in keys:
            if self.add_tag(library_root, key, canonical, db_conn):
                added.append(key)
        if added and self._activity_recorder is not None:
            try:
                self._activity_recorder.record(
                    "tag_add", f"{canonical} -> {summarize_targets(added)}"
                )
            except Exception:
                # Activity recording must never fail the tagging itself.
                pass
        return len(added)

    @session_operation
    def remove_tag(self, library_root: str | Path, path: str | Path, tag: str,
                   db_conn: Connection | None = None,
                   *, source: TagSource = "human") -> bool:
        """Remove a tag from a file (case-insensitive match).

        Returns True when a stored tag was removed, False when the file did
        not carry it (a no-op).
        """
        key = self._resolve_under_root(library_root, path)
        repo = self._repo(db_conn, library_root)
        self._require_event_safe_transaction(repo)
        existing = repo.get_tags(key, source=source)
        match = next((t for t in existing if t.lower() == tag.lower()), None)
        if not match:
            return False
        repo.remove_tag(key, match, source=source, require_clean_transaction=True)
        tags = tuple(repo.get_tags(key, source=source))
        self._publish_asset_tags_changed(
            key, tags, publish_catalog=(source == "human")
        )
        self._reindex_search_documents((key,))
        return True

    @session_operation
    def remove_tag_from_files(self, library_root: str | Path,
                              paths: list[str | Path], tag: str,
                              db_conn: Connection | None = None) -> int:
        """Remove one tag from many files and record exactly one activity row.

        Desktop batch-untagging surface (file list multi-selection); the
        batch shares a single ``activity_log`` row. Returns the number of
        files the tag was actually removed from.
        """
        tag = self.validate_tag_name(tag)
        keys = self._resolve_many_under_root(library_root, paths)
        removed: list[str] = []
        for key in keys:
            if self.remove_tag(library_root, key, tag, db_conn):
                removed.append(key)
        if removed and self._activity_recorder is not None:
            try:
                self._activity_recorder.record(
                    "tag_remove", f"{tag} <- {summarize_targets(removed)}"
                )
            except Exception:
                # Activity recording must never fail the tagging itself.
                pass
        return len(removed)

    @session_operation
    def remove_file(self, library_root: str | Path, path: str | Path,
                    db_conn: Connection | None = None) -> None:
        """Remove all tags for a resolved file path and publish its empty state."""
        key = self._resolve_under_root(library_root, path)
        repo = self._repo(db_conn, library_root)
        self._require_event_safe_transaction(repo)
        removed = repo.remove_file(key, require_clean_transaction=True)
        if removed:
            self._publish_asset_tags_changed(key, (), publish_catalog=True)
        self._reindex_search_documents((key,))

    @session_operation
    def rename_tag(self, library_root: str | Path, old_name: str, new_name: str,
                   db_conn: Connection | None = None) -> None:
        """Rename a tag across all files."""
        new_name = self.validate_tag_name(new_name, field="new_name")
        repo = self._repo(db_conn, library_root)
        self._require_event_safe_transaction(repo)
        paths = repo.get_files_by_tag(old_name)
        repo.rename_tag(old_name, new_name, require_clean_transaction=True)
        self._publish_asset_tags_batch_changed(tuple(paths))
        self._publish_tag_catalog_changed()
        self._reindex_search_documents(paths)

    @session_operation
    def delete_tag(self, library_root: str | Path, tag_name: str,
                   db_conn: Connection | None = None) -> None:
        """Delete a tag from all files."""
        repo = self._repo(db_conn, library_root)
        self._require_event_safe_transaction(repo)
        paths = repo.get_files_by_tag(tag_name)
        repo.delete_tag(tag_name, require_clean_transaction=True)
        self._publish_asset_tags_batch_changed(tuple(paths))
        self._publish_tag_catalog_changed()
        self._reindex_search_documents(paths)

    @session_operation
    def get_tags_for_tree(self, library_root: str | Path, dir_path: str | Path,
                          db_conn: Connection | None = None) -> list[str]:
        """Return all distinct tags for a directory and its descendants."""
        key = self._resolve_under_root(library_root, dir_path)
        repo = self._repo(db_conn, library_root)
        return repo.get_tags_for_tree(key)

    @session_operation
    def get_all_tags(self, library_root: str | Path,
                     db_conn: Connection | None = None,
                     *, source: TagSource = "human") -> list[str]:
        """Return all distinct tags in the library."""
        repo = self._repo(db_conn, library_root)
        return repo.get_all_tags(source=source)

    @session_operation
    def get_files_by_tag(self, library_root: str | Path, tag: str,
                         db_conn: Connection | None = None,
                         *, source: TagSource = "human") -> set[str]:
        """Return all file paths that have a given tag."""
        repo = self._repo(db_conn, library_root)
        return set(repo.get_files_by_tag(tag, source=source))

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


# ``TagServiceAdapter``'s root-bound adapter moved to the desktop port layer
# (``AssetsManager.application.desktop_ports.RootBoundTagService``).  This
# re-export is retained purely for backward compatibility with existing
# tests/docs that import the historical name from this module.
from AssetsManager.application.desktop_ports import RootBoundTagService as TagServiceAdapter  # noqa: E402, F401
