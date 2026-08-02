import sqlite3

import pytest

from AssetsManager.application.tag_service import TagService, TagServiceAdapter
from AssetsManager.core import database
from AssetsManager.core.db_migrations import migrate
from AssetsManager.domain.errors import ValidationError


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


@pytest.mark.parametrize("tag", ["", "   ", "x" * 201, None, 42])
def test_tag_service_rejects_invalid_add_tag_names(tmp_path, tag):
    service = TagService()

    with pytest.raises(ValidationError) as exc_info:
        service.add_tag(tmp_path, tmp_path / "asset.txt", tag)

    assert exc_info.value.field == "tag"


@pytest.mark.parametrize("new_name", ["", "   ", "x" * 201, None, 42])
def test_tag_service_rejects_invalid_rename_targets(tmp_path, new_name):
    service = TagService()

    with pytest.raises(ValidationError) as exc_info:
        service.rename_tag(tmp_path, "hero", new_name)

    assert exc_info.value.field == "new_name"
