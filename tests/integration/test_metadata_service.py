import sqlite3


def _memory_conn() -> sqlite3.Connection:
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(database._SCHEMA)
    migrate(conn)
    return conn


def test_metadata_service_reads_notes_urls_and_tags(tmp_path):
    from AssetsManager.application import MetadataService
    from AssetsManager.core.project_data import ProjectData
    from AssetsManager.core.tag_store import TagStore

    library = tmp_path / "library"
    library.mkdir()
    asset = library / "asset.txt"
    asset.write_text("asset", encoding="utf-8")

    conn = _memory_conn()
    try:
        root = str(library.resolve())
        project = ProjectData(root, db_conn=conn)
        project.set_notes(str(asset), "note")
        project.add_url(str(asset), "https://example.com")
        store = TagStore(root, db_conn=conn)
        store.add_tag(str(asset), "hero")

        meta = MetadataService(connection_provider=lambda _root: conn).get_metadata(library, asset)

        assert meta.path == asset.resolve()
        assert meta.notes == "note"
        assert meta.urls == ("https://example.com",)
        assert meta.tags == ("hero",)
    finally:
        conn.close()


def test_metadata_service_combines_notes_and_urls_into_one_metadata_query(tmp_path):
    from AssetsManager.application import MetadataService

    library = tmp_path / "library"
    library.mkdir()
    asset = library / "asset.txt"
    asset.write_text("asset", encoding="utf-8")

    conn = _memory_conn()
    try:
        service = MetadataService(connection_provider=lambda _root: conn)
        service.set_notes(library, asset, "note")
        service.add_url(library, asset, "https://example.com")
        statements: list[str] = []
        conn.set_trace_callback(statements.append)

        metadata = service.get_metadata(library, asset)

        reads = [" ".join(statement.split()) for statement in statements if statement.startswith("SELECT")]
        assert metadata.notes == "note"
        assert metadata.urls == ("https://example.com",)
        assert len(reads) == 2
        assert any("SELECT tag FROM file_tags WHERE file_path=" in statement for statement in reads)
        assert any("SELECT notes, urls FROM file_meta WHERE file_path=" in statement for statement in reads)
    finally:
        conn.set_trace_callback(None)
        conn.close()


def test_metadata_service_writes_notes_and_urls(tmp_path):
    from AssetsManager.application import MetadataService

    library = tmp_path / "library"
    library.mkdir()
    asset = library / "asset.txt"
    asset.write_text("asset", encoding="utf-8")

    conn = _memory_conn()
    try:
        service = MetadataService(connection_provider=lambda _root: conn)
        service.set_notes(library, asset, "new note")
        service.add_url(library, asset, "https://example.com")

        assert service.get_notes(library, asset) == "new note"
        assert service.get_urls(library, asset) == ["https://example.com"]

        service.remove_url(library, asset, "https://example.com")
        assert service.get_urls(library, asset) == []
    finally:
        conn.close()


def test_metadata_service_get_dir_size(tmp_path):
    from AssetsManager.application import MetadataService

    library = tmp_path / "library"
    folder = library / "folder"
    folder.mkdir(parents=True)
    (folder / "asset.bin").write_bytes(b"1234")

    conn = _memory_conn()
    try:
        size, cached = MetadataService(connection_provider=lambda _root: conn).get_dir_size(library, folder)

        assert size == 4
        assert cached is False
    finally:
        conn.close()


def test_metadata_service_uses_connection_provider_for_notes_and_urls(tmp_path):
    from AssetsManager.application import MetadataService

    conn = _memory_conn()
    try:
        library = tmp_path / "library"
        library.mkdir()
        asset = library / "asset.txt"
        asset.write_text("asset", encoding="utf-8")

        service = MetadataService(connection_provider=lambda _root: conn)
        service.set_notes(library, asset, "provider note")
        service.add_url(library, asset, "https://example.com/provider")

        assert service.get_notes(library, asset) == "provider note"
        assert service.get_urls(library, asset) == ["https://example.com/provider"]
    finally:
        conn.close()


def test_metadata_service_get_metadata_uses_provider_for_tag_store(tmp_path):
    from AssetsManager.application import MetadataService
    from AssetsManager.core.tag_store import TagStore

    conn = _memory_conn()
    try:
        library = tmp_path / "library"
        library.mkdir()
        asset = library / "asset.txt"
        asset.write_text("asset", encoding="utf-8")

        root = str(library.resolve())
        service = MetadataService(connection_provider=lambda _root: conn)
        service.set_notes(library, asset, "provider note")
        TagStore(root, db_conn=conn).add_tag(str(asset.resolve()), "provider-tag")

        meta = service.get_metadata(library, asset)

        assert meta.notes == "provider note"
        assert meta.tags == ("provider-tag",)
    finally:
        conn.close()
