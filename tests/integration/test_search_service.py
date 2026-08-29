"""Tests for SearchService."""

import os

import pytest

from AssetsManager.application.search_service import SearchService


def test_real_session_search_service_auto_binds_asset_index_service(tmp_path):
    from AssetsManager.application import ApplicationBootstrap
    from AssetsManager.application.asset_index_service import AssetIndexService

    library = tmp_path / "library"
    library.mkdir()
    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(library)
    try:
        service = SearchService(session=session, connection_provider=session.connection_for)
        assert isinstance(service._asset_index_service, AssetIndexService)
        assert service._asset_index_service.session is session
    finally:
        bootstrap.library_service.close()


def test_search_by_tags_finds_tagged_files(tmp_path, schema_db):
    library = tmp_path / "lib"
    library.mkdir()
    asset = library / "hero.png"
    asset.write_bytes(b"fake")

    conn = schema_db
    conn.execute("INSERT INTO file_tags (file_path, tag) VALUES (?, ?)", (str(asset.resolve()), "hero"))
    conn.commit()

    svc = SearchService()
    results = svc.search_by_tags(library, ["hero"], db_conn=conn)

    assert len(results) == 1
    assert results[0].name == "hero.png"
    assert results[0].path == "hero.png"


def test_search_by_tags_matches_tags_case_insensitively(tmp_path, schema_db):
    library = tmp_path / "lib"
    library.mkdir()
    asset = library / "hero.png"
    asset.write_bytes(b"fake")
    schema_db.execute(
        "INSERT INTO file_tags (file_path, tag) VALUES (?, ?)",
        (str(asset.resolve()), "Hero"),
    )
    schema_db.commit()

    results = SearchService().search_by_tags(library, ["hero"], db_conn=schema_db)

    assert [result.path for result in results] == ["hero.png"]


def test_search_by_tags_uses_connection_provider_without_db_conn(tmp_path, schema_db):
    library = tmp_path / "lib"
    library.mkdir()
    asset = library / "hero.png"
    asset.write_bytes(b"fake")
    schema_db.execute(
        "INSERT INTO file_tags (file_path, tag) VALUES (?, ?)",
        (str(asset.resolve()), "hero"),
    )
    schema_db.commit()
    roots = []
    service = SearchService(connection_provider=lambda root: roots.append(root) or schema_db)

    results = service.search_by_tags(library, ["hero"])

    assert [result.path for result in results] == ["hero.png"]
    assert roots == [library.resolve()]


def test_search_by_tags_filters_by_query(tmp_path, schema_db):
    library = tmp_path / "lib"
    library.mkdir()
    (library / "hero.png").write_bytes(b"a")
    (library / "villain.png").write_bytes(b"b")

    conn = schema_db
    conn.execute("INSERT INTO file_tags (file_path, tag) VALUES (?, ?)", (str((library / "hero.png").resolve()), "char"))
    conn.execute("INSERT INTO file_tags (file_path, tag) VALUES (?, ?)", (str((library / "villain.png").resolve()), "char"))
    conn.commit()

    svc = SearchService()
    results = svc.search_by_tags(library, ["char"], query="hero", db_conn=conn)

    assert len(results) == 1
    assert results[0].name == "hero.png"


def test_search_by_tags_filters_by_category(tmp_path, schema_db):
    library = tmp_path / "lib"
    library.mkdir()
    (library / "hero.png").write_bytes(b"a")
    (library / "readme.txt").write_text("b")

    conn = schema_db
    conn.execute("INSERT INTO file_tags (file_path, tag) VALUES (?, ?)", (str((library / "hero.png").resolve()), "tag"))
    conn.execute("INSERT INTO file_tags (file_path, tag) VALUES (?, ?)", (str((library / "readme.txt").resolve()), "tag"))
    conn.commit()

    svc = SearchService()
    results = svc.search_by_tags(library, ["tag"], category="images", db_conn=conn)

    assert len(results) == 1
    assert results[0].name == "hero.png"


def test_search_by_tags_deduplicates_multi_tag_matches(tmp_path, schema_db):
    library = tmp_path / "lib"
    library.mkdir()
    asset = library / "hero.png"
    asset.write_bytes(b"fake")

    conn = schema_db
    conn.execute("INSERT INTO file_tags (file_path, tag) VALUES (?, ?)", (str(asset.resolve()), "hero"))
    conn.execute("INSERT INTO file_tags (file_path, tag) VALUES (?, ?)", (str(asset.resolve()), "character"))
    conn.commit()

    results = SearchService().search_by_tags(library, ["hero", "character"], db_conn=conn)

    assert [result.path for result in results] == ["hero.png"]


def test_search_by_tags_returns_empty_without_db():
    svc = SearchService()
    assert svc.search_by_tags("/tmp", ["tag"], db_conn=None) == []


def test_search_by_name_returns_empty_without_scanner():
    svc = SearchService()
    assert svc.search_by_name("query", scanner=None) == []


def test_search_result_exposes_relative_thumbnail_reference_only():
    from AssetsManager.application.search_service import SearchResult

    r = SearchResult(name="a.png", path="sub/a.png", extension=".png", category="images")
    assert r.thumbnail_path == "sub/a.png"
    assert "/api/" not in r.thumbnail_path


def test_search_by_name_indexed_finds_files(tmp_path, schema_db):
    from AssetsManager.application.asset_index_service import AssetIndexService

    library = tmp_path / "lib"
    library.mkdir()
    (library / "hero_idle.png").write_bytes(b"a")
    (library / "hero_attack.png").write_bytes(b"b")
    (library / "villain.png").write_bytes(b"c")

    conn = schema_db
    AssetIndexService().index_directory(conn, library, library)

    svc = SearchService()
    results = svc.search_by_name_indexed(library, "hero", db_conn=conn)

    assert len(results) == 2
    names = {r.name for r in results}
    assert "hero_idle.png" in names
    assert "hero_attack.png" in names


def test_search_by_name_indexed_uses_connection_provider_without_db_conn(tmp_path, schema_db):
    from AssetsManager.application.asset_index_service import AssetIndexService

    library = tmp_path / "lib"
    library.mkdir()
    (library / "hero.png").write_bytes(b"a")
    AssetIndexService().index_directory(schema_db, library, library)
    service = SearchService(connection_provider=lambda _root: schema_db)

    results = service.search_by_name_indexed(library, "hero")

    assert [result.name for result in results] == ["hero.png"]


def test_search_by_name_indexed_filters_by_category(tmp_path, schema_db):
    from AssetsManager.application.asset_index_service import AssetIndexService

    library = tmp_path / "lib"
    library.mkdir()
    (library / "hero.png").write_bytes(b"a")
    (library / "hero.txt").write_text("b")

    conn = schema_db
    AssetIndexService().index_directory(conn, library, library)

    svc = SearchService()
    results = svc.search_by_name_indexed(library, "hero", category="images", db_conn=conn)

    assert len(results) == 1
    assert results[0].name == "hero.png"


def test_search_by_name_indexed_returns_empty_without_conn():
    svc = SearchService()
    assert svc.search_by_name_indexed("/tmp", "query", db_conn=None) == []


def test_search_records_session_scoped_tag_and_indexed_metrics(tmp_path, schema_db):
    from AssetsManager.application.asset_index_service import AssetIndexService
    from AssetsManager.core.performance import PerformanceRecorder

    library = tmp_path / "lib"
    library.mkdir()
    asset = library / "hero.png"
    asset.write_bytes(b"fake")
    schema_db.execute("INSERT INTO file_tags (file_path, tag) VALUES (?, ?)", (str(asset), "hero"))
    schema_db.commit()
    AssetIndexService().index_directory(schema_db, library, library)
    recorder = PerformanceRecorder(enabled=True)
    service = SearchService(recorder, session_token="session-a")

    service.search_by_tags(library, ["hero"], db_conn=schema_db)
    service.search_by_name_indexed(library, "hero", db_conn=schema_db, limit=10)

    events = recorder.recent()
    assert [event.name for event in events] == ["search.tags", "search.indexed"]
    assert all(event.session_token == "session-a" and event.path == str(library.resolve()) for event in events)
    assert events[0].attributes == {"outcome": "success", "result_count": 1}
    assert events[1].attributes == {"outcome": "success", "result_count": 1, "limit": 10}


def test_search_recorder_failure_does_not_change_results(tmp_path, schema_db, monkeypatch):
    from AssetsManager.core.performance import PerformanceRecorder

    library = tmp_path / "lib"
    library.mkdir()
    asset = library / "hero.png"
    asset.write_bytes(b"fake")
    schema_db.execute("INSERT INTO file_tags (file_path, tag) VALUES (?, ?)", (str(asset), "hero"))
    schema_db.commit()
    recorder = PerformanceRecorder(enabled=True)
    monkeypatch.setattr(recorder, "record", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError()))

    results = SearchService(recorder).search_by_tags(library, ["hero"], db_conn=schema_db)

    assert [result.name for result in results] == ["hero.png"]


def test_search_records_non_sensitive_outcomes_for_early_and_failed_paths():
    from AssetsManager.core.performance import PerformanceRecorder

    class _BrokenScanner:
        def search(self, query: str, limit: int = 200) -> list[dict]:
            del query, limit
            raise RuntimeError("backend failed")

    recorder = PerformanceRecorder(enabled=True)
    service = SearchService(recorder)

    service.search_by_tags("/library", ["hero"], db_conn=None)
    service.search_by_name("", scanner=_BrokenScanner())
    service.search_by_name("hero", scanner=None)
    service.search_by_name("hero", scanner=_BrokenScanner())

    assert [(event.name, event.attributes["outcome"]) for event in recorder.recent()] == [
        ("search.tags", "unavailable"),
        ("search.name", "invalid_input"),
        ("search.name", "unavailable"),
        ("search.name", "error"),
    ]


def test_search_by_name_indexed_filters_library_external_absolute_paths(tmp_path, schema_db):
    library = tmp_path / "lib"
    library.mkdir()
    inside = library / "inside-hero.png"
    inside.write_bytes(b"inside")
    outside = tmp_path / "outside-hero.png"
    outside.write_bytes(b"outside")

    root = str(library.resolve())
    schema_db.executemany(
        "INSERT INTO assets (file_path, name, extension, kind, size, mtime, parent_path, library_root) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (str(outside.resolve()), outside.name, ".png", "file", 7, 1.0, root, root),
            (str(inside.resolve()), inside.name, ".png", "file", 6, 1.0, root, root),
        ],
    )
    schema_db.commit()

    results = SearchService().search_by_name_indexed(library, "hero", db_conn=schema_db)

    assert [(result.name, result.path) for result in results] == [(inside.name, inside.name)]


def test_search_by_name_indexed_filters_relative_parent_escape(tmp_path, schema_db):
    library = tmp_path / "lib"
    library.mkdir()
    inside = library / "inside-hero.png"
    inside.write_bytes(b"inside")
    outside = tmp_path / "outside-hero.png"
    outside.write_bytes(b"outside")

    root = str(library.resolve())
    schema_db.executemany(
        "INSERT INTO assets (file_path, name, extension, kind, size, mtime, parent_path, library_root) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("../outside-hero.png", outside.name, ".png", "file", 7, 1.0, root, root),
            ("inside-hero.png", inside.name, ".png", "file", 6, 1.0, root, root),
        ],
    )
    schema_db.commit()

    results = SearchService().search_by_name_indexed(library, "hero", db_conn=schema_db)

    assert [(result.name, result.path) for result in results] == [(inside.name, inside.name)]


def test_search_by_name_indexed_filters_symlink_to_library_external_path(tmp_path, schema_db):
    library = tmp_path / "lib"
    library.mkdir()
    outside = tmp_path / "outside-hero.png"
    outside.write_bytes(b"outside")
    linked = library / "linked-hero.png"

    try:
        os.symlink(outside, linked)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    root = str(library.resolve())
    schema_db.execute(
        "INSERT INTO assets (file_path, name, extension, kind, size, mtime, parent_path, library_root) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (str(linked), linked.name, ".png", "file", 7, 1.0, root, root),
    )
    schema_db.commit()

    assert SearchService().search_by_name_indexed(library, "hero", db_conn=schema_db) == []


def test_search_service_accepts_managed_same_root_connection(tmp_path):
    from AssetsManager.core.database import DatabaseManager

    library = tmp_path / "library"
    library.mkdir()
    asset = library / "hero.png"
    asset.write_bytes(b"asset")
    manager = DatabaseManager()
    try:
        conn = manager.connection_for(library)
        conn.execute(
            "INSERT INTO file_tags (file_path, tag) VALUES (?, ?)",
            (str(asset.resolve()), "hero"),
        )
        conn.commit()

        results = SearchService(connection_provider=lambda _root: conn).search_by_tags(
            library, ["hero"]
        )

        assert [result.path for result in results] == ["hero.png"]
    finally:
        manager.close()


def test_search_service_rejects_provider_managed_foreign_root(tmp_path):
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
            service.search_by_tags(root_a, ["hero"])
    finally:
        manager.close()


def test_search_service_provider_failure_still_degrades(tmp_path):
    library = tmp_path / "library"
    library.mkdir()

    def failing_provider(_root):
        raise RuntimeError("provider unavailable")

    assert SearchService(connection_provider=failing_provider).search_by_tags(
        library, ["hero"]
    ) == []


def test_search_service_explicit_unmanaged_connection_overrides_provider(tmp_path, schema_db):
    library = tmp_path / "library"
    library.mkdir()
    asset = library / "hero.png"
    asset.write_bytes(b"asset")
    schema_db.execute(
        "INSERT INTO file_tags (file_path, tag) VALUES (?, ?)",
        (str(asset.resolve()), "hero"),
    )
    schema_db.commit()

    def failing_provider(_root):
        raise AssertionError("provider must not be called")

    results = SearchService(connection_provider=failing_provider).search_by_tags(
        library, ["hero"], db_conn=schema_db
    )

    assert [result.path for result in results] == ["hero.png"]


def test_standalone_search_service_remains_unbound_and_compatible(tmp_path, schema_db):
    library = tmp_path / "library"
    library.mkdir()
    asset = library / "hero.png"
    asset.write_bytes(b"asset")
    schema_db.execute(
        "INSERT INTO file_tags (file_path, tag) VALUES (?, ?)",
        (str(asset.resolve()), "hero"),
    )
    schema_db.commit()

    service = SearchService()

    assert service._session is None
    assert [result.path for result in service.search_by_tags(
        library, ["hero"], db_conn=schema_db
    )] == ["hero.png"]


def test_session_bound_search_service_rejects_operations_after_close(tmp_path):
    from AssetsManager.application import ApplicationBootstrap

    bootstrap = ApplicationBootstrap()
    session = bootstrap.library_service.open_session(tmp_path / "library")
    try:
        service = bootstrap.runtime_for(session).services.search_service
        session.close()

        with pytest.raises(RuntimeError, match="closed LibrarySession"):
            service.search_by_name("hero", scanner=object())
    finally:
        bootstrap.library_service.close()


# ── search_structured_detailed ────────────────────────────────────


def _index_library(library, conn):
    from AssetsManager.application.asset_index_service import AssetIndexService

    library.mkdir(parents=True, exist_ok=True)
    (library / "old_small.png").write_bytes(b"a")
    (library / "new_big.png").write_bytes(b"b" * 4096)
    (library / "new_big.jpg").write_bytes(b"c" * 8192)
    AssetIndexService().index_directory(conn, library, library)
    # Deterministic mtimes: 1000.0 vs 2000.0 (epoch seconds, assets.mtime).
    conn.execute("UPDATE assets SET mtime=1000.0 WHERE name='old_small.png'")
    conn.execute("UPDATE assets SET mtime=2000.0 WHERE name IN ('new_big.png', 'new_big.jpg')")
    conn.commit()


def test_search_structured_filters_by_mtime_range(tmp_path, schema_db):
    library = tmp_path / "lib"
    _index_library(library, schema_db)

    svc = SearchService()
    result_set = svc.search_structured_detailed(
        library, mtime_after=1500.0, db_conn=schema_db,
    )

    assert result_set.status.value == "complete"
    assert [result.name for result in result_set.results] == ["new_big.jpg", "new_big.png"]
    assert result_set.sources[0].source == "indexed"


def test_search_structured_combines_ext_size_and_name(tmp_path, schema_db):
    library = tmp_path / "lib"
    _index_library(library, schema_db)

    svc = SearchService()
    result_set = svc.search_structured_detailed(
        library,
        name_substring="big",
        extensions=["png"],
        size_min=4000,
        mtime_after=1500.0,
        db_conn=schema_db,
    )

    assert [result.name for result in result_set.results] == ["new_big.png"]


def test_search_structured_orders_by_size_and_pages(tmp_path, schema_db):
    library = tmp_path / "lib"
    _index_library(library, schema_db)

    svc = SearchService()
    ordered = svc.search_structured_detailed(
        library, order_by="size", db_conn=schema_db,
    )
    assert [result.name for result in ordered.results] == [
        "old_small.png", "new_big.png", "new_big.jpg",
    ]

    paged = svc.search_structured_detailed(
        library, order_by="size", offset=1, limit=1, db_conn=schema_db,
    )
    assert [result.name for result in paged.results] == ["new_big.png"]


def test_search_structured_invalid_order_by_raises_value_error(tmp_path, schema_db):
    library = tmp_path / "lib"
    _index_library(library, schema_db)

    svc = SearchService()
    with pytest.raises(ValueError):
        svc.search_structured_detailed(
            library, order_by="mtime; DROP TABLE assets", db_conn=schema_db,
        )


def test_search_structured_returns_unavailable_without_conn(tmp_path):
    svc = SearchService()
    result_set = svc.search_structured_detailed("/tmp", size_min=1, db_conn=None)
    assert result_set.status.value == "unavailable"
    assert result_set.results == ()
