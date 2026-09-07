"""Search application service."""
from __future__ import annotations

import os
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from time import monotonic, perf_counter
from typing import TYPE_CHECKING, Iterable, Protocol, cast

from AssetsManager.application.asset_index_service import AssetIndexService
from AssetsManager.application.context import ConnectionProvider, LibrarySession, session_operation
from AssetsManager.application.search_syntax import parse_query
from AssetsManager.core.database import DatabaseManager
from AssetsManager.core.format_utils import CATEGORY_MAP
from AssetsManager.core.path_resolver import root_identity
from AssetsManager.core.performance import PerformanceRecorder
from AssetsManager.core.session_contract import require_library_session
from AssetsManager.repositories.asset_index_repository import AssetIndexRepository
from AssetsManager.repositories.tag_repository import TagRepository

if TYPE_CHECKING:
    from AssetsManager.application.search_index_service import SearchIndexService
    from AssetsManager.repositories.asset_index_repository import AssetIndexEntry


class _Scanner(Protocol):
    def search(self, query: str, limit: int = 200) -> list[dict]: ...


def _category_for_extension(extension: str) -> str:
    """Resolve one extension against the live CATEGORY_MAP snapshot."""
    # LiveCategoryMap.get loses its default's declared type (core.format_utils);
    # a string default can never resolve to None.
    return cast(str, CATEGORY_MAP.get(extension, "other"))


@dataclass(frozen=True)
class SearchResult:
    name: str
    path: str
    extension: str
    category: str

    @property
    def thumbnail_path(self) -> str:
        """Relative asset reference; transport layers decide how to expose it."""
        return self.path


@dataclass(frozen=True)
class QuickSearchResult:
    """A bounded, filesystem-safe result for the LAN command palette."""

    name: str
    path: str
    type: str
    extension: str
    category: str


_QUICK_SEARCH_DEFAULT_LIMIT = 20
_QUICK_SEARCH_MAX_LIMIT = 100
_QUICK_SEARCH_MAX_DIRECTORIES = 512
_QUICK_SEARCH_MAX_ENTRIES = 10_000
_QUICK_SEARCH_MAX_MATCHES = 1_000
_QUICK_SEARCH_BUDGET_SECONDS = 0.075


class SearchStatus(str, Enum):
    """Detailed outcome of one search source or an aggregate search."""

    COMPLETE = "complete"
    EMPTY = "empty"
    INVALID_INPUT = "invalid_input"
    UNAVAILABLE = "unavailable"
    ERROR = "error"
    PARTIAL = "partial"
    DEGRADED = "degraded"
    PATH_REJECTED = "path_rejected"


@dataclass(frozen=True)
class SearchError:
    """Safe, stable diagnostic information for a search failure."""

    code: str
    source: str
    recoverable: bool = False


@dataclass(frozen=True)
class SearchSourceStatus:
    """Status and counters for one source in a detailed result set."""

    source: str
    status: SearchStatus
    result_count: int
    dropped_count: int = 0
    error_count: int = 0


@dataclass(frozen=True)
class SearchResultSet:
    """Detailed search result contract kept beside the legacy list API.

    ``results`` is immutable so a transport or UI consumer cannot change the
    diagnostic counts after the search has completed. The existing search
    methods still return ``list[SearchResult]``; callers that need to
    distinguish empty, unavailable, partial, and degraded results can use the
    corresponding ``*_detailed`` method.
    """

    results: tuple[SearchResult, ...]
    status: SearchStatus
    sources: tuple[SearchSourceStatus, ...] = ()
    errors: tuple[SearchError, ...] = ()
    dropped_count: int = 0
    fallback_used: bool = False

    @property
    def count(self) -> int:
        return len(self.results)

    @property
    def is_complete(self) -> bool:
        """Whether the source(s) completed without degraded diagnostics."""
        return self.status in {SearchStatus.COMPLETE, SearchStatus.EMPTY}

    @property
    def telemetry_outcome(self) -> str:
        """Map detailed status to the pre-existing telemetry vocabulary."""
        if self.status in {SearchStatus.COMPLETE, SearchStatus.EMPTY}:
            return "success"
        if self.status is SearchStatus.INVALID_INPUT:
            return "invalid_input"
        if self.status is SearchStatus.UNAVAILABLE:
            return "unavailable"
        return "error"

    def as_list(self) -> list[SearchResult]:
        """Return a mutable compatibility copy for the legacy callers."""
        return list(self.results)

    @classmethod
    def from_source(
        cls,
        source: str,
        results: Iterable[SearchResult] = (),
        *,
        status: SearchStatus | None = None,
        errors: Iterable[SearchError] = (),
        dropped_count: int = 0,
        fallback_used: bool = False,
    ) -> SearchResultSet:
        """Build a result set for one source and derive a safe default status."""
        result_tuple = tuple(results)
        error_tuple = tuple(errors)
        if status is None:
            if error_tuple:
                status = SearchStatus.PARTIAL if result_tuple else SearchStatus.ERROR
            elif dropped_count:
                status = SearchStatus.PARTIAL if result_tuple else SearchStatus.PATH_REJECTED
            else:
                status = SearchStatus.COMPLETE if result_tuple else SearchStatus.EMPTY
        source_status = SearchSourceStatus(
            source=source,
            status=status,
            result_count=len(result_tuple),
            dropped_count=dropped_count,
            error_count=len(error_tuple),
        )
        return cls(
            results=result_tuple,
            status=status,
            sources=(source_status,),
            errors=error_tuple,
            dropped_count=dropped_count,
            fallback_used=fallback_used,
        )

    @classmethod
    def merge(
        cls,
        *result_sets: SearchResultSet,
        fallback_used: bool = False,
    ) -> SearchResultSet:
        """Aggregate primary/fallback sources without hiding source failures."""
        if not result_sets:
            raise ValueError("At least one search result set is required")

        results: list[SearchResult] = []
        seen_paths: set[str] = set()
        sources: list[SearchSourceStatus] = []
        errors: list[SearchError] = []
        dropped_count = 0
        used_fallback = fallback_used or any(result_set.fallback_used for result_set in result_sets)

        for result_set in result_sets:
            sources.extend(result_set.sources)
            errors.extend(result_set.errors)
            dropped_count += result_set.dropped_count
            for result in result_set.results:
                if result.path in seen_paths:
                    continue
                seen_paths.add(result.path)
                results.append(result)

        statuses = {result_set.status for result_set in result_sets}
        failed = bool(statuses & {SearchStatus.ERROR, SearchStatus.UNAVAILABLE})
        invalid_only = statuses == {SearchStatus.INVALID_INPUT}
        if invalid_only:
            status = SearchStatus.INVALID_INPUT
        elif failed:
            status = (
                SearchStatus.DEGRADED
                if used_fallback or len(result_sets) > 1
                else SearchStatus.ERROR
            )
        elif SearchStatus.PARTIAL in statuses:
            status = SearchStatus.PARTIAL if results else SearchStatus.PATH_REJECTED
        elif SearchStatus.PATH_REJECTED in statuses:
            status = SearchStatus.PATH_REJECTED if not results else SearchStatus.PARTIAL
        else:
            status = SearchStatus.COMPLETE if results else SearchStatus.EMPTY

        return cls(
            results=tuple(results),
            status=status,
            sources=tuple(sources),
            errors=tuple(errors),
            dropped_count=dropped_count,
            fallback_used=used_fallback,
        )


def _contained_relative_path(
    library_root: Path,
    file_path: str,
    resolved_root: Path | None = None,
) -> str | None:
    """Return a safe relative asset path, or reject a contaminated index row.

    ``resolved_root`` accepts the caller's already-resolved ``library_root`` so
    per-row loops do not pay a second ``Path.resolve()`` (a Windows final-path
    syscall) for a loop-invariant value; when omitted the root is resolved here
    exactly as before.
    """
    try:
        root = (
            resolved_root
            if resolved_root is not None
            else library_root.resolve(strict=False)
        )
        raw_path = os.fspath(file_path)
        candidate = Path(raw_path) if os.path.isabs(raw_path) else root / raw_path
        candidate = candidate.resolve(strict=False)
        candidate_text = os.path.normpath(os.fspath(candidate))
        root_text = os.path.normpath(os.fspath(root))
        if os.path.normcase(os.path.commonpath((root_text, candidate_text))) != os.path.normcase(root_text):
            return None
    except (OSError, RuntimeError, ValueError):
        return None

    relative = os.path.relpath(candidate_text, root_text)
    if relative in ("", ".") or relative == os.pardir or relative.startswith(os.pardir + os.sep):
        return None
    return relative.replace("\\", "/")


def _append_error(errors: list[SearchError], error: SearchError) -> None:
    """Keep diagnostics bounded and free of repeated sensitive detail."""
    if error not in errors:
        errors.append(error)


class SearchService:
    """Search assets by tags or name."""

    def __init__(
        self,
        performance_recorder: PerformanceRecorder | None = None,
        session_token: str | None = None,
        connection_provider: ConnectionProvider | None = None,
        session: LibrarySession | None = None,
        asset_index_service: AssetIndexService | None = None,
        search_index_service: SearchIndexService | None = None,
    ) -> None:
        self._performance_recorder = (
            performance_recorder if performance_recorder is not None and performance_recorder.enabled else None
        )
        self._session_token = session_token
        self._session = session
        self._asset_index_service = asset_index_service
        # FTS fourth source (migration v39); optional so legacy/fake
        # constructions keep their exact previous behavior without it.
        self._search_index_service = search_index_service
        self._tag_repository: TagRepository | None = None
        self._root_identity = None
        if isinstance(session, LibrarySession):
            require_library_session(session)
            if self._asset_index_service is None:
                self._asset_index_service = AssetIndexService.for_session(session)
            elif self._asset_index_service.session is not session:
                raise ValueError(
                    "SearchService asset index service does not belong to the LibrarySession"
                )
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
                    "SearchService connection provider does not belong to "
                    "the LibrarySession"
                )
            # Retain the exact provider object supplied by the runtime.
            # Besides preserving the session binding, this keeps the provider
            # identity shared by sibling runtime services.
            self._connection_provider = provider
            self._root_identity = session.context.root_identity
            self._tag_repository = TagRepository.for_session(session)
        else:
            self._connection_provider = connection_provider

    @session_operation
    def search_by_tags(
        self,
        library_root: str | Path,
        tags: list[str],
        query: str = "",
        category: str = "all",
        db_conn: sqlite3.Connection | None = None,
    ) -> list[SearchResult]:
        """Find files that have any of the given tags.

        This legacy wrapper deliberately keeps returning a list. Use
        :meth:`search_by_tags_detailed` when source health and rejected rows
        matter to the caller.
        """
        return self._search_by_tags_detailed(library_root, tags, query, category, db_conn).as_list()

    @session_operation
    def search_by_tags_detailed(
        self,
        library_root: str | Path,
        tags: list[str],
        query: str = "",
        category: str = "all",
        db_conn: sqlite3.Connection | None = None,
    ) -> SearchResultSet:
        """Return tag matches together with source and diagnostic status."""
        return self._search_by_tags_detailed(library_root, tags, query, category, db_conn)

    def _search_by_tags_detailed(
        self,
        library_root: str | Path,
        tags: list[str],
        query: str,
        category: str,
        db_conn: sqlite3.Connection | None,
    ) -> SearchResultSet:
        started = perf_counter() if self._performance_recorder is not None else None
        db_conn = self._connection(library_root, db_conn)
        if db_conn is None:
            return self._record_results(
                "search.tags",
                library_root,
                started,
                SearchResultSet.from_source(
                    "tags",
                    status=SearchStatus.UNAVAILABLE,
                    errors=(SearchError("search_source_unavailable", "tags", recoverable=True),),
                ),
                limit=None,
            )

        results: list[SearchResult] = []
        seen_paths: set[str] = set()
        errors: list[SearchError] = []
        dropped_count = 0
        failed = False
        root = Path(library_root).resolve(strict=False)
        repository = (
            self._tag_repository
            if isinstance(self._session, LibrarySession) and self._tag_repository is not None
            else TagRepository(db_conn)
        )
        for tag in tags:
            try:
                paths = repository.get_files_by_tag_case_insensitive(tag)
            except (sqlite3.ProgrammingError, sqlite3.OperationalError):
                raise
            except Exception:
                failed = True
                _append_error(errors, SearchError("search_source_failed", "tags", recoverable=True))
                continue
            for fp in paths:
                try:
                    rel = _contained_relative_path(root, fp, resolved_root=root)
                    if rel is None:
                        dropped_count += 1
                        _append_error(errors, SearchError("search_result_rejected", "tags", recoverable=True))
                        continue
                    if rel in seen_paths:
                        # A file may carry several of the searched tags; keep
                        # one result per relative path (mirror merge dedup).
                        continue
                    seen_paths.add(rel)
                    name = Path(rel).name
                    if query and query not in name.lower():
                        continue
                    ext = Path(name).suffix.lower()
                    cat = _category_for_extension(ext)
                    if category != "all" and cat != category:
                        continue
                    results.append(SearchResult(name=name, path=rel, extension=ext, category=cat))
                except (OSError, TypeError, ValueError):
                    dropped_count += 1
                    _append_error(errors, SearchError("search_result_invalid", "tags", recoverable=True))

        if failed:
            status = SearchStatus.PARTIAL if results else SearchStatus.ERROR
        elif dropped_count:
            status = SearchStatus.PARTIAL if results else SearchStatus.PATH_REJECTED
        else:
            status = SearchStatus.COMPLETE if results else SearchStatus.EMPTY
        return self._record_results(
            "search.tags",
            library_root,
            started,
            SearchResultSet.from_source(
                "tags",
                results,
                status=status,
                errors=errors,
                dropped_count=dropped_count,
            ),
            limit=None,
        )

    @session_operation
    def search_by_name(
        self,
        query: str,
        category: str = "all",
        scanner: _Scanner | None = None,
        limit: int = 200,
    ) -> list[SearchResult]:
        """Find files by name using the in-memory scanner index.

        This legacy wrapper deliberately keeps returning a list. Use
        :meth:`search_by_name_detailed` for source diagnostics.
        """
        return self._search_by_name_detailed(query, category, scanner, limit).as_list()

    @session_operation
    def search_by_name_detailed(
        self,
        query: str,
        category: str = "all",
        scanner: _Scanner | None = None,
        limit: int = 200,
    ) -> SearchResultSet:
        """Return scanner matches together with source and diagnostic status."""
        return self._search_by_name_detailed(query, category, scanner, limit)

    def _search_by_name_detailed(
        self,
        query: str,
        category: str,
        scanner: _Scanner | None,
        limit: int,
    ) -> SearchResultSet:
        started = perf_counter() if self._performance_recorder is not None else None
        if not query:
            return self._record_results(
                "search.name",
                None,
                started,
                SearchResultSet.from_source(
                    "scanner",
                    status=SearchStatus.INVALID_INPUT,
                    errors=(SearchError("search_invalid_input", "scanner", recoverable=True),),
                ),
                limit=limit,
            )
        if not scanner:
            return self._record_results(
                "search.name",
                None,
                started,
                SearchResultSet.from_source(
                    "scanner",
                    status=SearchStatus.UNAVAILABLE,
                    errors=(SearchError("search_source_unavailable", "scanner", recoverable=True),),
                ),
                limit=limit,
            )
        try:
            index_results = scanner.search(query, limit=limit)
            rows = tuple(index_results)
        except (sqlite3.ProgrammingError, sqlite3.OperationalError):
            raise
        except Exception:
            return self._record_results(
                "search.name",
                None,
                started,
                SearchResultSet.from_source(
                    "scanner",
                    status=SearchStatus.ERROR,
                    errors=(SearchError("search_source_failed", "scanner", recoverable=True),),
                ),
                limit=limit,
            )

        results: list[SearchResult] = []
        errors: list[SearchError] = []
        dropped_count = 0
        for row in rows:
            try:
                if not isinstance(row, dict):
                    raise TypeError("scanner row must be a mapping")
                extension = row["extension"]
                name = row["name"]
                path = row["path"]
                if not all(isinstance(value, str) for value in (extension, name, path)):
                    raise TypeError("scanner row fields must be strings")
                cat = _category_for_extension(extension)
                if category != "all" and cat != category:
                    continue
                results.append(SearchResult(name=name, path=path, extension=extension, category=cat))
            except (KeyError, TypeError, ValueError):
                dropped_count += 1
                _append_error(errors, SearchError("search_result_invalid", "scanner", recoverable=True))

        status = SearchStatus.PARTIAL if dropped_count and results else (
            SearchStatus.PARTIAL if dropped_count else SearchStatus.COMPLETE if results else SearchStatus.EMPTY
        )
        return self._record_results(
            "search.name",
            None,
            started,
            SearchResultSet.from_source(
                "scanner",
                results,
                status=status,
                errors=errors,
                dropped_count=dropped_count,
            ),
            limit=limit,
        )

    @session_operation
    def search_by_name_indexed(
        self,
        library_root: str | Path,
        query: str,
        category: str = "all",
        db_conn: sqlite3.Connection | None = None,
        limit: int = 200,
    ) -> list[SearchResult]:
        """Find files by name using the assets DB index.

        This is an alternative to ``search_by_name`` that uses the
        ``assets`` table instead of the in-memory scanner. It works
        even when the scanner has not been populated yet.
        """
        return self._search_by_name_indexed_detailed(library_root, query, category, db_conn, limit).as_list()

    @session_operation
    def search_by_name_indexed_detailed(
        self,
        library_root: str | Path,
        query: str,
        category: str = "all",
        db_conn: sqlite3.Connection | None = None,
        limit: int = 200,
    ) -> SearchResultSet:
        """Return indexed matches together with containment diagnostics."""
        return self._search_by_name_indexed_detailed(library_root, query, category, db_conn, limit)

    def _search_by_name_indexed_detailed(
        self,
        library_root: str | Path,
        query: str,
        category: str,
        db_conn: sqlite3.Connection | None,
        limit: int,
    ) -> SearchResultSet:
        started = perf_counter() if self._performance_recorder is not None else None
        if not query:
            return self._record_results(
                "search.indexed",
                library_root,
                started,
                SearchResultSet.from_source(
                    "indexed",
                    status=SearchStatus.INVALID_INPUT,
                    errors=(SearchError("search_invalid_input", "indexed", recoverable=True),),
                ),
                limit=limit,
            )
        db_conn = self._connection(library_root, db_conn)
        if db_conn is None:
            return self._record_results(
                "search.indexed",
                library_root,
                started,
                SearchResultSet.from_source(
                    "indexed",
                    status=SearchStatus.UNAVAILABLE,
                    errors=(SearchError("search_source_unavailable", "indexed", recoverable=True),),
                ),
                limit=limit,
            )
        root = root_identity(library_root, strict=False).display_path
        try:
            if self._asset_index_service is not None:
                entries = self._asset_index_service.search_by_name(
                    db_conn, root, query, limit
                )
            else:
                entries = AssetIndexRepository(db_conn).search_by_name(
                    str(root), query, limit
                )
        except (sqlite3.ProgrammingError, sqlite3.OperationalError):
            raise
        except Exception:
            return self._record_results(
                "search.indexed",
                library_root,
                started,
                SearchResultSet.from_source(
                    "indexed",
                    status=SearchStatus.ERROR,
                    errors=(SearchError("search_source_failed", "indexed", recoverable=True),),
                ),
                limit=limit,
            )

        results, errors, dropped_count = self._project_index_entries(
            root, entries, category,
        )

        if dropped_count:
            status = SearchStatus.PARTIAL if results else SearchStatus.PATH_REJECTED
        else:
            status = SearchStatus.COMPLETE if results else SearchStatus.EMPTY
        return self._record_results(
            "search.indexed",
            library_root,
            started,
            SearchResultSet.from_source(
                "indexed",
                results,
                status=status,
                errors=errors,
                dropped_count=dropped_count,
            ),
            limit=limit,
        )

    @session_operation
    def search_by_fts_detailed(
        self,
        library_root: str | Path,
        query: str,
        category: str = "all",
        db_conn: sqlite3.Connection | None = None,
        limit: int = 200,
    ) -> SearchResultSet:
        """Return full-text (``asset_search``) matches with source diagnostics.

        Fourth search source (migration v39, trigram since v40): the FTS5
        document aggregates ``assets.name``, ``file_tags`` and
        ``file_meta.notes`` per path, so this source recalls tag/notes text
        that the scanner and indexed sources cannot see. The query is
        parsed with the shared syntax parser (bare words AND, ``|`` OR,
        ``-`` exclusion, quoted phrases, ``name:``/``tag:``/``notes:``
        field filters) and executed on the dual-track contract: a trigram
        MATCH prefilter plus an exact case-folded substring
        post-verification that serves 1-2 code point (e.g. CJK) terms.

        The full-text index is a derived, rebuildable projection: every
        failure (unwired maintainer, missing table, malformed MATCH)
        degrades to a diagnostic status — this source never raises to the
        transport and therefore can never turn a search into a 500.
        """
        return self._search_by_fts_detailed(library_root, query, category, db_conn, limit)

    def _search_by_fts_detailed(
        self,
        library_root: str | Path,
        query: str,
        category: str,
        db_conn: sqlite3.Connection | None,
        limit: int,
    ) -> SearchResultSet:
        started = perf_counter() if self._performance_recorder is not None else None
        if not query:
            return self._record_results(
                "search.fts",
                library_root,
                started,
                SearchResultSet.from_source(
                    "fts",
                    status=SearchStatus.INVALID_INPUT,
                    errors=(SearchError("search_invalid_input", "fts", recoverable=True),),
                ),
                limit=limit,
            )
        if self._search_index_service is None:
            return self._record_results(
                "search.fts",
                library_root,
                started,
                SearchResultSet.from_source(
                    "fts",
                    status=SearchStatus.UNAVAILABLE,
                    errors=(SearchError("search_source_unavailable", "fts", recoverable=True),),
                ),
                limit=limit,
            )
        db_conn = self._connection(library_root, db_conn)
        if db_conn is None:
            return self._record_results(
                "search.fts",
                library_root,
                started,
                SearchResultSet.from_source(
                    "fts",
                    status=SearchStatus.UNAVAILABLE,
                    errors=(SearchError("search_source_unavailable", "fts", recoverable=True),),
                ),
                limit=limit,
            )
        root = Path(library_root).resolve(strict=False)
        try:
            parsed = parse_query(query)
            # Dual-track execution (migration v40): the trigram MATCH
            # prefilter narrows candidates, the exact substring predicate
            # post-verifies them (implementing 1-2 code point terms that
            # cannot form a trigram, plus exclusions and field scopes).
            # A query with no positive term yields no paths.
            paths = self._search_index_service.query_file_paths(
                parsed, limit=limit, db_conn=db_conn,
            )
        except Exception:
            return self._record_results(
                "search.fts",
                library_root,
                started,
                SearchResultSet.from_source(
                    "fts",
                    status=SearchStatus.ERROR,
                    errors=(SearchError("search_source_failed", "fts", recoverable=True),),
                ),
                limit=limit,
            )

        results: list[SearchResult] = []
        errors: list[SearchError] = []
        dropped_count = 0
        for file_path in paths:
            rel = _contained_relative_path(root, file_path, resolved_root=root)
            if rel is None:
                dropped_count += 1
                _append_error(errors, SearchError("search_result_rejected", "fts", recoverable=True))
                continue
            name = Path(rel).name
            extension = Path(name).suffix.lower()
            cat = _category_for_extension(extension)
            if category != "all" and cat != category:
                continue
            results.append(SearchResult(name=name, path=rel, extension=extension, category=cat))

        if dropped_count:
            status = SearchStatus.PARTIAL if results else SearchStatus.PATH_REJECTED
        else:
            status = SearchStatus.COMPLETE if results else SearchStatus.EMPTY
        return self._record_results(
            "search.fts",
            library_root,
            started,
            SearchResultSet.from_source(
                "fts",
                results,
                status=status,
                errors=errors,
                dropped_count=dropped_count,
            ),
            limit=limit,
        )

    @session_operation
    def search_structured_detailed(
        self,
        library_root: str | Path,
        *,
        name_substring: str = "",
        extensions: Sequence[str] | None = None,
        size_min: int | None = None,
        size_max: int | None = None,
        mtime_after: float | None = None,
        mtime_before: float | None = None,
        rating_min: int | None = None,
        rating_max: int | None = None,
        favorite: bool = False,
        favorite_owner_key: str | None = None,
        category: str = "all",
        order_by: str = "name",
        db_conn: sqlite3.Connection | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> SearchResultSet:
        """Structured indexed search by extension/size/mtime (and name).

        Unlike the scanner-based sources, the ``assets`` index can execute
        size/mtime/extension predicates efficiently in SQL, so structured
        queries run indexed-only by contract. ``rating_min``/``rating_max``
        filter on ``file_meta.rating`` (NULL = unrated, excluded by any
        positive rating filter); ``favorite`` keeps only rows favorited by
        ``favorite_owner_key`` in ``library_favorites``. A raised
        ``ValueError`` (from the repository's whitelist/validation)
        propagates to the caller — transport layers map it to a client
        error instead of an empty "error" result set.
        """
        started = perf_counter() if self._performance_recorder is not None else None
        db_conn = self._connection(library_root, db_conn)
        if db_conn is None:
            return self._record_results(
                "search.structured",
                library_root,
                started,
                SearchResultSet.from_source(
                    "indexed",
                    status=SearchStatus.UNAVAILABLE,
                    errors=(SearchError("search_source_unavailable", "indexed", recoverable=True),),
                ),
                limit=limit,
            )
        root = root_identity(library_root, strict=False).display_path
        try:
            if self._asset_index_service is not None:
                entries = self._asset_index_service.search_structured(
                    db_conn,
                    root,
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
                    order_by=order_by,
                    limit=limit,
                    offset=offset,
                )
            else:
                entries = AssetIndexRepository(db_conn).search_structured(
                    str(root),
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
                    order_by=order_by,
                    limit=limit,
                    offset=offset,
                )
        except (sqlite3.ProgrammingError, sqlite3.OperationalError, ValueError):
            raise
        except Exception:
            return self._record_results(
                "search.structured",
                library_root,
                started,
                SearchResultSet.from_source(
                    "indexed",
                    status=SearchStatus.ERROR,
                    errors=(SearchError("search_source_failed", "indexed", recoverable=True),),
                ),
                limit=limit,
            )

        results, errors, dropped_count = self._project_index_entries(
            root, entries, category,
        )
        if dropped_count:
            status = SearchStatus.PARTIAL if results else SearchStatus.PATH_REJECTED
        else:
            status = SearchStatus.COMPLETE if results else SearchStatus.EMPTY
        return self._record_results(
            "search.structured",
            library_root,
            started,
            SearchResultSet.from_source(
                "indexed",
                results,
                status=status,
                errors=errors,
                dropped_count=dropped_count,
            ),
            limit=limit,
        )

    def _project_index_entries(
        self,
        root: Path,
        entries: Iterable[AssetIndexEntry],
        category: str,
    ) -> tuple[list[SearchResult], list[SearchError], int]:
        """Project ``AssetIndexEntry`` rows into results with diagnostics.

        Shared by the indexed name search and the structured search so both
        keep the identical containment/category/drop contract.
        """
        results: list[SearchResult] = []
        errors: list[SearchError] = []
        dropped_count = 0
        # The root is loop-invariant; resolve it once so each row pays only the
        # candidate resolve (one final-path syscall) instead of two.
        resolved_root = root.resolve(strict=False)
        for entry in entries:
            try:
                if entry.kind != "file":
                    continue
                rel = _contained_relative_path(
                    root, entry.file_path, resolved_root=resolved_root
                )
                if rel is None:
                    dropped_count += 1
                    _append_error(errors, SearchError("search_result_rejected", "indexed", recoverable=True))
                    continue
                extension = entry.extension
                name = entry.name
                if not all(isinstance(value, str) for value in (extension, name)):
                    raise TypeError("indexed row fields must be strings")
                cat = _category_for_extension(extension)
                if category != "all" and cat != category:
                    continue
                results.append(SearchResult(name=name, path=rel, extension=extension, category=cat))
            except (AttributeError, TypeError, ValueError):
                dropped_count += 1
                _append_error(errors, SearchError("search_result_invalid", "indexed", recoverable=True))
        return results, errors, dropped_count

    def _connection(
        self, library_root: str | Path, db_conn: sqlite3.Connection | None
    ) -> sqlite3.Connection | None:
        if isinstance(self._session, LibrarySession):
            requested = root_identity(library_root, strict=False)
            captured = self._root_identity
            if captured is None or requested.map_key != captured.map_key:
                raise ValueError(
                    "SearchService library_root does not match the bound "
                    "LibrarySession"
                )
            expected = self._session.connection_for(captured)
            if db_conn is not None and db_conn is not expected:
                raise ValueError(
                    "SearchService connection does not belong to the bound "
                    "LibrarySession"
                )
            return expected

        root = Path(library_root).resolve()
        if db_conn is not None:
            return DatabaseManager.validate_connection_owner(root, db_conn, allow_unmanaged=True)
        if self._connection_provider is None:
            return None
        try:
            conn = self._connection_provider(root)
        except (ValueError, sqlite3.ProgrammingError, sqlite3.OperationalError):
            raise
        except Exception:
            return None
        return DatabaseManager.validate_connection_owner(root, conn, allow_unmanaged=True)

    @session_operation
    def quick_search(
        self,
        library_root: str | Path,
        query: str,
        limit: int = _QUICK_SEARCH_DEFAULT_LIMIT,
    ) -> list[QuickSearchResult]:
        """Search visible files and directories with a bounded filesystem scan.

        This intentionally remains separate from the LAN search endpoint.
        The legacy search contract is file-oriented and may consult
        tag/index sources; command-palette search needs a small mixed
        file/directory projection, path matching, and a hard scan budget
        instead.

        The scan never follows symlinks, rejects resolved paths outside the
        canonical library root, skips hidden path components, and bounds both
        traversal and candidate collection.  A partial scan is acceptable for
        this interactive endpoint: it is preferable to blocking a LAN request
        on an unexpectedly large library.
        """
        if not isinstance(query, str):
            raise ValueError("query must be a string")
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("limit must be an integer")
        if limit < 1 or limit > _QUICK_SEARCH_MAX_LIMIT:
            raise ValueError(
                f"limit must be between 1 and {_QUICK_SEARCH_MAX_LIMIT}"
            )

        text = query.strip()
        if not text:
            return []

        root = root_identity(library_root, strict=False).display_path
        try:
            if not root.is_dir():
                return []
        except OSError:
            return []

        query_lower = text.lower()
        path_query = query_lower.replace("\\", "/")
        pending: list[Path] = [root]
        seen_directories: set[str] = set()
        candidates: list[tuple[tuple[int, int, str, str], QuickSearchResult]] = []
        scanned_entries = 0
        scanned_directories = 0
        deadline = monotonic() + _QUICK_SEARCH_BUDGET_SECONDS

        while pending and scanned_directories < _QUICK_SEARCH_MAX_DIRECTORIES:
            if monotonic() >= deadline or scanned_entries >= _QUICK_SEARCH_MAX_ENTRIES:
                break
            current = pending.pop(0)
            try:
                current_resolved = current.resolve(strict=False)
                if not current_resolved.is_relative_to(root):
                    continue
                directory_key = os.path.normcase(os.fspath(current_resolved))
                if directory_key in seen_directories:
                    continue
                seen_directories.add(directory_key)
                scanned_directories += 1
                with os.scandir(current) as entries:
                    for entry in entries:
                        if monotonic() >= deadline or scanned_entries >= _QUICK_SEARCH_MAX_ENTRIES:
                            break
                        scanned_entries += 1
                        name = entry.name
                        if not name or name.startswith("."):
                            continue

                        try:
                            # ``follow_symlinks=False`` prevents ordinary
                            # symlinks from becoming either results or scan
                            # roots.  The resolved containment check also
                            # protects against junction/reparse surprises.
                            if entry.is_symlink():
                                continue
                            candidate = Path(entry.path)
                            resolved = candidate.resolve(strict=False)
                            if not resolved.is_relative_to(root):
                                continue
                            is_dir = entry.is_dir(follow_symlinks=False)
                            is_file = entry.is_file(follow_symlinks=False)
                            if not is_dir and not is_file:
                                continue
                            rel = os.path.relpath(candidate, root).replace("\\", "/")
                            if not rel or rel == "." or rel.startswith("../"):
                                continue
                            parts = rel.split("/")
                            if any(part.startswith(".") for part in parts):
                                continue
                        except (OSError, RuntimeError, ValueError):
                            continue

                        if is_dir:
                            if scanned_directories + len(pending) < _QUICK_SEARCH_MAX_DIRECTORIES:
                                pending.append(candidate)
                            extension = ""
                            category = "folder"
                            item_type = "dir"
                        else:
                            extension = Path(name).suffix.lower()
                            category = _category_for_extension(extension)
                            item_type = "file"

                        name_lower = name.lower()
                        if query_lower in name_lower:
                            match_rank = 0
                        elif path_query in rel.lower():
                            match_rank = 1
                        else:
                            continue

                        result = QuickSearchResult(
                            name=name,
                            path=rel,
                            type=item_type,
                            extension=extension,
                            category=category,
                        )
                        candidates.append(
                            (
                                (
                                    match_rank,
                                    0 if is_dir else 1,
                                    rel.lower(),
                                    rel,
                                ),
                                result,
                            )
                        )
                        if len(candidates) > _QUICK_SEARCH_MAX_MATCHES:
                            candidates.sort(key=lambda item: item[0])
                            del candidates[_QUICK_SEARCH_MAX_MATCHES:]
            except OSError:
                continue

        candidates.sort(key=lambda item: item[0])
        return [result for _key, result in candidates[:limit]]

    def _record_results(
        self,
        name: str,
        library_root: str | Path | None,
        started: float | None,
        result_set: SearchResultSet,
        limit: int | None,
    ) -> SearchResultSet:
        if self._performance_recorder is None or started is None:
            return result_set
        attributes: dict[str, int | str] = {
            "outcome": result_set.telemetry_outcome,
            "result_count": result_set.count,
        }
        if limit is not None:
            attributes["limit"] = limit
        try:
            self._performance_recorder.record(
                name,
                (perf_counter() - started) * 1000,
                session_token=self._session_token,
                path=str(Path(library_root).resolve()) if library_root is not None else None,
                attributes=attributes,
            )
        except Exception:
            # Observability must not change search results or fallback behavior.
            pass
        return result_set
