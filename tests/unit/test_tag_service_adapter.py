import sqlite3

from AssetsManager.application.tag_service import TagService, TagServiceAdapter
from AssetsManager.core import database
from AssetsManager.core.db_migrations import migrate


def test_adapter_batch_methods_resolve_paths_and_hold_service_boundary(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    path = library / "nested" / "asset.txt"
    path.parent.mkdir()
    path.write_text("asset", encoding="utf-8")
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(database._SCHEMA)
    migrate(conn)
    try:
        service = TagService(connection_provider=lambda _root: conn)
        adapter = TagServiceAdapter(library, service)
        alias = str(library / "nested" / ".." / "nested" / "asset.txt")
        service.add_tag(library, path, "tag")

        assert adapter.get_tags_for_files([alias]) == {str(path.resolve()): ["tag"]}
        adapter.remove_file(alias)
        assert service.get_tags(library, path) == []
    finally:
        conn.close()
