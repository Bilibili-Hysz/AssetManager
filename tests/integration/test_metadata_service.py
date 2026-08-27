import pytest

import sqlite3
import time


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
        # db_write_lock probes closed connections with a "SELECT 1" health
        # check; count only the business queries.
        assert len([r for r in reads if r != "SELECT 1"]) == 2
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


def test_metadata_service_persists_library_total_size(tmp_path):
    from AssetsManager.application import MetadataService

    library = tmp_path / "library"
    library.mkdir()
    conn = _memory_conn()
    try:
        service = MetadataService(connection_provider=lambda _root: conn)
        service.set_library_total_size(library, 1234)

        assert service.get_library_total_size(library) == 1234
    finally:
        conn.close()


def test_metadata_service_dir_size_ttl_prevents_recompute_inside_window(tmp_path, monkeypatch):
    from AssetsManager.application import MetadataService
    from AssetsManager.core.project_data import ProjectData

    library = tmp_path / "library"
    folder = library / "folder"
    folder.mkdir(parents=True)
    (folder / "asset.bin").write_bytes(b"1234")

    calls = {"n": 0}
    real_compute = ProjectData.compute_dir_size

    def counting_compute(path, _depth=0, cancel_token=None):
        calls["n"] += 1
        return real_compute(path, _depth, cancel_token=cancel_token)

    monkeypatch.setattr(ProjectData, "compute_dir_size", staticmethod(counting_compute))

    conn = _memory_conn()
    try:
        service = MetadataService(connection_provider=lambda _root: conn)
        size, cached = service.get_dir_size(library, folder)
        assert size == 4
        assert cached is False

        size_again, cached_again = service.get_dir_size(library, folder)
        assert size_again == 4
        assert cached_again is True
        assert calls["n"] == 1
    finally:
        conn.close()


def test_metadata_service_dir_size_recomputes_after_ttl_expiry(tmp_path, monkeypatch):
    from AssetsManager.application import MetadataService
    from AssetsManager.core.project_data import ProjectData

    library = tmp_path / "library"
    folder = library / "folder"
    folder.mkdir(parents=True)
    (folder / "asset.bin").write_bytes(b"1234")

    calls = {"n": 0}
    real_compute = ProjectData.compute_dir_size

    def counting_compute(path, _depth=0, cancel_token=None):
        calls["n"] += 1
        return real_compute(path, _depth, cancel_token=cancel_token)

    monkeypatch.setattr(ProjectData, "compute_dir_size", staticmethod(counting_compute))

    conn = _memory_conn()
    try:
        service = MetadataService(connection_provider=lambda _root: conn)
        assert service.get_dir_size(library, folder) == (4, False)

        # Expire the TTL window without sleeping: the directory mtime is
        # unchanged, so only the TTL (not the mtime check) forces recompute.
        service._size_cache_ts[str(folder.resolve())] = time.time() - 31.0

        assert service.get_dir_size(library, folder) == (4, False)
        assert calls["n"] == 2
    finally:
        conn.close()


def test_metadata_service_size_cache_sweeps_expired_entries(tmp_path):
    from AssetsManager.application import MetadataService
    from AssetsManager.core.project_data import _SIZE_CACHE_TTL_SECONDS

    library = tmp_path / "library"
    folder = library / "folder"
    folder.mkdir(parents=True)
    (folder / "asset.bin").write_bytes(b"1234")

    conn = _memory_conn()
    try:
        service = MetadataService(connection_provider=lambda _root: conn)
        stale_key = str((library / "vanished").resolve())
        service._size_cache_ts[stale_key] = (
            time.time() - 2 * _SIZE_CACHE_TTL_SECONDS
        )
        fresh_key = str(folder.resolve())
        service._size_cache_ts[fresh_key] = time.time()

        # Any write through _mark_size_cached triggers the opportunistic
        # sweep; the fresh entry must survive while the stale one is gone.
        assert service.get_dir_size(library, folder) == (4, False)
        assert stale_key not in service._size_cache_ts
        assert fresh_key in service._size_cache_ts
    finally:
        conn.close()


def test_metadata_service_library_total_size_served_within_ttl(tmp_path, monkeypatch):
    from AssetsManager.application import MetadataService
    from AssetsManager.core.project_data import ProjectData

    library = tmp_path / "library"
    library.mkdir()
    (library / "asset.bin").write_bytes(b"1234")

    calls = {"n": 0}
    real_compute = ProjectData.compute_dir_size

    def counting_compute(path, _depth=0, cancel_token=None):
        calls["n"] += 1
        return real_compute(path, _depth, cancel_token=cancel_token)

    monkeypatch.setattr(ProjectData, "compute_dir_size", staticmethod(counting_compute))

    conn = _memory_conn()
    try:
        service = MetadataService(connection_provider=lambda _root: conn)
        service.set_library_total_size(library, 4321)

        size, cached = service.get_dir_size(library, library)
        assert size == 4321
        assert cached is True
        assert calls["n"] == 0

        service._size_cache_ts[str(library.resolve())] = time.time() - 31.0
        size_again, cached_again = service.get_dir_size(library, library)
        assert cached_again is False
        assert size_again == 4
        assert calls["n"] == 1
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


def test_metadata_service_accepts_managed_same_root_connection(tmp_path):
    from AssetsManager.application.metadata_service import MetadataService
    from AssetsManager.core.database import DatabaseManager

    library = tmp_path / "library"
    library.mkdir()
    asset = library / "asset.png"
    asset.write_bytes(b"asset")
    manager = DatabaseManager()
    try:
        conn = manager.connection_for(library)
        service = MetadataService(connection_provider=lambda _root: conn)

        service.set_notes(library, asset, "managed")

        assert service.get_notes(library, asset) == "managed"
    finally:
        manager.close()


def test_metadata_service_rejects_managed_foreign_root_connection(tmp_path):
    import pytest

    from AssetsManager.application.metadata_service import MetadataService
    from AssetsManager.core.database import DatabaseManager

    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    root_a.mkdir()
    root_b.mkdir()
    manager = DatabaseManager()
    try:
        foreign_conn = manager.connection_for(root_b)
        service = MetadataService(connection_provider=lambda _root: foreign_conn)

        with pytest.raises(ValueError, match="different library root"):
            service.get_notes(root_a, root_a / "asset.png")
    finally:
        manager.close()


@pytest.mark.parametrize(
    "operation",
    [
        "get_metadata",
        "get_notes",
        "set_notes",
        "get_urls",
        "add_url",
        "remove_url",
        "get_dir_size",
        "set_dir_size",
        "get_cached_stats",
        "get_cached_file_count",
        "batch_get_cached_file_counts",
        "batch_set_cached_file_counts",
    ],
)
def test_metadata_service_rejects_path_outside_library_root(tmp_path, operation):
    from AssetsManager.application.metadata_service import MetadataService

    library = tmp_path / "library"
    outside = tmp_path / "outside"
    library.mkdir()
    outside.mkdir()
    conn = _memory_conn()
    try:
        service = MetadataService(connection_provider=lambda _root: conn)
        with pytest.raises(ValueError, match="under library_root"):
            if operation == "get_metadata":
                service.get_metadata(library, outside / "asset.txt")
            elif operation == "get_notes":
                service.get_notes(library, outside / "asset.txt")
            elif operation == "set_notes":
                service.set_notes(library, outside / "asset.txt", "blocked")
            elif operation == "get_urls":
                service.get_urls(library, outside / "asset.txt")
            elif operation == "add_url":
                service.add_url(library, outside / "asset.txt", "https://example.com")
            elif operation == "remove_url":
                service.remove_url(library, outside / "asset.txt", "https://example.com")
            elif operation == "get_dir_size":
                service.get_dir_size(library, outside)
            elif operation == "set_dir_size":
                service.set_dir_size(library, outside, 1)
            elif operation == "get_cached_stats":
                service.get_cached_stats(library, [str(outside / "asset.txt")])
            elif operation == "get_cached_file_count":
                service.get_cached_file_count(library, outside)
            elif operation == "batch_get_cached_file_counts":
                service.batch_get_cached_file_counts(library, [str(outside)])
            else:
                service.batch_set_cached_file_counts(library, {str(outside): 1})
    finally:
        conn.close()


def test_add_url_is_atomic_across_connections(tmp_path):
    """Concurrent add_url calls on different connections must not lose entries."""
    from AssetsManager.application import MetadataService

    library = tmp_path / "library"
    library.mkdir()
    asset = library / "asset.txt"
    asset.write_text("asset", encoding="utf-8")

    conn_a = _memory_conn()
    conn_b = _memory_conn()
    # Both services point at the same database file so the two connections
    # share state; each service uses its own connection.
    db_path = tmp_path / "shared.db"
    conn_a.close()
    conn_b.close()
    import sqlite3

    conn_a = sqlite3.connect(str(db_path), check_same_thread=False)
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate

    conn_a.executescript(database._SCHEMA)
    migrate(conn_a)
    conn_b = sqlite3.connect(str(db_path), check_same_thread=False)

    svc_a = MetadataService(connection_provider=lambda _root: conn_a)
    svc_b = MetadataService(connection_provider=lambda _root: conn_b)
    try:
        svc_a.add_url(library, asset, "https://a.example")
        svc_b.add_url(library, asset, "https://b.example")
        # The two writes are independent connections; a read-modify-write
        # cycle would have let one overwrite the other.  The atomic JSON
        # append keeps both.
        assert svc_a.get_urls(library, asset) == ["https://a.example", "https://b.example"]
        # Deduplication still applies.
        svc_b.add_url(library, asset, "https://a.example")
        assert svc_a.get_urls(library, asset) == ["https://a.example", "https://b.example"]
    finally:
        conn_a.close()
        conn_b.close()
