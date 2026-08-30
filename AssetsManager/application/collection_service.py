"""Collection application service — user collections and smart query views.

Collections are **query views / reference sets**: nothing in this service
moves, copies, or deletes files. Manual collections hold member path
references; smart collections hold a structured predicate JSON that is
evaluated against the ``assets`` index (the same repository query behind
``SearchService.search_structured_detailed``) plus a tag dimension computed
from ``TagService.get_files_by_tag`` intersection/union.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from sqlite3 import Connection
from typing import TYPE_CHECKING, Any

from AssetsManager.application.activity_recorder import ActivityRecorder, summarize_targets
from AssetsManager.application.context import ConnectionProvider, LibrarySession, session_operation
from AssetsManager.application.tag_service import TagService
from AssetsManager.core.database import DatabaseManager
from AssetsManager.core.path_resolver import root_identity
from AssetsManager.domain.errors import NotFoundError, OperationNotPermitted, ValidationError
from AssetsManager.domain.event_bus import get_event_bus
from AssetsManager.domain.events import CollectionChanged
from AssetsManager.repositories.asset_index_repository import AssetIndexEntry
from AssetsManager.repositories.collection_repository import CollectionRepository

if TYPE_CHECKING:
    from AssetsManager.application.search_index_service import SearchIndexService

_log = logging.getLogger(__name__)

_MAX_COLLECTION_NAME_LENGTH = 200

# Structured predicate keys understood by ``evaluate``. Everything else is a
# ValidationError so a typo in a saved smart query fails loudly instead of
# silently matching nothing.
_QUERY_KEYS = frozenset({
    "name_substring", "extensions", "size_min", "size_max",
    "mtime_after", "mtime_before", "tags", "tag_match", "order_by",
    # v39: full-text dimension over the asset_search FTS index (name/tags/
    # notes document per path), evaluated with the shared query syntax.
    "fts",
})
# Mirrors the repository's _STRUCTURED_ORDER_COLUMNS whitelist (minus the
# path column, which would leak absolute filesystem layout into results).
_QUERY_ORDER_COLUMNS = frozenset({"name", "size", "mtime"})

# Filter-then-page scan page size for tag-filtered smart evaluation.
_EVALUATE_SCAN_PAGE = 500


def _validated_collection_name(value: Any, *, field: str = "name") -> str:
    """Return one normalized collection name or raise a domain error."""
    if not isinstance(value, str):
        raise ValidationError(field, "must be a string")
    clean = value.strip()
    if not clean:
        raise ValidationError(field, "must not be empty")
    if len(clean) > _MAX_COLLECTION_NAME_LENGTH:
        raise ValidationError(
            field, f"must be at most {_MAX_COLLECTION_NAME_LENGTH} characters"
        )
    return clean


def _validated_query(query: Any) -> dict:
    """Validate and normalize one smart-collection predicate dict."""
    if not isinstance(query, dict):
        raise ValidationError("query", "must be an object")
    unknown = sorted(set(query) - _QUERY_KEYS)
    if unknown:
        raise ValidationError("query", f"unknown keys: {', '.join(unknown)}")

    clean: dict[str, Any] = {}
    name_substring = query.get("name_substring")
    if name_substring is not None:
        if not isinstance(name_substring, str):
            raise ValidationError("name_substring", "must be a string")
        clean["name_substring"] = name_substring

    extensions = query.get("extensions")
    if extensions is not None:
        if (
            not isinstance(extensions, list)
            or not all(isinstance(ext, str) for ext in extensions)
        ):
            raise ValidationError("extensions", "must be a list of strings")
        clean["extensions"] = extensions

    order_by = query.get("order_by")
    if order_by is not None:
        if order_by not in _QUERY_ORDER_COLUMNS:
            raise ValidationError(
                "order_by",
                f"must be one of {sorted(_QUERY_ORDER_COLUMNS)}",
            )
        clean["order_by"] = order_by

    for key in ("size_min", "size_max"):
        value = query.get(key)
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValidationError(key, "must be an integer")
        clean[key] = value
    for key in ("mtime_after", "mtime_before"):
        value = query.get(key)
        if value is None:
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValidationError(key, "must be a number")
        clean[key] = float(value)

    tags = query.get("tags")
    if tags is not None:
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise ValidationError("tags", "must be a list of strings")
        clean["tags"] = tags

    fts = query.get("fts")
    if fts is not None:
        if not isinstance(fts, str) or not fts.strip():
            raise ValidationError("fts", "must be a non-empty string")
        clean["fts"] = fts

    tag_match = query.get("tag_match")
    if tag_match is not None:
        if tag_match not in ("all", "any"):
            raise ValidationError("tag_match", "must be 'all' or 'any'")
        clean["tag_match"] = tag_match

    return clean


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
    raise RuntimeError(
        "CollectionService requires an explicit db_conn or ConnectionProvider."
    )


def _get_repo(
    db_conn: Connection | None,
    library_root: str | Path,
    connection_provider: ConnectionProvider | None = None,
) -> CollectionRepository:
    """Resolve a CollectionRepository from an explicit connection or root."""
    return CollectionRepository(
        _resolve_connection(db_conn, library_root, connection_provider)
    )


class CollectionService:
    """Read and mutate user collections through one application-layer API."""

    def __init__(
        self,
        connection_provider: ConnectionProvider | None = None,
        session: LibrarySession | None = None,
        *,
        asset_index_service: Any | None = None,
        tag_service: TagService | None = None,
        search_index_service: SearchIndexService | None = None,
        activity_recorder: ActivityRecorder | None = None,
    ):
        self._session = session
        self._asset_index_service = asset_index_service
        self._tag_service = tag_service
        self._search_index_service = search_index_service
        self._activity_recorder = activity_recorder
        self._repository: CollectionRepository | None = None
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
                    "CollectionService connection provider does not belong to "
                    "the LibrarySession"
                )
            self._connection_provider = expected_provider
            self._root_identity = session.context.root_identity
            self._repository = CollectionRepository.for_session(session)
        else:
            # Provider-only fake sessions remain on the raw compatibility path.
            self._connection_provider = connection_provider

    @classmethod
    def for_session(
        cls,
        session: LibrarySession,
        *,
        asset_index_service: Any | None = None,
        tag_service: TagService | None = None,
        search_index_service: SearchIndexService | None = None,
        activity_recorder: ActivityRecorder | None = None,
    ) -> "CollectionService":
        """Build the canonical collection service for one real session."""
        if not isinstance(session, LibrarySession):
            raise TypeError("CollectionService.for_session requires a real LibrarySession")
        return cls(
            connection_provider=session.connection_for,
            session=session,
            asset_index_service=asset_index_service,
            tag_service=tag_service,
            search_index_service=search_index_service,
            activity_recorder=activity_recorder,
        )

    def _repo(
        self,
        db_conn: Connection | None,
        library_root: str | Path,
    ) -> CollectionRepository:
        if isinstance(self._session, LibrarySession):
            requested = root_identity(library_root, strict=False)
            captured = self._root_identity
            if captured is None or requested.map_key != captured.map_key:
                # Domain error so the LAN error contract maps binding
                # mismatches to a mapped status instead of an unmapped 500.
                raise OperationNotPermitted(
                    "CollectionService library_root does not match the bound "
                    "LibrarySession"
                )
            expected = self._session.connection_for(captured)
            if db_conn is not None and db_conn is not expected:
                raise OperationNotPermitted(
                    "CollectionService connection does not belong to the bound "
                    "LibrarySession"
                )
            if self._repository is None or self._repository._conn is not expected:
                raise RuntimeError("CollectionService repository binding is unavailable")
            return self._repository
        return _get_repo(db_conn, library_root, self._connection_provider)

    def _require_event_safe_transaction(self, repo: CollectionRepository) -> None:
        """Reject outer transactions before publishing collection events."""
        if isinstance(self._session, LibrarySession) and repo._conn.in_transaction:
            raise RuntimeError(
                "CollectionService mutations require a clean transaction boundary"
            )

    def _publish_collection_changed(
        self,
        collection_id: int,
        kind: str,
        paths: tuple[str, ...] = (),
    ) -> None:
        if self._session is None:
            return
        get_event_bus().publish(CollectionChanged(
            library_root=self._session.root_str,
            session_token=self._session.event_token,
            collection_id=collection_id,
            kind=kind,
            paths=paths,
        ))

    def _record_activity(self, action: str, detail: str) -> None:
        if self._activity_recorder is None:
            return
        try:
            self._activity_recorder.record(action, detail)
        except Exception:
            # Activity recording must never fail the collection mutation.
            pass

    @staticmethod
    def validate_collection_name(value: str, *, field: str = "name") -> str:
        """Validate and normalize one collection name without persistence."""
        return _validated_collection_name(value, field=field)

    # ── Manual collections ───────────────────────────────────────

    @session_operation
    def create(
        self,
        library_root: str | Path,
        name: str,
        kind: str = "manual",
        db_conn: Connection | None = None,
    ) -> dict:
        """Create a manual (default) collection and publish its event."""
        name = self.validate_collection_name(name)
        repo = self._repo(db_conn, library_root)
        self._require_event_safe_transaction(repo)
        collection = repo.create(kind, name, "{}", require_clean_transaction=True)
        self._publish_collection_changed(collection["id"], collection["kind"])
        return collection

    @session_operation
    def create_smart(
        self,
        library_root: str | Path,
        name: str,
        query: dict,
        db_conn: Connection | None = None,
    ) -> dict:
        """Create a smart collection from one structured predicate dict."""
        name = self.validate_collection_name(name)
        clean_query = _validated_query(query)
        repo = self._repo(db_conn, library_root)
        self._require_event_safe_transaction(repo)
        collection = repo.create(
            "smart", name, json.dumps(clean_query),
            require_clean_transaction=True,
        )
        self._publish_collection_changed(collection["id"], collection["kind"])
        return collection

    @session_operation
    def update_query(
        self,
        library_root: str | Path,
        collection_id: int,
        query: dict,
        db_conn: Connection | None = None,
    ) -> None:
        """Replace the predicate JSON of an existing smart collection."""
        clean_query = _validated_query(query)
        repo = self._repo(db_conn, library_root)
        self._require_event_safe_transaction(repo)
        collection = repo.get(collection_id)
        if collection is None:
            raise NotFoundError("collection", str(collection_id))
        if collection["kind"] != "smart":
            raise ValidationError("kind", "only smart collections carry a query")
        repo.set_query(
            collection_id, json.dumps(clean_query),
            require_clean_transaction=True,
        )
        self._publish_collection_changed(collection_id, collection["kind"])

    @session_operation
    def rename(
        self,
        library_root: str | Path,
        collection_id: int,
        new_name: str,
        db_conn: Connection | None = None,
    ) -> None:
        """Rename a collection (duplicate names raise DuplicateError)."""
        new_name = self.validate_collection_name(new_name, field="new_name")
        repo = self._repo(db_conn, library_root)
        self._require_event_safe_transaction(repo)
        collection = repo.get(collection_id)
        if collection is None:
            raise NotFoundError("collection", str(collection_id))
        repo.rename(collection_id, new_name, require_clean_transaction=True)
        self._publish_collection_changed(collection_id, collection["kind"])

    @session_operation
    def delete(
        self,
        library_root: str | Path,
        collection_id: int,
        db_conn: Connection | None = None,
    ) -> None:
        """Delete a collection; membership rows cascade, files stay put."""
        repo = self._repo(db_conn, library_root)
        self._require_event_safe_transaction(repo)
        collection = repo.get(collection_id)
        if collection is None:
            raise NotFoundError("collection", str(collection_id))
        repo.delete(collection_id, require_clean_transaction=True)
        self._publish_collection_changed(collection_id, collection["kind"])

    @session_operation
    def list_collections(
        self,
        library_root: str | Path,
        db_conn: Connection | None = None,
    ) -> list[dict]:
        """Return all collections with member counts, sorted by name."""
        repo = self._repo(db_conn, library_root)
        return repo.list_collections()

    @session_operation
    def get_members(
        self,
        library_root: str | Path,
        collection_id: int,
        db_conn: Connection | None = None,
    ) -> list[dict]:
        """Return membership rows ordered by insertion time.

        Deleted-on-disk member paths are **not** pruned automatically: each
        row carries an ``exists`` flag so consumers can skip absent files
        while keeping the reference set intact. Returns [] for smart
        collections (their membership is defined by the query, not rows).
        """
        repo = self._repo(db_conn, library_root)
        if repo.get(collection_id) is None:
            raise NotFoundError("collection", str(collection_id))
        members = repo.get_members(collection_id)
        for member in members:
            member["exists"] = os.path.exists(member["file_path"])
        return members

    @session_operation
    def add_files(
        self,
        library_root: str | Path,
        collection_id: int,
        paths: list[str | Path],
        db_conn: Connection | None = None,
    ) -> int:
        """Add member references (batch, de-duplicated) to a collection.

        Rejects smart collections: their membership is query-defined. The
        repository resolves/contains-checks each path; files themselves are
        never touched. Returns the number of newly inserted references.
        """
        if not paths:
            return 0
        repo = self._repo(db_conn, library_root)
        self._require_event_safe_transaction(repo)
        collection = repo.get(collection_id)
        if collection is None:
            raise NotFoundError("collection", str(collection_id))
        if collection["kind"] != "manual":
            raise ValidationError(
                "kind", "smart collections do not accept manual members"
            )
        added = repo.add_members(
            collection_id, [str(p) for p in paths],
            require_clean_transaction=True,
        )
        if added:
            resolved = [str(Path(p).resolve()) for p in paths]
            self._publish_collection_changed(
                collection_id, collection["kind"], tuple(resolved)
            )
            self._record_activity(
                "collection_add",
                f"{collection['name']} <- {summarize_targets(resolved)}",
            )
        return added

    @session_operation
    def remove_files(
        self,
        library_root: str | Path,
        collection_id: int,
        paths: list[str | Path],
        db_conn: Connection | None = None,
    ) -> int:
        """Remove member references from a collection (files stay put)."""
        if not paths:
            return 0
        repo = self._repo(db_conn, library_root)
        self._require_event_safe_transaction(repo)
        collection = repo.get(collection_id)
        if collection is None:
            raise NotFoundError("collection", str(collection_id))
        if collection["kind"] != "manual":
            raise ValidationError(
                "kind", "smart collections do not hold manual members"
            )
        removed = repo.remove_members(
            collection_id, [str(p) for p in paths],
            require_clean_transaction=True,
        )
        if removed:
            resolved = [str(Path(p).resolve()) for p in paths]
            self._publish_collection_changed(
                collection_id, collection["kind"], tuple(resolved)
            )
            self._record_activity(
                "collection_remove",
                f"{collection['name']} <- {summarize_targets(resolved)}",
            )
        return removed

    # ── Smart evaluation ─────────────────────────────────────────

    @session_operation
    def evaluate(
        self,
        library_root: str | Path,
        collection_id: int,
        limit: int = 200,
        offset: int = 0,
        db_conn: Connection | None = None,
    ) -> list[AssetIndexEntry]:
        """Evaluate a smart collection against the assets index.

        Reuses the structured repository query behind
        ``SearchService.search_structured_detailed`` (via the injected
        ``AssetIndexService``); the optional ``tags`` dimension is applied
        in-memory from ``TagService.get_files_by_tag`` with ``tag_match``
        ``all`` (default: intersection) or ``any`` (union). Missing index
        entries are simply absent — evaluation is a read over the index and
        never touches the filesystem. Only indexed files can appear, which
        doubles as the "skip deleted members" guarantee for smart views.
        """
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValidationError("limit", "must be a positive integer")
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValidationError("offset", "must be a non-negative integer")
        repo = self._repo(db_conn, library_root)
        collection = repo.get(collection_id)
        if collection is None:
            raise NotFoundError("collection", str(collection_id))
        if collection["kind"] != "smart":
            raise ValidationError("kind", "only smart collections can be evaluated")
        try:
            query = _validated_query(json.loads(collection["query_json"]))
        except json.JSONDecodeError as exc:
            raise ValidationError("query_json", "is not valid JSON") from exc

        structured_kwargs: dict[str, Any] = {
            "name_substring": query.get("name_substring"),
            "extensions": query.get("extensions"),
            "size_min": query.get("size_min"),
            "size_max": query.get("size_max"),
            "mtime_after": query.get("mtime_after"),
            "mtime_before": query.get("mtime_before"),
            "order_by": query.get("order_by", "name"),
        }
        tags = query.get("tags") or []
        tag_match = query.get("tag_match", "all")
        fts_text = query.get("fts")

        allowed = self._allowed_tag_paths(library_root, tags, tag_match)
        fts_allowed = self._allowed_fts_paths(fts_text)
        if fts_allowed is not None:
            # Combine independent dimensions by intersection; an empty set
            # short-circuits below without scanning the index.
            allowed = fts_allowed if allowed is None else (allowed & fts_allowed)

        index_service = self._require_index_service()
        if allowed is None:
            # No tag dimension: the repository query paginates natively.
            return list(index_service.search_structured(
                library_root, limit=limit, offset=offset, **structured_kwargs,
            ))
        if not allowed:
            # A tag dimension that matches nothing: short-circuit without
            # scanning the index.
            return []

        # Tag-filtered evaluation streams index pages in the same
        # deterministic order and applies the filter before paging, so
        # ``offset``/``limit`` stay correct without materializing the index.
        needed = offset + limit
        collected: list[AssetIndexEntry] = []
        scan_offset = 0
        while len(collected) < needed:
            page = index_service.search_structured(
                library_root,
                limit=_EVALUATE_SCAN_PAGE,
                offset=scan_offset,
                **structured_kwargs,
            )
            if not page:
                break
            collected.extend(
                entry for entry in page if entry.file_path in allowed
            )
            scan_offset += len(page)
            if len(page) < _EVALUATE_SCAN_PAGE:
                break
        return collected[offset:offset + limit]

    def _allowed_fts_paths(self, fts_text: str | None) -> set[str] | None:
        """Return the full-text dimension path set, or None when absent.

        The query text runs through the shared FTS syntax parser against the
        ``asset_search`` index (migration v39). Requires a SearchIndexService
        — a saved query with an ``fts`` dimension is a hard error without
        one, never silently ignored (mirrors the tag-dimension contract).
        Lookup failures degrade to "matches nothing" inside the maintainer,
        so evaluation stays a read that never raises infrastructure errors.
        """
        if fts_text is None:
            return None
        if self._search_index_service is None:
            raise ValidationError(
                "fts", "evaluating an fts dimension requires a SearchIndexService"
            )
        return set(self._search_index_service.search_file_paths(fts_text))

    def _require_index_service(self) -> Any:
        if self._asset_index_service is None:
            raise RuntimeError(
                "CollectionService smart evaluation requires an AssetIndexService"
            )
        return self._asset_index_service

    def _allowed_tag_paths(
        self, library_root: str | Path, tags: list[str], tag_match: str
    ) -> set[str] | None:
        """Return the tag-dimension path set, or None when tags are absent.

        ``all`` intersects every tag's file set (the empty-intersection
        short-circuit prevents a full index scan when one tag matches
        nothing); ``any`` unions. Requires a TagService — a saved query with
        a tag dimension is a hard error without one, never silently ignored.
        """
        if not tags:
            return None
        if self._tag_service is None:
            raise ValidationError(
                "tags", "evaluating a tag dimension requires a TagService"
            )
        sets = [
            set(self._tag_service.get_files_by_tag(library_root, tag))
            for tag in tags
        ]
        if tag_match == "any":
            union: set[str] = set()
            for path_set in sets:
                union |= path_set
            return union
        intersection = sets[0]
        for path_set in sets[1:]:
            intersection &= path_set
            if not intersection:
                break
        return intersection
