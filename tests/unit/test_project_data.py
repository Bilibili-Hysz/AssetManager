"""Tests for core/project_data.py — per-library metadata via SQLite."""
import sqlite3
from pathlib import Path

import pytest

from AssetsManager.core import database
from AssetsManager.core.db_migrations import migrate


@pytest.fixture
def project_env(tmp_path):
    """Create a temporary library with DB and return (lib_root, conn)."""
    lib_root = str(tmp_path)
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    try:
        conn.executescript(database._SCHEMA)
        migrate(conn)
        from AssetsManager.application.library_service import LibraryService
        LibraryService().open_session(lib_root)
        yield lib_root, conn
    finally:
        conn.close()


class TestProjectData:

    def test_get_notes_empty(self, project_env):
        from AssetsManager.core.project_data import ProjectData
        lib_root, conn = project_env
        pd = ProjectData(lib_root, db_conn=conn)
        assert pd.get_notes(str(Path(lib_root) / "nonexistent.txt")) == ""

    def test_set_and_get_notes(self, project_env):
        from AssetsManager.core.project_data import ProjectData
        lib_root, conn = project_env
        pd = ProjectData(lib_root, db_conn=conn)
        file_path = str(Path(lib_root) / "test.txt")
        pd.set_notes(file_path, "hello world")
        assert pd.get_notes(file_path) == "hello world"

    def test_set_notes_empty_clears(self, project_env):
        from AssetsManager.core.project_data import ProjectData
        lib_root, conn = project_env
        pd = ProjectData(lib_root, db_conn=conn)
        file_path = str(Path(lib_root) / "test.txt")
        pd.set_notes(file_path, "hello")
        pd.set_notes(file_path, "")
        assert pd.get_notes(file_path) == ""

    def test_has_notes(self, project_env):
        from AssetsManager.core.project_data import ProjectData
        lib_root, conn = project_env
        pd = ProjectData(lib_root, db_conn=conn)
        file_path = str(Path(lib_root) / "test.txt")
        assert pd.has_notes(file_path) is False
        pd.set_notes(file_path, "note")
        assert pd.has_notes(file_path) is True

    def test_get_urls_empty(self, project_env):
        from AssetsManager.core.project_data import ProjectData
        lib_root, conn = project_env
        pd = ProjectData(lib_root, db_conn=conn)
        assert pd.get_urls(str(Path(lib_root) / "nonexistent.txt")) == []

    def test_add_and_get_url(self, project_env):
        from AssetsManager.core.project_data import ProjectData
        lib_root, conn = project_env
        pd = ProjectData(lib_root, db_conn=conn)
        file_path = str(Path(lib_root) / "test.txt")
        pd.add_url(file_path, "https://example.com")
        urls = pd.get_urls(file_path)
        assert "https://example.com" in urls

    def test_add_url_duplicate(self, project_env):
        from AssetsManager.core.project_data import ProjectData
        lib_root, conn = project_env
        pd = ProjectData(lib_root, db_conn=conn)
        file_path = str(Path(lib_root) / "test.txt")
        pd.add_url(file_path, "https://example.com")
        pd.add_url(file_path, "https://example.com")
        urls = pd.get_urls(file_path)
        assert urls.count("https://example.com") == 1

    def test_add_url_invalid(self, project_env):
        from AssetsManager.core.project_data import ProjectData
        lib_root, conn = project_env
        pd = ProjectData(lib_root, db_conn=conn)
        file_path = str(Path(lib_root) / "test.txt")
        with pytest.raises(ValueError, match="URL must start with"):
            pd.add_url(file_path, "not-a-url")

    def test_remove_url(self, project_env):
        from AssetsManager.core.project_data import ProjectData
        lib_root, conn = project_env
        pd = ProjectData(lib_root, db_conn=conn)
        file_path = str(Path(lib_root) / "test.txt")
        pd.add_url(file_path, "https://example.com")
        pd.remove_url(file_path, "https://example.com")
        urls = pd.get_urls(file_path)
        assert "https://example.com" not in urls

    def test_get_dir_size(self, project_env):
        from AssetsManager.core.project_data import ProjectData
        lib_root, conn = project_env
        pd = ProjectData(lib_root, db_conn=conn)
        # get_dir_size on a non-existent path should return (0, False)
        size, cached = pd.get_dir_size(str(Path(lib_root) / "nonexistent"))
        assert size == 0
        assert cached is False

    @pytest.mark.parametrize("separator", ["\\", "/"])
    def test_invalidate_size_cache_respects_subtree_boundary_and_like_escaping(
        self, monkeypatch, separator
    ):
        from AssetsManager.core.project_data import ProjectData

        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            migrate(conn)
            project_data = ProjectData(".", db_conn=conn)
            monkeypatch.setattr(project_data, "_key", lambda path: path)

            prefix = f"fixture{separator}folder%_"
            child = f"{prefix}{separator}child"
            sibling = f"{prefix}-copy{separator}keep"
            wildcard_decoy = f"fixture{separator}folderAB{separator}keep"
            rows = (prefix, child, sibling, wildcard_decoy)
            conn.executemany(
                "INSERT INTO file_meta "
                "(file_path, cached_size, cached_mtime, cached_file_count) "
                "VALUES (?, 1, 1.0, 1)",
                ((path,) for path in rows),
            )
            conn.commit()

            project_data.invalidate_size_cache(prefix)

            cached = {
                path: conn.execute(
                    "SELECT cached_size, cached_mtime, cached_file_count "
                    "FROM file_meta WHERE file_path=?",
                    (path,),
                ).fetchone()
                for path in rows
            }
            assert cached[prefix] == (None, None, None)
            assert cached[child] == (None, None, None)
            assert cached[sibling] == (1, 1.0, 1)
            assert cached[wildcard_decoy] == (1, 1.0, 1)
        finally:
            conn.close()

    def test_multiple_notes_different_files(self, project_env):
        from AssetsManager.core.project_data import ProjectData
        lib_root, conn = project_env
        pd = ProjectData(lib_root, db_conn=conn)
        pd.set_notes(str(Path(lib_root) / "a.txt"), "note A")
        pd.set_notes(str(Path(lib_root) / "b.txt"), "note B")
        assert pd.get_notes(str(Path(lib_root) / "a.txt")) == "note A"
        assert pd.get_notes(str(Path(lib_root) / "b.txt")) == "note B"

    def test_multiple_urls_same_file(self, project_env):
        from AssetsManager.core.project_data import ProjectData
        lib_root, conn = project_env
        pd = ProjectData(lib_root, db_conn=conn)
        file_path = str(Path(lib_root) / "test.txt")
        pd.add_url(file_path, "https://a.com")
        pd.add_url(file_path, "https://b.com")
        urls = pd.get_urls(file_path)
        assert "https://a.com" in urls
        assert "https://b.com" in urls

    def test_explicit_managed_connection_rejects_different_root(self, tmp_path):
        from AssetsManager.core.database import DatabaseManager
        from AssetsManager.core.project_data import ProjectData

        root_a = tmp_path / "root-a"
        root_b = tmp_path / "root-b"
        root_a.mkdir()
        root_b.mkdir()
        manager = DatabaseManager()
        try:
            root_b_conn = manager.connection_for(root_b)

            with pytest.raises(ValueError, match="different library root"):
                ProjectData(str(root_a), db_conn=root_b_conn)
        finally:
            manager.close()

    def test_explicit_managed_connection_accepts_same_root(self, tmp_path):
        from AssetsManager.core.database import DatabaseManager
        from AssetsManager.core.project_data import ProjectData

        root = tmp_path / "root"
        root.mkdir()
        manager = DatabaseManager()
        try:
            conn = manager.connection_for(root)

            project_data = ProjectData(str(root), db_conn=conn)

            assert project_data._db is conn
        finally:
            manager.close()

    def test_explicit_unmanaged_connection_remains_compatible(self, tmp_path):
        from AssetsManager.core.project_data import ProjectData

        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            migrate(conn)

            project_data = ProjectData(str(tmp_path), db_conn=conn)

            assert project_data._db is conn
        finally:
            conn.close()

    def test_deprecated_get_project_data_does_not_retain_process_global_store(self, project_env):
        from AssetsManager.core.project_data import get_project_data

        root, conn = project_env
        with pytest.warns(DeprecationWarning, match="get_project_data"):
            first = get_project_data(root, db_conn=conn)
        with pytest.warns(DeprecationWarning, match="get_project_data"):
            second = get_project_data(root, db_conn=conn)

        assert first is not second
        assert first._db is second._db is conn


def test_get_by_uid_does_not_mutate_settings(tmp_path):
    from AssetsManager.core import library_manager
    from AssetsManager.core.settings import AppSettings

    settings = AppSettings.instance()
    original = settings.get("library_records", {})
    uid = "abc123"
    try:
        settings.set("library_records", {uid: {"name": "Library", "path": str(tmp_path)}})
        result = library_manager.get_by_uid(uid)
        assert result is not None
        assert result["uid"] == uid
        assert "uid" not in settings.get("library_records", {})[uid]
    finally:
        settings.set("library_records", original)
