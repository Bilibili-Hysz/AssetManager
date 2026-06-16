import sqlite3


def _memory_conn() -> sqlite3.Connection:
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(database._SCHEMA)
    migrate(conn)
    return conn


def test_tag_service_adds_and_lists_tags(tmp_path):
    from AssetsManager.application import TagService

    library = tmp_path / "library"
    library.mkdir()
    asset = library / "asset.txt"
    asset.write_text("asset", encoding="utf-8")

    conn = _memory_conn()
    try:
        service = TagService(connection_provider=lambda _root: conn)
        service.add_tag(library, asset, "hero")

        assert service.get_tags(library, asset) == ["hero"]
        assert service.list_tags(library) == [{"name": "hero", "count": 1}]
    finally:
        conn.close()


def test_tag_service_renames_and_deletes_tags(tmp_path):
    from AssetsManager.application import TagService

    library = tmp_path / "library"
    library.mkdir()
    asset = library / "asset.txt"
    asset.write_text("asset", encoding="utf-8")

    conn = _memory_conn()
    try:
        service = TagService(connection_provider=lambda _root: conn)
        service.add_tag(library, asset, "hero")
        service.rename_tag(library, "hero", "villain")

        assert service.get_tags(library, asset) == ["villain"]
        service.delete_tag(library, "villain")
        assert service.get_tags(library, asset) == []
    finally:
        conn.close()


def test_tag_service_uses_connection_provider(tmp_path):
    from AssetsManager.application import TagService

    conn = _memory_conn()
    try:
        library = tmp_path / "library"
        library.mkdir()
        asset = library / "asset.txt"
        asset.write_text("asset", encoding="utf-8")

        service = TagService(connection_provider=lambda _root: conn)
        service.add_tag(library, asset, "hero")

        assert service.get_tags(library, asset) == ["hero"]
        assert service.list_tags(library) == [{"name": "hero", "count": 1}]
    finally:
        conn.close()


def test_tag_service_explicit_connection_overrides_provider(tmp_path):
    from AssetsManager.application import TagService

    provider_conn = _memory_conn()
    explicit_conn = _memory_conn()
    try:
        library = tmp_path / "library"
        library.mkdir()
        asset = library / "asset.txt"
        asset.write_text("asset", encoding="utf-8")

        service = TagService(connection_provider=lambda _root: provider_conn)
        service.add_tag(library, asset, "hero", db_conn=explicit_conn)

        assert service.get_tags(library, asset, db_conn=explicit_conn) == ["hero"]
        assert service.get_tags(library, asset) == []
    finally:
        explicit_conn.close()
        provider_conn.close()
