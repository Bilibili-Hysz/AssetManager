import pytest

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


def test_tag_service_rename_tag_migrates_tag_metadata(tmp_path):
    from AssetsManager.application import TagService

    library = tmp_path / "library"
    library.mkdir()
    asset = library / "asset.txt"
    asset.write_text("asset", encoding="utf-8")

    conn = _memory_conn()
    try:
        service = TagService(connection_provider=lambda _root: conn)
        service.add_tag(library, asset, "hero")
        service.set_tag_metadata(
            library, "hero", color="red", icon="star", category="work"
        )
        service.rename_tag(library, "hero", "villain")

        assert service.get_tags(library, asset) == ["villain"]
        assert service.get_tag_metadata(library, "villain") == {
            "color": "red", "icon": "star", "category": "work",
        }
        assert service.get_tag_metadata(library, "hero") is None
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


def test_tag_service_accepts_managed_same_root_connection(tmp_path):
    from AssetsManager.application.tag_service import TagService
    from AssetsManager.core.database import DatabaseManager

    library = tmp_path / "library"
    library.mkdir()
    asset = library / "asset.png"
    asset.write_bytes(b"asset")
    manager = DatabaseManager()
    try:
        conn = manager.connection_for(library)
        service = TagService(connection_provider=lambda _root: conn)

        service.add_tag(library, asset, "managed")

        assert service.get_tags(library, asset) == ["managed"]
    finally:
        manager.close()


def test_tag_service_rejects_managed_foreign_root_connection(tmp_path):
    import pytest

    from AssetsManager.application.tag_service import TagService
    from AssetsManager.core.database import DatabaseManager

    root_a = tmp_path / "root-a"
    root_b = tmp_path / "root-b"
    root_a.mkdir()
    root_b.mkdir()
    manager = DatabaseManager()
    try:
        foreign_conn = manager.connection_for(root_b)
        service = TagService(connection_provider=lambda _root: foreign_conn)

        with pytest.raises(ValueError, match="different library root"):
            service.list_tags(root_a)
    finally:
        manager.close()


@pytest.mark.parametrize("operation", ["get_tags", "get_tags_for_files", "add_tag", "remove_tag", "remove_file", "get_tags_for_tree"])
def test_tag_service_rejects_path_outside_library_root(tmp_path, operation):
    from AssetsManager.application.tag_service import TagService

    library = tmp_path / "library"
    outside = tmp_path / "outside"
    library.mkdir()
    outside.mkdir()
    asset = outside / "asset.txt"
    conn = _memory_conn()
    try:
        service = TagService(connection_provider=lambda _root: conn)
        with pytest.raises(ValueError, match="under library_root"):
            if operation == "get_tags":
                service.get_tags(library, asset)
            elif operation == "get_tags_for_files":
                service.get_tags_for_files(library, [asset])
            elif operation == "add_tag":
                service.add_tag(library, asset, "blocked")
            elif operation == "remove_tag":
                service.remove_tag(library, asset, "blocked")
            elif operation == "remove_file":
                service.remove_file(library, asset)
            else:
                service.get_tags_for_tree(library, outside)
    finally:
        conn.close()


def test_tag_service_propagates_connection_provider_runtime_error(tmp_path):
    from AssetsManager.application.tag_service import TagService

    library = tmp_path / "library"
    library.mkdir()

    def provider(_root):
        raise RuntimeError("session is closed")

    service = TagService(connection_provider=provider)
    with pytest.raises(RuntimeError, match="session is closed"):
        service.get_all_tags(library)


def test_tag_service_propagates_connection_provider_ownership_error(tmp_path):
    from AssetsManager.application.tag_service import TagService

    library = tmp_path / "library"
    library.mkdir()

    def provider(_root):
        raise ValueError("foreign library root")

    service = TagService(connection_provider=provider)
    with pytest.raises(ValueError, match="foreign library root"):
        service.get_tags(library, library / "asset.txt")


def test_tag_service_propagates_closed_connection_error(tmp_path):
    from AssetsManager.application.tag_service import TagService

    library = tmp_path / "library"
    library.mkdir()
    conn = _memory_conn()
    conn.close()

    service = TagService()
    with pytest.raises(sqlite3.ProgrammingError):
        service.get_tags(library, library / "asset.txt", db_conn=conn)


@pytest.mark.parametrize("operation", [
    "get_tags",
    "list_tags",
    "add_tag",
    "remove_tag",
    "get_tags_with_metadata",
    "get_tag_metadata",
    "set_tag_metadata",
])
def test_tag_service_propagates_missing_schema_error(tmp_path, operation):
    from AssetsManager.application.tag_service import TagService

    library = tmp_path / "library"
    library.mkdir()
    asset = library / "asset.txt"
    conn = sqlite3.connect(":memory:", check_same_thread=False)

    try:
        service = TagService(connection_provider=lambda _root: conn)
        with pytest.raises(sqlite3.OperationalError):
            if operation == "get_tags":
                service.get_tags(library, asset)
            elif operation == "list_tags":
                service.list_tags(library)
            elif operation == "add_tag":
                service.add_tag(library, asset, "hero")
            elif operation == "remove_tag":
                service.remove_tag(library, asset, "hero")
            elif operation == "get_tags_with_metadata":
                service.get_tags_with_metadata(library)
            elif operation == "get_tag_metadata":
                service.get_tag_metadata(library, "hero")
            else:
                service.set_tag_metadata(library, "hero")
    finally:
        conn.close()


def test_tag_service_resolve_cache_reused_across_batch_calls(tmp_path, monkeypatch):
    """P0-5: batch tag reads resolve each file path exactly once.

    After the first get_tags_for_files() the resolve cache must serve the
    second batch and get_resolved_path() with zero new Path.resolve()
    syscalls for the same paths.
    """
    from AssetsManager.application.tag_service import TagService
    import AssetsManager.application.tag_service as tag_service_module

    library = tmp_path / "library"
    library.mkdir()
    asset = library / "nested" / "asset.txt"
    asset.parent.mkdir()
    asset.write_text("asset", encoding="utf-8")
    alias = str(library / "nested" / ".." / "nested" / "asset.txt")

    conn = _memory_conn()
    try:
        service = TagService(connection_provider=lambda _root: conn)
        service.add_tag(library, asset, "hero")

        resolve_inputs = []
        original = tag_service_module.Path.resolve

        def counting_resolve(self_path, *args, **kwargs):
            resolve_inputs.append(str(self_path))
            return original(self_path, *args, **kwargs)

        monkeypatch.setattr(tag_service_module.Path, "resolve", counting_resolve)

        expected_key = str(original(tag_service_module.Path(alias)))
        first = service.get_tags_for_files(library, [alias])
        assert first == {expected_key: ["hero"]}
        assert resolve_inputs.count(alias) == 1  # cold miss: one syscall

        second = service.get_tags_for_files(library, [alias])
        assert second == {expected_key: ["hero"]}
        assert resolve_inputs.count(alias) == 1  # cache hit: none

        assert service.get_resolved_path(library, alias) == expected_key
        assert resolve_inputs.count(alias) == 1
    finally:
        conn.close()
