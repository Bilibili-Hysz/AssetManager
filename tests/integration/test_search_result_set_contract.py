"""Detailed SearchResultSet and SearchService status contract tests."""

from __future__ import annotations

import sqlite3

import pytest

from AssetsManager.application.search_service import (
    SearchError,
    SearchResult,
    SearchResultSet,
    SearchService,
    SearchStatus,
)
from AssetsManager.repositories.tag_repository import TagRepository


def test_detailed_tag_search_distinguishes_empty_from_unavailable(tmp_path, schema_db):
    library = tmp_path / "library"
    library.mkdir()
    service = SearchService()

    empty = service.search_by_tags_detailed(library, ["missing"], db_conn=schema_db)
    unavailable = service.search_by_tags_detailed(library, ["missing"])

    assert empty.status is SearchStatus.EMPTY
    assert empty.is_complete
    assert empty.results == ()
    assert empty.sources[0].source == "tags"
    assert empty.sources[0].status is SearchStatus.EMPTY

    assert unavailable.status is SearchStatus.UNAVAILABLE
    assert not unavailable.is_complete
    assert unavailable.errors == (
        SearchError("search_source_unavailable", "tags", recoverable=True),
    )


def test_detailed_scanner_failure_is_not_reported_as_empty():
    class BrokenScanner:
        def search(self, query: str, limit: int = 200) -> list[dict]:
            del query, limit
            raise RuntimeError("scanner backend failed")

    result_set = SearchService().search_by_name_detailed("hero", scanner=BrokenScanner())

    assert result_set.status is SearchStatus.ERROR
    assert result_set.results == ()
    assert result_set.errors == (
        SearchError("search_source_failed", "scanner", recoverable=True),
    )


def test_detailed_scanner_row_failure_is_partial():
    class Scanner:
        def search(self, query: str, limit: int = 200) -> list[dict]:
            del query, limit
            return [
                {"name": "hero.png", "path": "hero.png", "extension": ".png"},
                {"name": "broken"},
            ]

    result_set = SearchService().search_by_name_detailed("hero", scanner=Scanner())

    assert result_set.status is SearchStatus.PARTIAL
    assert [result.path for result in result_set.results] == ["hero.png"]
    assert result_set.dropped_count == 1
    assert result_set.errors[0].code == "search_result_invalid"


def test_detailed_tag_failure_is_partial_when_another_tag_succeeds(tmp_path, schema_db, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    asset = library / "hero.png"
    asset.write_bytes(b"asset")
    schema_db.execute(
        "INSERT INTO file_tags (file_path, tag) VALUES (?, ?)",
        (str(asset.resolve()), "good"),
    )
    schema_db.commit()

    original = TagRepository.get_files_by_tag_case_insensitive

    def get_files(self, tag):
        if tag == "broken":
            raise RuntimeError("one tag source failed")
        return original(self, tag)

    monkeypatch.setattr(TagRepository, "get_files_by_tag_case_insensitive", get_files)
    result_set = SearchService().search_by_tags_detailed(
        library,
        ["broken", "good"],
        db_conn=schema_db,
    )

    assert result_set.status is SearchStatus.PARTIAL
    assert [result.path for result in result_set.results] == ["hero.png"]
    assert result_set.errors == (
        SearchError("search_source_failed", "tags", recoverable=True),
    )


def test_detailed_indexed_search_reports_rejected_paths(tmp_path, schema_db):
    library = tmp_path / "library"
    library.mkdir()
    outside = tmp_path / "outside-hero.png"
    outside.write_bytes(b"outside")
    root = str(library.resolve())
    schema_db.execute(
        "INSERT INTO assets (file_path, name, extension, kind, size, mtime, parent_path, library_root) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (str(outside.resolve()), outside.name, ".png", "file", 7, 1.0, root, root),
    )
    schema_db.commit()

    result_set = SearchService().search_by_name_indexed_detailed(
        library,
        "hero",
        db_conn=schema_db,
    )

    assert result_set.status is SearchStatus.PATH_REJECTED
    assert result_set.results == ()
    assert result_set.dropped_count == 1
    assert result_set.errors == (
        SearchError("search_result_rejected", "indexed", recoverable=True),
    )


def test_detailed_indexed_schema_failure_propagates(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    conn = sqlite3.connect(":memory:")
    try:
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            SearchService().search_by_name_indexed_detailed(library, "hero", db_conn=conn)
    finally:
        conn.close()


def test_detailed_indexed_closed_connection_propagates(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    conn = sqlite3.connect(":memory:")
    conn.close()

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        SearchService().search_by_name_indexed_detailed(library, "hero", db_conn=conn)


def test_detailed_search_rejects_foreign_managed_connection(tmp_path):
    from AssetsManager.core.database import DatabaseManager

    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    root_a.mkdir()
    root_b.mkdir()
    manager = DatabaseManager()
    try:
        foreign_conn = manager.connection_for(root_b)
        service = SearchService(connection_provider=lambda _root: foreign_conn)
        with pytest.raises(ValueError, match="different library root"):
            service.search_by_tags_detailed(root_a, ["hero"])
    finally:
        manager.close()


def test_session_closed_is_rejected_before_detailed_search(tmp_path):
    from AssetsManager.application import ApplicationBootstrap

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        service = bootstrap.runtime_for(session).services.search_service
        session.close()
        with pytest.raises(RuntimeError, match="closed LibrarySession"):
            service.search_by_name_detailed("hero", scanner=object())
    finally:
        bootstrap.library_service.close()


def test_merge_marks_failed_fallback_as_degraded():
    primary = SearchResultSet.from_source(
        "scanner",
        status=SearchStatus.ERROR,
        errors=(SearchError("search_source_failed", "scanner", recoverable=True),),
    )
    fallback = SearchResultSet.from_source("indexed")

    merged = SearchResultSet.merge(primary, fallback, fallback_used=True)

    assert merged.status is SearchStatus.DEGRADED
    assert not merged.is_complete
    assert merged.fallback_used
    assert [source.source for source in merged.sources] == ["scanner", "indexed"]
    assert merged.errors == primary.errors


def test_merge_deduplicates_results_by_relative_path():
    first = SearchResult(name="hero.png", path="hero.png", extension=".png", category="images")
    duplicate = SearchResult(name="hero-renamed.png", path="hero.png", extension=".png", category="images")
    primary = SearchResultSet.from_source("scanner", [first])
    fallback = SearchResultSet.from_source("indexed", [duplicate])

    merged = SearchResultSet.merge(primary, fallback)

    assert merged.status is SearchStatus.COMPLETE
    assert merged.results == (first,)
    assert merged.count == 1
