"""Tests for SearchService."""

from AssetsManager.application.search_service import SearchService


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
