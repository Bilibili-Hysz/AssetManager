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


def test_search_result_thumbnail_url():
    from AssetsManager.application.search_service import SearchResult

    r = SearchResult(name="a.png", path="sub/a.png", extension=".png", category="images")
    assert "/api/thumbnails/" in r.thumbnail_url
    assert "sub/a.png" in r.thumbnail_url


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
