"""Lifecycle and containment tests for PluginMetadataRepository."""

import sqlite3

import pytest


def test_session_bound_repository_rejects_access_after_begin_close(tmp_path):
    from AssetsManager.application.library_service import LibraryService
    from AssetsManager.repositories.plugin_metadata_repository import (
        PluginMetadataRepository,
    )

    library = tmp_path / "library"
    service = LibraryService()
    session = service.open_session(library)
    try:
        file_path = library / "asset.txt"
        repo = PluginMetadataRepository(
            session.connection_for(library),
            session=session,
            library_root=library,
        )
        repo.upsert(str(file_path), "plugin", "name", "asset")
        assert repo.get_fields(str(file_path))["plugin"]["name"] == "asset"

        session._begin_close()
        with pytest.raises(RuntimeError, match="closed LibrarySession"):
            repo.get_fields(str(file_path))
        with pytest.raises(RuntimeError, match="closed LibrarySession"):
            repo.upsert(str(file_path), "plugin", "name", "blocked")
    finally:
        if not session.is_closed:
            session.close()
        else:
            session._finish_close()


def test_repository_root_containment_is_independent_of_controller(tmp_path):
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate
    from AssetsManager.repositories.plugin_metadata_repository import (
        PluginMetadataRepository,
    )

    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(database._SCHEMA)
        migrate(conn)
        library = tmp_path / "library"
        outside = tmp_path / "outside"
        library.mkdir()
        outside.mkdir()
        repo = PluginMetadataRepository(conn, library_root=library)

        with pytest.raises(ValueError, match="under library_root"):
            repo.get_fields(str(outside / "asset.txt"))
        with pytest.raises(ValueError, match="under library_root"):
            repo.delete_for_file(str(library / ".." / "outside" / "asset.txt"))
    finally:
        conn.close()


def test_legacy_raw_repository_remains_compatible_until_physical_close(tmp_path):
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate
    from AssetsManager.repositories.plugin_metadata_repository import (
        PluginMetadataRepository,
    )

    conn = sqlite3.connect(":memory:")
    conn.executescript(database._SCHEMA)
    migrate(conn)
    repo = PluginMetadataRepository(conn)
    file_path = str(tmp_path / "asset.txt")
    repo.upsert(file_path, "plugin", "name", "asset")
    assert repo.get_fields(file_path)["plugin"]["name"] == "asset"

    conn.close()
    with pytest.raises(sqlite3.ProgrammingError):
        repo.get_fields(file_path)


def test_same_root_reopen_does_not_revive_old_repository(tmp_path):
    from AssetsManager.application.library_service import LibraryService
    from AssetsManager.repositories.plugin_metadata_repository import (
        PluginMetadataRepository,
    )

    library = tmp_path / "library"
    service = LibraryService()
    old_session = service.open_session(library)
    old_repo = PluginMetadataRepository(
        old_session.connection_for(library),
        session=old_session,
        library_root=library,
    )
    old_session.close()

    new_session = service.open_session(library)
    try:
        new_repo = PluginMetadataRepository(
            new_session.connection_for(library),
            session=new_session,
            library_root=library,
        )
        file_path = str(library / "asset.txt")
        with pytest.raises(RuntimeError, match="closed LibrarySession"):
            old_repo.upsert(file_path, "plugin", "name", "old")
        new_repo.upsert(file_path, "plugin", "name", "new")
        assert new_repo.get_fields(file_path)["plugin"]["name"] == "new"
    finally:
        new_session.close()


def test_get_fields_for_children_escapes_like_wildcards(tmp_path):
    from AssetsManager.core import database
    from AssetsManager.core.db_migrations import migrate
    from AssetsManager.repositories.plugin_metadata_repository import (
        PluginMetadataRepository,
    )

    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(database._SCHEMA)
        migrate(conn)
        repo = PluginMetadataRepository(conn)
        target = tmp_path / "dir_with_underscore"
        sibling = tmp_path / "dirXwithXunderscore"
        percent = tmp_path / "50%_off"
        target.mkdir()
        sibling.mkdir()
        percent.mkdir()
        repo.upsert(str(target / "a.txt"), "plugin", "name", "a")
        repo.upsert(str(sibling / "b.txt"), "plugin", "name", "b")
        repo.upsert(str(percent / "c.txt"), "plugin", "name", "c")

        # A LIKE wildcard in the directory name must not bleed into siblings.
        assert repo.get_fields_for_children(str(target)) == {
            "plugin": {"name": "a"}
        }
        assert repo.get_fields_for_children(str(percent)) == {
            "plugin": {"name": "c"}
        }
    finally:
        conn.close()


def test_session_bound_repository_rejects_foreign_connection(tmp_path):
    from AssetsManager.application.library_service import LibraryService
    from AssetsManager.repositories.plugin_metadata_repository import (
        PluginMetadataRepository,
    )

    service = LibraryService()
    first = service.open_session(tmp_path / "first")
    try:
        second = service.open_session(tmp_path / "second")
        try:
            with pytest.raises(ValueError, match="does not belong"):
                PluginMetadataRepository(
                    second.connection_for(second.root),
                    session=first,
                    library_root=first.root,
                )
        finally:
            second.close()
    finally:
        if not first.is_closed:
            first.close()
