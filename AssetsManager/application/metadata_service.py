"""Metadata application service."""
from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Connection
from typing import TYPE_CHECKING

from AssetsManager.application.context import ConnectionProvider, LibrarySession, session_operation
from AssetsManager.core.database import DatabaseManager
from AssetsManager.core.path_resolver import RootIdentity, root_identity
from AssetsManager.core.project_data import ProjectData, _SIZE_CACHE_TTL_SECONDS
from AssetsManager.domain.errors import OperationNotPermitted, PathEscapeError
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import (
    AssetNotesChanged, AssetRatingChanged, AssetUrlsChanged,
)
from AssetsManager.repositories.metadata_repository import MetadataRepository
from AssetsManager.repositories.tag_repository import TagRepository

if TYPE_CHECKING:
    from AssetsManager.application.search_index_service import SearchIndexService

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AssetMetadata:
    path: Path
    tags: tuple[str, ...]
    notes: str
    urls: tuple[str, ...]
    rating: int | None = None


class MetadataService:
    """Read and write per-asset metadata.

    Uses MetadataRepository for file_meta operations and
    TagRepository for tag reads.
    """

    def __init__(
        self,
        connection_provider: ConnectionProvider | None = None,
        session: LibrarySession | None = None,
        search_index_service: SearchIndexService | None = None,
    ):
        self._binding_lock = threading.RLock()
        self._connection_provider = connection_provider
        self._session: LibrarySession | None = None
        self._root_identity: RootIdentity | None = None
        self._repository: MetadataRepository | None = None
        self._tag_repository: TagRepository | None = None
        # FTS index maintainer (migration v39); optional so legacy/fake
        # constructions keep working without the fourth search source.
        self._search_index_service = search_index_service
        # Timestamps of the last size (re)computation per canonical path key.
        # Mirrors ProjectData._size_cache_ts so the persisted size cache is
        # only trusted inside the TTL window (see _size_cache_fresh).
        self._size_cache_ts: dict[str, float] = {}
        self._size_cache_lock = threading.Lock()
        if session is not None:
            self._bind_session(session, connection_provider=connection_provider)

    @classmethod
    def for_session(
        cls,
        session: LibrarySession,
        search_index_service: SearchIndexService | None = None,
    ) -> "MetadataService":
        """Build the canonical metadata service for one real session."""
        return cls(
            connection_provider=session.connection_for,
            session=session,
            search_index_service=search_index_service,
        )

    def _bind_session(
        self,
        session: LibrarySession,
        *,
        connection_provider: ConnectionProvider | None = None,
    ) -> None:
        if not isinstance(session, LibrarySession):
            raise TypeError("MetadataService requires a real LibrarySession")
        provider = connection_provider or session.connection_for
        if not callable(provider):
            raise TypeError("MetadataService requires a callable ConnectionProvider")
        identity = session.context.root_identity

        with self._binding_lock:
            if self._session is not None:
                if self._session is session:
                    return
                raise RuntimeError(
                    "MetadataService is already bound to another LibrarySession"
                )
            with session.operation():
                conn = session.connection_for(identity)
                conn = DatabaseManager.require_managed_connection_owner(
                    identity, conn
                )
                # Binding mismatches raise domain errors so the LAN error
                # contract maps them instead of leaking unmapped 500s
                # (minimal ValueError migration; message text preserved).
                if provider(identity.display_path) is not conn:
                    raise OperationNotPermitted(
                        "MetadataService connection provider does not belong "
                        "to the LibrarySession"
                    )
                repository = MetadataRepository.for_session(session)
                if repository._conn is not conn:
                    raise OperationNotPermitted(
                        "MetadataRepository connection does not match MetadataService"
                    )
                tag_repository = TagRepository.for_session(session)
                if tag_repository._conn is not conn:
                    raise OperationNotPermitted(
                        "TagRepository connection does not match MetadataService"
                    )

                def publish_binding() -> None:
                    self._connection_provider = session.connection_for
                    self._root_identity = identity
                    self._repository = repository
                    self._tag_repository = tag_repository
                    self._session = session

                session._publish_while_live(publish_binding)

    def _connection(self, library_root: str | Path) -> Connection:
        identity = root_identity(library_root, strict=False)
        if self._session is not None:
            if (
                self._root_identity is None
                or identity.map_key != self._root_identity.map_key
            ):
                raise OperationNotPermitted(
                    "MetadataService library_root does not match "
                    "the bound LibrarySession"
                )
            if self._repository is None:
                raise RuntimeError("MetadataService repository binding is unavailable")
            return self._repository._conn

        root = str(identity.display_path)
        if self._connection_provider is not None:
            conn = self._connection_provider(root)
            return DatabaseManager.validate_connection_owner(
                identity, conn, allow_unmanaged=True
            )
        raise RuntimeError("MetadataService requires an explicit ConnectionProvider.")

    def _repo(self, library_root: str | Path) -> MetadataRepository:
        """Return the retained bound repository or a raw legacy adapter."""
        conn = self._connection(library_root)
        if self._session is not None:
            if self._repository is None or self._repository._conn is not conn:
                raise RuntimeError("MetadataService repository binding is unavailable")
            return self._repository
        return MetadataRepository(conn)

    @staticmethod
    def _resolve_under_root(
        library_root: str | Path, path: str | Path
    ) -> tuple[Path, Path]:
        """Resolve a library root and reject paths outside that root."""
        root = Path(library_root).resolve()
        target = Path(path).resolve()
        if not target.is_relative_to(root):
            # Domain escape error so the LAN error contract maps it to a 400
            # instead of an unmapped 500 (minimal ValueError migration).
            raise PathEscapeError(str(target), str(root))
        return root, target

    @classmethod
    def _resolve_many_under_root(
        cls, library_root: str | Path, paths: Sequence[str | Path]
    ) -> tuple[Path, list[Path]]:
        root = Path(library_root).resolve()
        targets = [cls._resolve_under_root(root, path)[1] for path in paths]
        return root, targets

    def _publish_notes_changed(self, file_path: str) -> None:
        if self._session is None:
            return
        get_event_bus().publish(AssetNotesChanged(
            library_root=self._session.root_str,
            session_token=self._session.event_token,
            file_path=file_path,
        ))

    def _publish_urls_changed(self, file_path: str, urls: tuple[str, ...]) -> None:
        if self._session is None:
            return
        get_event_bus().publish(AssetUrlsChanged(
            library_root=self._session.root_str,
            session_token=self._session.event_token,
            file_path=file_path,
            new_urls=urls,
        ))

    def _publish_rating_changed(self, file_path: str, rating: int | None) -> None:
        if self._session is None:
            return
        get_event_bus().publish(AssetRatingChanged(
            library_root=self._session.root_str,
            session_token=self._session.event_token,
            file_path=file_path,
            rating=rating,
        ))

    def _reindex_search_document(self, file_path: str) -> None:
        """Refresh the ``asset_search`` document for one path; never raises.

        Notes participate in the FTS document (urls currently do not, but
        the doc is re-aggregated at every metadata save so future indexed
        columns stay correct). The maintainer swallows its own failures;
        this guard keeps bookkeeping strictly non-essential.
        """
        service = self._search_index_service
        if service is None:
            return
        try:
            service.reindex_file(file_path)
        except Exception:  # pragma: no cover - defensive, service never raises
            _log.warning("Search index reindex hook failed", exc_info=True)

    def _require_event_safe_transaction(self, repo: MetadataRepository) -> None:
        """Reject caller-owned transactions before publishing metadata events.

        The bound repository deliberately preserves an outer transaction.  A
        service-level metadata event, however, cannot be deferred until an
        arbitrary caller later commits that transaction.  Fail closed rather
        than publish a notification for a write that may roll back.
        Raw compatibility services retain their historical behavior.

        Sampled under the connection-owned write gate — same reconciliation-
        worker race as CollectionService/TagService: an unlocked
        ``in_transaction`` peek can observe the worker's short transaction on
        the shared connection and reject a mutation that owns no outer
        transaction (deterministically reproduced by the round-3 recheck).
        """
        if self._session is None:
            return
        from AssetsManager.core.database import db_write_lock

        with db_write_lock(repo._conn):
            in_transaction = repo._conn.in_transaction
        if in_transaction:
            raise RuntimeError(
                "MetadataService metadata mutations require a clean transaction "
                "boundary"
            )

    @session_operation
    def get_metadata(self, library_root: str | Path, path: str | Path) -> AssetMetadata:
        root_path, target = self._resolve_under_root(library_root, path)
        root = str(root_path)
        meta_repo = self._repo(root)
        tag_repo = (
            self._tag_repository
            if self._session is not None and self._tag_repository is not None
            else TagRepository(meta_repo._conn)
        )
        notes, urls, rating = meta_repo.get_notes_urls_rating(str(target))
        return AssetMetadata(
            path=target,
            tags=tuple(tag_repo.get_tags(str(target))),
            notes=notes,
            urls=tuple(urls),
            rating=rating,
        )

    @session_operation
    def get_notes(self, library_root: str | Path, path: str | Path) -> str:
        root, target = self._resolve_under_root(library_root, path)
        return self._repo(root).get_notes(str(target))

    @session_operation
    def set_notes(self, library_root: str | Path, path: str | Path, text: str) -> None:
        root, target = self._resolve_under_root(library_root, path)
        key = str(target)
        repo = self._repo(root)
        self._require_event_safe_transaction(repo)
        repo.set_notes(key, text)
        self._reindex_search_document(key)
        self._publish_notes_changed(key)

    @session_operation
    def get_urls(self, library_root: str | Path, path: str | Path) -> list[str]:
        root, target = self._resolve_under_root(library_root, path)
        return self._repo(root).get_urls(str(target))

    @session_operation
    def add_url(self, library_root: str | Path, path: str | Path, url: str) -> None:
        root_path, target = self._resolve_under_root(library_root, path)
        root = str(root_path)
        key = str(target)
        repo = self._repo(root)
        self._require_event_safe_transaction(repo)
        urls = repo.add_url(key, url)
        if urls is not None:
            result = tuple(urls)
            self._publish_urls_changed(key, result)
            self._reindex_search_document(key)

    @session_operation
    def remove_url(self, library_root: str | Path, path: str | Path, url: str) -> None:
        root_path, target = self._resolve_under_root(library_root, path)
        root = str(root_path)
        key = str(target)
        repo = self._repo(root)
        self._require_event_safe_transaction(repo)
        urls = repo.remove_url(key, url)
        if urls is not None:
            result = tuple(urls)
            self._publish_urls_changed(key, result)
            self._reindex_search_document(key)

    # ── Rating ──────────────────────────────────────────────────

    @session_operation
    def get_rating(self, library_root: str | Path, path: str | Path) -> int | None:
        """Return the 0-5 rating for a path, or None when unrated."""
        root, target = self._resolve_under_root(library_root, path)
        return self._repo(root).get_rating(str(target))

    @session_operation
    def set_rating(
        self, library_root: str | Path, path: str | Path, rating: int | None
    ) -> None:
        """Set (or clear) the 0-5 rating for a path and publish the change.

        ``rating=None`` clears the rating back to unrated. Values outside
        0-5 raise :class:`ValueError` (rejected before any write).
        """
        if rating is not None and not (
            isinstance(rating, int)
            and not isinstance(rating, bool)
            and 0 <= rating <= 5
        ):
            raise ValueError(
                f"rating must be an integer 0-5 or None, got {rating!r}"
            )
        root, target = self._resolve_under_root(library_root, path)
        key = str(target)
        repo = self._repo(root)
        self._require_event_safe_transaction(repo)
        repo.set_rating(key, rating)
        self._publish_rating_changed(key, rating)

    @session_operation
    def get_dir_size(self, library_root: str | Path, dir_path: str | Path,
                     force: bool = False,
                     cancel_token: Callable[[], bool] | None = None,
                     ) -> tuple[int, bool]:
        root_path, target_path = self._resolve_under_root(library_root, dir_path)
        root = str(root_path)
        target = str(target_path)
        repo = self._repo(root)
        if not force and target == root:
            total = repo.get_library_total_size(root)
            # The library root has no directory mtime probe; the TTL window
            # alone guarantees that in-place edits refresh the total.
            if total > 0 and self._size_cache_fresh(root):
                return (total, True)
        if not os.path.isdir(target):
            return (0, False)
        if not force:
            cached = repo.get_cached_size(target)
            if cached is not None:
                try:
                    current_mtime = os.path.getmtime(target)
                except OSError:
                    return (0, False)
                # The mtime check alone cannot detect in-place file edits
                # (they leave the directory mtime untouched), so the cached
                # value is additionally trusted only inside the TTL window.
                if cached[1] >= current_mtime and self._size_cache_fresh(target):
                    return (cached[0], True)
        size = ProjectData.compute_dir_size(target, cancel_token=cancel_token)
        if cancel_token is not None and cancel_token():
            # A cancelled walk returned a partial total; never persist it.
            return (size, False)
        try:
            mtime = os.path.getmtime(target)
        except OSError:
            mtime = 0.0
        repo.set_cached_size(target, size, mtime)
        self._mark_size_cached(target)
        return (size, False)

    @session_operation
    def set_dir_size(self, library_root: str | Path, dir_path: str | Path, size: int) -> None:
        root_path, target_path = self._resolve_under_root(library_root, dir_path)
        root = str(root_path)
        target = str(target_path)
        mtime = os.path.getmtime(target) if os.path.exists(target) else 0.0
        self._repo(root).set_cached_size(target, size, mtime)
        self._mark_size_cached(target)

    def _size_cache_fresh(self, key: str) -> bool:
        """Return True while the size for ``key`` is inside the TTL window.

        Mirrors the ProjectData.get_dir_size TTL semantics: the persisted
        size cache is only trusted for ``_SIZE_CACHE_TTL_SECONDS`` after the
        last (re)computation, so in-place edits that do not change the
        directory mtime still force a refresh.
        """
        with self._size_cache_lock:
            computed_at = self._size_cache_ts.get(key)
        return (
            computed_at is not None
            and time.time() - computed_at < _SIZE_CACHE_TTL_SECONDS
        )

    def _mark_size_cached(self, key: str) -> None:
        """Record that the persisted size for ``key`` was just (re)computed."""
        now = time.time()
        with self._size_cache_lock:
            self._size_cache_ts[key] = now
            # Opportunistic sweep: entries past the TTL can never satisfy
            # _size_cache_fresh again, so drop them instead of growing the
            # map with every directory ever probed this session.
            expired = [
                cached_key
                for cached_key, computed_at in self._size_cache_ts.items()
                if now - computed_at >= _SIZE_CACHE_TTL_SECONDS
            ]
            for cached_key in expired:
                del self._size_cache_ts[cached_key]

    @staticmethod
    def _canonical_path_key(path: str | Path) -> str:
        """Return the canonical key used by the metadata repository."""
        return str(Path(path).resolve())

    @classmethod
    def _canonicalize_path_keys(
        cls, paths: Sequence[str | Path], caller_paths: Sequence[str | Path]
    ) -> tuple[list[str], dict[str, list[str]]]:
        """Canonicalize query keys and retain their caller-facing spellings."""
        canonical_paths = [cls._canonical_path_key(path) for path in paths]
        caller_keys: dict[str, list[str]] = {}
        for canonical, caller in zip(canonical_paths, (str(path) for path in caller_paths), strict=True):
            caller_keys.setdefault(canonical, []).append(caller)
        return canonical_paths, caller_keys

    @session_operation
    def get_cached_stats(
        self, library_root: str | Path, file_paths: list[str]
    ) -> dict[str, tuple[int, float]]:
        """Return cached stats under the keys supplied by the caller."""
        if not file_paths:
            return {}
        root, targets = self._resolve_many_under_root(library_root, file_paths)
        canonical_paths, caller_keys = self._canonicalize_path_keys(targets, file_paths)
        cached = self._repo(root).get_cached_stats(canonical_paths)
        return {
            caller_key: value
            for path, value in cached.items()
            for caller_key in caller_keys[path]
        }

    @session_operation
    def get_cached_file_count(self, library_root: str | Path, dir_path: str | Path) -> int | None:
        """Return cached file count for a directory, or None if not cached."""
        root, target = self._resolve_under_root(library_root, dir_path)
        return self._repo(root).get_cached_file_count(str(target))

    @session_operation
    def get_library_total_size(self, library_root: str | Path) -> int:
        """Return total size from library_stats, or 0 if not available."""
        root = str(Path(library_root).resolve())
        return self._repo(root).get_library_total_size(root)

    @session_operation
    def set_library_total_size(self, library_root: str | Path, size: int) -> None:
        """Persist the current aggregate size for one library root."""
        if size < 0:
            raise ValueError("Library total size cannot be negative")
        root = str(Path(library_root).resolve())
        self._repo(root).set_library_total_size(root, int(size))
        # Refresh the root TTL so a fresh total is served by get_dir_size
        # instead of triggering an immediate full-library recompute.
        self._mark_size_cached(root)

    @session_operation
    def batch_get_cached_file_counts(self, library_root: str, dir_paths: list[str]) -> dict[str, int]:
        """Return cached file counts under the keys supplied by the caller."""
        if not dir_paths:
            return {}
        root, targets = self._resolve_many_under_root(library_root, dir_paths)
        canonical_paths, caller_keys = self._canonicalize_path_keys(targets, dir_paths)
        cached = self._repo(root).batch_get_cached_file_counts(canonical_paths)
        return {
            caller_key: value
            for path, value in cached.items()
            for caller_key in caller_keys[path]
        }

    @session_operation
    def batch_set_cached_file_counts(self, library_root: str, entries: dict[str, int]) -> None:
        """Cache file counts for multiple directories in a single transaction."""
        if not entries:
            return
        root, targets = self._resolve_many_under_root(library_root, list(entries))
        canonical_entries = {
            str(target): count
            for target, count in zip(targets, entries.values(), strict=True)
        }
        self._repo(root).batch_set_cached_file_counts(canonical_entries)
