"""Tests for the ``asset_search`` FTS index (migration v39).

Covers the four seams of the full-text fourth source:

- migration seed: v39 aggregates one document per file_path from
  assets.name + file_tags (group_concat) + file_meta.notes, idempotently;
- incremental maintenance: TagService / MetadataService /
  AssetIndexService hooks refresh documents after their own commit;
- SearchService.search_by_fts_detailed: the query-syntax fourth source
  with its degrade-to-diagnostics contract;
- smart collections: the ``fts`` query dimension.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from AssetsManager.application.asset_index_service import AssetIndexService
from AssetsManager.application.collection_service import CollectionService
from AssetsManager.application.metadata_service import MetadataService
from AssetsManager.application.search_index_service import SearchIndexService
from AssetsManager.application.search_service import SearchService, SearchStatus
from AssetsManager.application.tag_service import TagService
from AssetsManager.core import database
from AssetsManager.core.db_migrations import (
    CURRENT_SCHEMA_VERSION,
    _add_asset_search_fts_v39,
    _add_assets_index_v2,
    migrate,
)
from AssetsManager.domain.errors import ValidationError
from AssetsManager.repositories.asset_index_repository import AssetIndexRepository


@pytest.fixture
def conn() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.executescript(database._SCHEMA)
    # Full migration: the wiring tests need the v2 assets index and the v39
    # FTS table, i.e. the real migrated shape of a current library database.
    version = migrate(connection)
    assert version == CURRENT_SCHEMA_VERSION
    connection.commit()
    try:
        yield connection
    finally:
        connection.close()


def _insert_asset(conn: sqlite3.Connection, file_path: str, name: str) -> None:
    conn.execute(
        "INSERT INTO assets (file_path, name, extension, kind, size, mtime, parent_path, library_root) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            file_path, name, ".png", "file", 100, 1000.0,
            str(Path(file_path).parent), str(Path(file_path).parent),
        ),
    )


def _document(conn: sqlite3.Connection, file_path: str) -> tuple[str, str, str] | None:
    row = conn.execute(
        "SELECT name, tags, notes FROM asset_search WHERE file_path = ?",
        (file_path,),
    ).fetchone()
    return tuple(row) if row else None  # type: ignore[return-value]


# ── Migration v39: seed content and idempotency ────────────────────────


def test_migrate_reaches_latest_and_provisions_fts_table():
    from AssetsManager.core.db_migrations import CURRENT_SCHEMA_VERSION

    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.executescript(database._SCHEMA)
    try:
        version = migrate(connection)
        assert version == CURRENT_SCHEMA_VERSION
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "asset_search" in tables
        assert connection.execute("SELECT count(*) FROM asset_search").fetchone()[0] == 0
        # v40 rebuilt the table with the trigram tokenizer.
        ddl = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='asset_search'"
        ).fetchone()[0]
        assert "trigram" in ddl
    finally:
        connection.close()


def test_v39_seed_aggregates_three_sources_and_is_idempotent(conn: sqlite3.Connection):
    _add_assets_index_v2(conn)
    _insert_asset(conn, "D:/lib/sunset.png", "sunset.png")
    conn.execute(
        "INSERT INTO file_tags(file_path, tag) VALUES ('D:/lib/sunset.png', 'landscape'), "
        "('D:/lib/sunset.png', '风景')"
    )
    conn.execute(
        "INSERT INTO file_meta(file_path, notes) VALUES ('D:/lib/sunset.png', 'golden hour')"
    )
    # A path known only to file_tags (tagged before its first scan) still
    # becomes a document via the UNION of source keys.
    conn.execute("INSERT INTO file_tags(file_path, tag) VALUES ('D:/lib/only-tagged.png', 'lonetag')")
    conn.commit()

    # The step function is what Migration(39, ...) wraps; running it on a
    # v38-shaped database is exactly the v38 -> v39 upgrade.
    _add_asset_search_fts_v39(conn)

    assert _document(conn, "D:/lib/sunset.png") == ("sunset.png", "landscape 风景", "golden hour")
    assert _document(conn, "D:/lib/only-tagged.png") == ("", "lonetag", "")

    # Idempotent: re-running the step neither duplicates nor loses rows.
    _add_asset_search_fts_v39(conn)
    assert conn.execute("SELECT count(*) FROM asset_search").fetchone()[0] == 2


# ── Migration v40: trigram rebuild (CJK substring fix) ─────────────────


def _migrate_to_39(conn: sqlite3.Connection) -> None:
    """Run and record migrations 1..39 only, leaving v40 pending."""
    from AssetsManager.core.db_migrations import MIGRATIONS
    from AssetsManager.core.schema_defs import SCHEMA_MIGRATIONS_SCHEMA

    conn.execute(SCHEMA_MIGRATIONS_SCHEMA)
    for migration in MIGRATIONS:
        if migration.version > 39:
            break
        migration.apply(conn)
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (migration.version, migration.name, 0.0),
        )


def test_v40_rebuild_preserves_documents_and_enables_trigram():
    from AssetsManager.core.db_migrations import migrate

    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.executescript(database._SCHEMA)
    try:
        # A database that recorded v39 with the unicode61-era index:
        # documents already exist when v40 runs.
        _migrate_to_39(connection)
        _add_assets_index_v2(connection)
        _insert_asset(connection, "D:/lib/美丽的风景.png", "美丽的风景.png")
        _insert_asset(connection, "D:/lib/other.png", "other.png")
        _add_asset_search_fts_v39(connection)
        assert connection.execute("SELECT count(*) FROM asset_search").fetchone()[0] == 2

        # v40: drop + recreate with trigram + reseed.
        assert migrate(connection) == CURRENT_SCHEMA_VERSION
        assert _document(connection, "D:/lib/美丽的风景.png") == ("美丽的风景.png", "", "")
        assert _document(connection, "D:/lib/other.png") == ("other.png", "", "")
        ddl = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='asset_search'"
        ).fetchone()[0]
        assert "trigram" in ddl

        # The rebuilt index answers substring queries through the service.
        service = SearchIndexService(lambda: connection)
        assert service.search_file_paths("风景") == ["D:/lib/美丽的风景.png"]
    finally:
        connection.close()


def test_v40_rebuild_is_idempotent(conn: sqlite3.Connection):
    from AssetsManager.core.db_migrations import _rebuild_asset_search_fts_trigram_v40

    _add_assets_index_v2(conn)
    _insert_asset(conn, "D:/lib/sunset.png", "sunset.png")
    conn.execute(
        "INSERT INTO file_tags(file_path, tag) VALUES ('D:/lib/sunset.png', '风景')"
    )
    conn.commit()

    _rebuild_asset_search_fts_trigram_v40(conn)
    assert conn.execute("SELECT count(*) FROM asset_search").fetchone()[0] == 1

    # Re-running neither duplicates nor loses documents.
    _rebuild_asset_search_fts_trigram_v40(conn)
    assert conn.execute("SELECT count(*) FROM asset_search").fetchone()[0] == 1
    assert _document(conn, "D:/lib/sunset.png") == ("sunset.png", "风景", "")


# ── Incremental maintenance wiring: three services ─────────────────────


def test_tag_service_mutations_reindex_the_document(tmp_path, conn: sqlite3.Connection):
    library = tmp_path / "library"
    library.mkdir()
    target = library / "asset.txt"
    target.write_text("asset", encoding="utf-8")
    key = str(target.resolve())
    maintainer = SearchIndexService(lambda: conn)
    service = TagService(connection_provider=lambda _root: conn, search_index_service=maintainer)

    assert service.add_tag(library, target, "风景") is True
    assert _document(conn, key) == ("", "风景", "")

    assert service.remove_tag(library, target, "风景") is True
    assert _document(conn, key) == ("", "", "")

    # rename_tag reindexes every affected path (old name disappears and the
    # new name appears on the same documents).
    conn.execute("INSERT INTO file_tags(file_path, tag) VALUES (?, 'old')", (key,))
    other = library / "other.txt"
    other.write_text("other", encoding="utf-8")
    other_key = str(other.resolve())
    conn.execute("INSERT INTO file_tags(file_path, tag) VALUES (?, 'old')", (other_key,))
    conn.commit()
    service.rename_tag(library, "old", "new")
    assert _document(conn, key) == ("", "new", "")
    assert _document(conn, other_key) == ("", "new", "")

    service.delete_tag(library, "new")
    assert _document(conn, key) == ("", "", "")


def test_metadata_service_save_reindexes_the_document(tmp_path, conn: sqlite3.Connection):
    library = tmp_path / "library"
    library.mkdir()
    target = library / "asset.txt"
    target.write_text("asset", encoding="utf-8")
    key = str(target.resolve())
    maintainer = SearchIndexService(lambda: conn)
    service = MetadataService(
        connection_provider=lambda _root: conn, search_index_service=maintainer
    )

    service.set_notes(library, target, "deep in the notes 风景")
    assert _document(conn, key) == ("", "", "deep in the notes 风景")

    # urls are not indexed columns, but saving them keeps the document
    # present and correct (re-aggregated).
    service.add_url(library, target, "https://example.com/a")
    assert _document(conn, key) == ("", "", "deep in the notes 风景")


def test_asset_index_publish_reindexes_scanned_documents(tmp_path, conn: sqlite3.Connection):
    library = tmp_path / "library"
    library.mkdir()
    (library / "sunset 风景.png").write_bytes(b"image")
    maintainer = SearchIndexService(lambda: conn)
    service = AssetIndexService(search_index_service=maintainer)

    result = service.index_directory_result(conn, str(library), str(library))
    assert result.status.value == "published"
    key = str(library / "sunset 风景.png")
    assert _document(conn, key) == ("sunset 风景.png", "", "")

    # A caller-owned outer transaction is not durable: the hook must not
    # describe uncommitted source rows.
    conn.execute("BEGIN")
    (library / "second.png").write_bytes(b"image")
    result = service.index_directory_result(conn, str(library), str(library), force=True)
    conn.rollback()
    assert _document(conn, str(library / "second.png")) is None


# ── SearchService.search_by_fts_detailed (fourth source) ───────────────


@pytest.fixture
def fts_library(tmp_path, conn: sqlite3.Connection):
    library = tmp_path / "library"
    library.mkdir()
    _insert_asset(conn, str(library / "photo1.png"), "photo1.png")
    # A CJK-substring document: under the v39 unicode61 tokenizer "风景"
    # could never match this name (one long run); under v40 trigram it must.
    _insert_asset(conn, str(library / "美丽的风景.png"), "美丽的风景.png")
    conn.execute(
        "INSERT INTO file_tags(file_path, tag) VALUES (?, '风景')",
        (str(library / "photo1.png"),),
    )
    conn.execute(
        "INSERT INTO file_meta(file_path, notes) VALUES (?, 'golden hour')",
        (str(library / "photo1.png"),),
    )
    conn.commit()
    SearchIndexService(lambda: conn).reindex_all()
    return library


def test_fts_source_hits_tags_and_notes_text(fts_library, conn: sqlite3.Connection):
    service = SearchService(
        connection_provider=lambda _root: conn,
        search_index_service=SearchIndexService(lambda: conn),
    )

    # "风景" (2 code points) post-verifies: it hits photo1.png (tag run)
    # AND 美丽的风景.png (substring of the name) — the latter was
    # impossible under the v39 unicode61 tokenizer.
    result = service.search_by_fts_detailed(fts_library, "风景")
    assert result.status is SearchStatus.COMPLETE
    assert result.count == 2
    assert {item.name for item in result.results} == {"photo1.png", "美丽的风景.png"}
    assert result.results[0].path == "photo1.png"
    assert result.sources[0].source == "fts"

    # 3+ code points ride the trigram MATCH track (substring semantics).
    assert service.search_by_fts_detailed(fts_library, "的风景").count == 1

    # Field filters scope to one column.
    assert service.search_by_fts_detailed(fts_library, "tag:风景").count == 1
    # photo1's name is "photo1.png" — only the CJK document's name contains
    # the substring, even though both documents contain the term overall.
    assert service.search_by_fts_detailed(fts_library, "name:风景").count == 1
    assert service.search_by_fts_detailed(fts_library, "name:photo1").count == 1
    assert service.search_by_fts_detailed(fts_library, "notes:golden").count == 1
    assert service.search_by_fts_detailed(fts_library, "tag:golden").count == 0

    # Exclusion via NOT.
    assert service.search_by_fts_detailed(fts_library, "风景 -风景").status is SearchStatus.EMPTY


def test_fts_source_degenerate_inputs_stay_diagnostic(fts_library, conn: sqlite3.Connection):
    service = SearchService(
        connection_provider=lambda _root: conn,
        search_index_service=SearchIndexService(lambda: conn),
    )

    empty = service.search_by_fts_detailed(fts_library, "")
    assert empty.status is SearchStatus.INVALID_INPUT

    pure_exclusion = service.search_by_fts_detailed(fts_library, "-nothing")
    assert pure_exclusion.status is SearchStatus.EMPTY
    assert pure_exclusion.errors == ()


def test_fts_source_missing_table_degrades_to_error_source(fts_library, conn: sqlite3.Connection):
    conn.execute("DROP TABLE asset_search")
    conn.commit()
    service = SearchService(
        connection_provider=lambda _root: conn,
        search_index_service=SearchIndexService(lambda: conn),
    )

    result = service.search_by_fts_detailed(fts_library, "风景")
    assert result.status is SearchStatus.ERROR
    assert result.results == ()
    assert result.errors[0].code == "search_source_failed"
    assert result.errors[0].source == "fts"


def test_fts_source_unavailable_without_maintainer(fts_library, conn: sqlite3.Connection):
    service = SearchService(connection_provider=lambda _root: conn)

    result = service.search_by_fts_detailed(fts_library, "风景")
    assert result.status is SearchStatus.UNAVAILABLE
    assert result.errors[0].code == "search_source_unavailable"


# ── Smart collections: the ``fts`` query dimension ─────────────────────


class _IndexAdapter:
    """Forwards smart evaluation to the canonical structured repository query."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._repo = AssetIndexRepository(connection)

    def search_structured(self, library_root, **kwargs):
        return self._repo.search_structured(str(library_root), **kwargs)


def test_smart_collection_fts_dimension(tmp_path, conn: sqlite3.Connection, fts_library):
    service = CollectionService(
        connection_provider=lambda _root: conn,
        asset_index_service=_IndexAdapter(conn),
        search_index_service=SearchIndexService(lambda: conn),
    )

    collection = service.create_smart(fts_library, "sunset", {"fts": "tag:风景"})
    entries = service.evaluate(fts_library, collection["id"])
    assert [entry.name for entry in entries] == ["photo1.png"]

    # The fts dimension intersects with the structured predicates.
    collection = service.create_smart(fts_library, "miss", {"fts": "tag:风景", "extensions": ["jpg"]})
    assert service.evaluate(fts_library, collection["id"]) == []

    # An fts dimension matching nothing short-circuits to empty.
    collection = service.create_smart(fts_library, "none", {"fts": "不存在的词"})
    assert service.evaluate(fts_library, collection["id"]) == []


def test_smart_collection_fts_requires_maintainer(tmp_path, conn: sqlite3.Connection, fts_library):
    service = CollectionService(
        connection_provider=lambda _root: conn,
        asset_index_service=_IndexAdapter(conn),
    )
    collection = service.create_smart(fts_library, "fts-view", {"fts": "风景"})

    with pytest.raises(ValidationError) as exc_info:
        service.evaluate(fts_library, collection["id"])
    assert exc_info.value.field == "fts"


def test_smart_collection_rejects_empty_fts_text(tmp_path, conn: sqlite3.Connection, fts_library):
    service = CollectionService(
        connection_provider=lambda _root: conn,
        asset_index_service=_IndexAdapter(conn),
        search_index_service=SearchIndexService(lambda: conn),
    )

    with pytest.raises(ValidationError) as exc_info:
        service.create_smart(fts_library, "bad", {"fts": "   "})
    assert exc_info.value.field == "fts"


# ── Failure containment: a swallowed reindex must not leak transactions ─


def test_failed_reindex_rolls_back_and_keeps_connection_clean(
    tmp_path, conn: sqlite3.Connection,
):
    """Regression: a mid-statement failure (here: missing assets source
    table) must roll back the implicit transaction the first DML opened,
    otherwise the connection stays dirty and the *next* writer's
    clean-transaction check fails."""
    existing = "D:/existing.png"
    _insert_asset(conn, existing, "existing.png")
    conn.execute("INSERT INTO file_tags(file_path, tag) VALUES (?, 'tag')", (existing,))
    conn.commit()
    maintainer = SearchIndexService(lambda: conn)
    assert maintainer.reindex_files([existing]) == 1

    conn.execute("DROP TABLE assets")
    conn.commit()

    maintainer.reindex_files(["D:/x.png"])  # swallowed, never raises
    assert conn.in_transaction is False

    maintainer.reindex_all()  # swallowed, never raises
    assert conn.in_transaction is False
    # The rolled-back rebuild also restored the pre-existing document set.
    assert conn.execute("SELECT count(*) FROM asset_search").fetchone()[0] == 1
