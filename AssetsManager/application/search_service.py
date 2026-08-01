"""Search application service."""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Protocol

from AssetsManager.core.format_utils import CATEGORY_MAP
from AssetsManager.core.performance import PerformanceRecorder
from AssetsManager.application.context import ConnectionProvider
from AssetsManager.repositories.asset_index_repository import AssetIndexRepository
from AssetsManager.repositories.tag_repository import TagRepository


class _Scanner(Protocol):
    def search(self, query: str, limit: int = 200) -> list[dict]: ...


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


class SearchService:
    """Search assets by tags or name."""

    def __init__(
        self,
        performance_recorder: PerformanceRecorder | None = None,
        session_token: str | None = None,
        connection_provider: ConnectionProvider | None = None,
    ) -> None:
        self._performance_recorder = (
            performance_recorder if performance_recorder is not None and performance_recorder.enabled else None
        )
        self._session_token = session_token
        self._connection_provider = connection_provider

    def search_by_tags(
        self,
        library_root: str | Path,
        tags: list[str],
        query: str = "",
        category: str = "all",
        db_conn: sqlite3.Connection | None = None,
    ) -> list[SearchResult]:
        """Find files that have any of the given tags."""
        started = perf_counter() if self._performance_recorder is not None else None
        db_conn = self._connection(library_root, db_conn)
        if db_conn is None:
            return self._record_results("search.tags", library_root, started, [], limit=None, outcome="unavailable")
        results: list[SearchResult] = []
        failed = False
        for tag in tags:
            try:
                for fp in TagRepository(db_conn).get_files_by_tag_case_insensitive(tag):
                    rel = os.path.relpath(fp, library_root).replace("\\", "/")
                    name = os.path.basename(fp)
                    if query and query not in name.lower():
                        continue
                    ext = os.path.splitext(name)[1].lower()
                    cat = CATEGORY_MAP.get(ext, "other")
                    if category != "all" and cat != category:
                        continue
                    results.append(SearchResult(name=name, path=rel, extension=ext, category=cat))
            except Exception:
                failed = True
                continue
        return self._record_results(
            "search.tags", library_root, started, results, limit=None, outcome="error" if failed else "success"
        )

    def search_by_name(
        self,
        query: str,
        category: str = "all",
        scanner: _Scanner | None = None,
        limit: int = 200,
    ) -> list[SearchResult]:
        """Find files by name using the in-memory scanner index."""
        started = perf_counter() if self._performance_recorder is not None else None
        if not query:
            return self._record_results("search.name", None, started, [], limit=limit, outcome="invalid_input")
        if not scanner:
            return self._record_results("search.name", None, started, [], limit=limit, outcome="unavailable")
        try:
            index_results = scanner.search(query, limit=limit)
        except Exception:
            return self._record_results("search.name", None, started, [], limit=limit, outcome="error")

        results: list[SearchResult] = []
        for f in index_results:
            cat = CATEGORY_MAP.get(f["extension"], "other")
            if category != "all" and cat != category:
                continue
            results.append(SearchResult(
                name=f["name"], path=f["path"],
                extension=f["extension"], category=cat,
            ))
        return self._record_results("search.name", None, started, results, limit=limit, outcome="success")

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
        even when the scanner hasn't been populated yet.
        """
        started = perf_counter() if self._performance_recorder is not None else None
        if not query:
            return self._record_results("search.indexed", library_root, started, [], limit=limit, outcome="invalid_input")
        db_conn = self._connection(library_root, db_conn)
        if db_conn is None:
            return self._record_results("search.indexed", library_root, started, [], limit=limit, outcome="unavailable")
        try:
            entries = AssetIndexRepository(db_conn).search_by_name(
                str(Path(library_root).resolve()), query, limit,
            )
        except Exception:
            return self._record_results("search.indexed", library_root, started, [], limit=limit, outcome="error")

        results: list[SearchResult] = []
        for e in entries:
            cat = CATEGORY_MAP.get(e.extension, "other")
            if category != "all" and cat != category:
                continue
            rel = os.path.relpath(e.file_path, library_root).replace("\\", "/")
            results.append(SearchResult(
                name=e.name, path=rel,
                extension=e.extension, category=cat,
            ))
        return self._record_results("search.indexed", library_root, started, results, limit=limit, outcome="success")

    def _connection(
        self, library_root: str | Path, db_conn: sqlite3.Connection | None
    ) -> sqlite3.Connection | None:
        if db_conn is not None:
            return db_conn
        if self._connection_provider is None:
            return None
        try:
            return self._connection_provider(Path(library_root).resolve())
        except Exception:
            return None

    def _record_results(
        self,
        name: str,
        library_root: str | Path | None,
        started: float | None,
        results: list[SearchResult],
        limit: int | None,
        outcome: str,
    ) -> list[SearchResult]:
        if self._performance_recorder is None or started is None:
            return results
        attributes: dict[str, int | str] = {"outcome": outcome, "result_count": len(results)}
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
        return results
