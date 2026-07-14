"""Tests for TagRepository, MetadataRepository, ShareRepository, AuthRepository."""
from AssetsManager.repositories.tag_repository import TagRepository
from AssetsManager.repositories.metadata_repository import MetadataRepository
from AssetsManager.repositories.share_repository import ShareRepository
from AssetsManager.repositories.auth_repository import AuthRepository
from AssetsManager.core import database
from AssetsManager.lan.auth import init_users_table


def _make_db(memory_db):
    conn = memory_db
    conn.executescript(database._SCHEMA)
    from AssetsManager.core.db_migrations import migrate
    migrate(conn)
    init_users_table(conn)
    return conn


# ── TagRepository ────────────────────────────────────────────────

class TestTagRepository:

    def test_add_and_get_tags(self, memory_db):
        conn = _make_db(memory_db)
        repo = TagRepository(conn)
        repo.add_tag("/file.txt", "hero")
        repo.add_tag("/file.txt", "villain")
        assert sorted(repo.get_tags("/file.txt")) == ["hero", "villain"]

    def test_remove_tag(self, memory_db):
        conn = _make_db(memory_db)
        repo = TagRepository(conn)
        repo.add_tag("/file.txt", "hero")
        repo.remove_tag("/file.txt", "hero")
        assert repo.get_tags("/file.txt") == []

    def test_get_tags_for_files(self, memory_db):
        conn = _make_db(memory_db)
        repo = TagRepository(conn)
        repo.add_tag("/a.txt", "tag1")
        repo.add_tag("/b.txt", "tag2")
        result = repo.get_tags_for_files(["/a.txt", "/b.txt", "/c.txt"])
        assert result["/a.txt"] == ["tag1"]
        assert result["/b.txt"] == ["tag2"]
        assert result["/c.txt"] == []

    def test_get_all_tags(self, memory_db):
        conn = _make_db(memory_db)
        repo = TagRepository(conn)
        repo.add_tag("/a.txt", "beta")
        repo.add_tag("/b.txt", "alpha")
        assert repo.get_all_tags() == ["alpha", "beta"]

    def test_get_files_by_tag(self, memory_db):
        conn = _make_db(memory_db)
        repo = TagRepository(conn)
        repo.add_tag("/a.txt", "hero")
        repo.add_tag("/b.txt", "hero")
        repo.add_tag("/c.txt", "villain")
        assert sorted(repo.get_files_by_tag("hero")) == ["/a.txt", "/b.txt"]

    def test_rename_tag(self, memory_db):
        conn = _make_db(memory_db)
        repo = TagRepository(conn)
        repo.add_tag("/a.txt", "old")
        repo.add_tag("/b.txt", "old")
        count = repo.rename_tag("old", "new")
        assert count == 2
        assert repo.get_tags("/a.txt") == ["new"]

    def test_delete_tag(self, memory_db):
        conn = _make_db(memory_db)
        repo = TagRepository(conn)
        repo.add_tag("/a.txt", "hero")
        repo.add_tag("/b.txt", "hero")
        count = repo.delete_tag("hero")
        assert count == 2
        assert repo.get_all_tags() == []


# ── MetadataRepository ───────────────────────────────────────────

class TestMetadataRepository:

    def test_notes_roundtrip(self, memory_db):
        conn = _make_db(memory_db)
        repo = MetadataRepository(conn)
        repo.set_notes("/file.txt", "hello")
        assert repo.get_notes("/file.txt") == "hello"

    def test_urls_roundtrip(self, memory_db):
        conn = _make_db(memory_db)
        repo = MetadataRepository(conn)
        repo.set_urls("/file.txt", ["https://a.com", "https://b.com"])
        assert repo.get_urls("/file.txt") == ["https://a.com", "https://b.com"]

    def test_add_remove_url_return_changed_urls(self, memory_db):
        conn = _make_db(memory_db)
        repo = MetadataRepository(conn)

        assert repo.add_url("/file.txt", "https://a.com") == ["https://a.com"]
        assert repo.add_url("/file.txt", "https://a.com") is None
        assert repo.add_url("/file.txt", "https://b.com") == ["https://a.com", "https://b.com"]
        assert repo.remove_url("/file.txt", "https://a.com") == ["https://b.com"]
        assert repo.remove_url("/file.txt", "https://a.com") is None

    def test_get_urls_malformed_json_returns_empty(self, memory_db):
        conn = _make_db(memory_db)
        repo = MetadataRepository(conn)
        conn.execute(
            "INSERT INTO file_meta (file_path, urls) VALUES (?, ?)",
            ("/bad.txt", "{not valid json"),
        )
        conn.commit()
        assert repo.get_urls("/bad.txt") == []

    def test_get_urls_wrong_json_type_returns_empty(self, memory_db):
        conn = _make_db(memory_db)
        repo = MetadataRepository(conn)
        conn.execute(
            "INSERT INTO file_meta (file_path, urls) VALUES (?, ?)",
            ("/obj.txt", '{"key": "value"}'),
        )
        conn.commit()
        assert repo.get_urls("/obj.txt") == []

    def test_get_urls_empty_string_returns_empty(self, memory_db):
        conn = _make_db(memory_db)
        repo = MetadataRepository(conn)
        conn.execute(
            "INSERT INTO file_meta (file_path, urls) VALUES (?, ?)",
            ("/empty.txt", ""),
        )
        conn.commit()
        assert repo.get_urls("/empty.txt") == []

    def test_add_url_survives_malformed_existing_json(self, memory_db):
        conn = _make_db(memory_db)
        repo = MetadataRepository(conn)
        conn.execute(
            "INSERT INTO file_meta (file_path, urls) VALUES (?, ?)",
            ("/bad.txt", "corrupted"),
        )
        conn.commit()
        result = repo.add_url("/bad.txt", "https://new.com")
        assert result == ["https://new.com"]

    def test_remove_url_survives_malformed_existing_json(self, memory_db):
        conn = _make_db(memory_db)
        repo = MetadataRepository(conn)
        conn.execute(
            "INSERT INTO file_meta (file_path, urls) VALUES (?, ?)",
            ("/bad.txt", "corrupted"),
        )
        conn.commit()
        result = repo.remove_url("/bad.txt", "https://anything.com")
        assert result is None

    def test_cached_size_roundtrip(self, memory_db):
        conn = _make_db(memory_db)
        repo = MetadataRepository(conn)
        repo.set_cached_size("/dir", 1024, 1000.0)
        result = repo.get_cached_size("/dir")
        assert result == (1024, 1000.0)

    def test_cached_file_count(self, memory_db):
        conn = _make_db(memory_db)
        repo = MetadataRepository(conn)
        repo.set_cached_file_count("/dir", 42)
        assert repo.get_cached_file_count("/dir") == 42

    def test_invalidate_size_cache(self, memory_db):
        conn = _make_db(memory_db)
        repo = MetadataRepository(conn)
        repo.set_cached_size("/dir", 1024, 1000.0)
        repo.invalidate_size_cache("/dir")
        assert repo.get_cached_size("/dir") is None

    def test_get_cached_stats_chunks_large_input(self, memory_db):
        conn = _make_db(memory_db)
        repo = MetadataRepository(conn)

        paths = []
        for i in range(1100):
            path = f"/dir/{i}"
            repo.set_cached_size(path, i + 1, 1000.0 + i)
            paths.append(path)

        result = repo.get_cached_stats(paths)

        assert len(result) == 1100
        assert result["/dir/0"] == (1, 1000.0)
        assert result["/dir/1099"] == (1100, 2099.0)


# ── ShareRepository ──────────────────────────────────────────────

class TestShareRepository:

    def test_insert_and_get(self, memory_db):
        conn = _make_db(memory_db)
        repo = ShareRepository(conn)
        repo.insert("abc123", ["project"], None, None, None, True, "admin")
        share = repo.get("abc123")
        assert share is not None
        assert share["id"] == "abc123"
        assert share["paths"] == ["project"]

    def test_list_all(self, memory_db):
        conn = _make_db(memory_db)
        repo = ShareRepository(conn)
        repo.insert("a", ["p1"], None, None, None, True, "alice")
        repo.insert("b", ["p2"], None, None, None, True, "bob")
        assert len(repo.list_all()) == 2
        assert len(repo.list_all(created_by="alice")) == 1

    def test_delete(self, memory_db):
        conn = _make_db(memory_db)
        repo = ShareRepository(conn)
        repo.insert("abc", ["p"], None, None, None, True, None)
        assert repo.delete("abc") is True
        assert repo.get("abc") is None

    def test_increment_download(self, memory_db):
        conn = _make_db(memory_db)
        repo = ShareRepository(conn)
        repo.insert("abc", ["p"], None, None, 5, True, None)
        repo.increment_download("abc")
        share = repo.get("abc")
        assert share is not None
        assert share["download_count"] == 1

    def test_increment_download_respects_limit_atomically(self, memory_db):
        conn = _make_db(memory_db)
        repo = ShareRepository(conn)
        repo.insert("abc", ["p"], None, None, 1, True, None)

        assert repo.increment_download("abc") is True
        assert repo.increment_download("abc") is False
        share = repo.get("abc", include_unavailable=True)
        assert share is not None
        assert share["download_count"] == 1

    def test_get_password_hash(self, memory_db):
        conn = _make_db(memory_db)
        repo = ShareRepository(conn)
        repo.insert("abc", ["p"], "hashed_pw", None, None, True, None)
        assert repo.get_password_hash("abc") == "hashed_pw"


# ── AuthRepository ──────────────────────────────────────────────

class TestAuthRepository:

    def test_insert_and_get_user(self, memory_db):
        conn = _make_db(memory_db)
        repo = AuthRepository(conn)
        user_id = repo.insert_user("alice", "hashed_pw", email="a@b.com")
        assert user_id is not None

        user = repo.get_user_by_id(user_id)
        assert user is not None
        assert user["username"] == "alice"
        assert user["email"] == "a@b.com"

    def test_get_user_by_username(self, memory_db):
        conn = _make_db(memory_db)
        repo = AuthRepository(conn)
        repo.insert_user("bob", "hashed_pw")

        user = repo.get_user_by_username("bob")
        assert user is not None
        assert user["username"] == "bob"

    def test_has_active_users(self, memory_db):
        conn = _make_db(memory_db)
        repo = AuthRepository(conn)
        assert repo.has_active_users() is False

        repo.insert_user("alice", "hashed_pw")
        assert repo.has_active_users() is True

    def test_set_user_active(self, memory_db):
        conn = _make_db(memory_db)
        repo = AuthRepository(conn)
        user_id = repo.insert_user("alice", "hashed_pw")
        assert user_id is not None

        assert repo.set_user_active(user_id, False) is True
        assert repo.has_active_users() is False

        assert repo.set_user_active(user_id, True) is True
        assert repo.has_active_users() is True

    def test_list_users(self, memory_db):
        conn = _make_db(memory_db)
        repo = AuthRepository(conn)
        repo.insert_user("alice", "pw1")
        repo.insert_user("bob", "pw2")

        users = repo.list_users()
        assert len(users) == 2
        assert {u["username"] for u in users} == {"alice", "bob"}

    def test_invite_code_roundtrip(self, memory_db):
        conn = _make_db(memory_db)
        repo = AuthRepository(conn)

        assert repo.insert_invite_code("ABC123", created_by="admin") is True
        code = repo.get_invite_code("ABC123")
        assert code is not None
        assert code["created_by"] == "admin"
        assert code["is_active"] == 1

        codes = repo.list_invite_codes()
        assert len(codes) == 1

        assert repo.deactivate_invite_code("ABC123") is True
        code = repo.get_invite_code("ABC123")
        assert code is not None
        assert code["is_active"] == 0

    def test_consume_invite_code_is_conditional(self, memory_db):
        conn = _make_db(memory_db)
        repo = AuthRepository(conn)
        assert repo.insert_invite_code("ABC123", created_by="admin") is True

        assert repo.consume_invite_code("ABC123", "alice") is True
        assert repo.consume_invite_code("ABC123", "bob") is False

    def test_insert_user_with_invite_rolls_back_on_reused_code(self, memory_db):
        conn = _make_db(memory_db)
        repo = AuthRepository(conn)
        assert repo.insert_invite_code("ABC123", created_by="admin") is True

        assert repo.insert_user_with_invite("alice", "hash", "ABC123") is not None
        assert repo.insert_user_with_invite("bob", "hash", "ABC123") is None
        assert repo.get_user_by_username("bob") is None


# ── TagRepository metadata ──────────────────────────────────────

def test_tag_metadata_roundtrip(memory_db):
    conn = _make_db(memory_db)
    repo = TagRepository(conn)
    repo.set_tag_metadata("hero", color="#ff0000", icon="👤", category="character")
    meta = repo.get_tag_metadata("hero")
    assert meta is not None
    assert meta["color"] == "#ff0000"
    assert meta["icon"] == "👤"
    assert meta["category"] == "character"


def test_get_tags_with_metadata(memory_db):
    conn = _make_db(memory_db)
    repo = TagRepository(conn)
    repo.add_tag("/file.txt", "hero")
    repo.set_tag_metadata("hero", color="#ff0000")
    repo.add_tag("/file.txt", "villain")

    tags = repo.get_tags_with_metadata()
    assert len(tags) == 2
    hero = next(t for t in tags if t["name"] == "hero")
    assert hero["count"] == 1
    assert hero["color"] == "#ff0000"
    villain = next(t for t in tags if t["name"] == "villain")
    assert villain["color"] == ""


def test_tag_service_metadata(memory_db):
    from AssetsManager.application.tag_service import TagService
    conn = _make_db(memory_db)
    svc = TagService()
    svc.set_tag_metadata("/lib", "hero", color="#00ff00", db_conn=conn)
    meta = svc.get_tag_metadata("/lib", "hero", db_conn=conn)
    assert meta is not None
    assert meta["color"] == "#00ff00"


# ── MetadataService via MetadataRepository ───────────────────

class TestMetadataService:

    def test_notes_roundtrip(self, memory_db, tmp_path):
        from AssetsManager.application.metadata_service import MetadataService
        from AssetsManager.application.library_service import LibraryService
        conn = _make_db(memory_db)
        lib_root = str(tmp_path)
        LibraryService().open_session(lib_root)
        svc = MetadataService(connection_provider=lambda _root: conn)
        svc.set_notes(lib_root, "/test.txt", "hello world")
        assert svc.get_notes(lib_root, "/test.txt") == "hello world"
        svc.set_notes(lib_root, "/test.txt", "")
        assert svc.get_notes(lib_root, "/test.txt") == ""

    def test_urls_roundtrip(self, memory_db, tmp_path):
        from AssetsManager.application.metadata_service import MetadataService
        from AssetsManager.application.library_service import LibraryService
        conn = _make_db(memory_db)
        lib_root = str(tmp_path)
        LibraryService().open_session(lib_root)
        svc = MetadataService(connection_provider=lambda _root: conn)
        svc.add_url(lib_root, "/test.txt", "https://example.com")
        svc.add_url(lib_root, "/test.txt", "https://other.com")
        urls = svc.get_urls(lib_root, "/test.txt")
        assert "https://example.com" in urls
        assert "https://other.com" in urls
        svc.remove_url(lib_root, "/test.txt", "https://example.com")
        urls2 = svc.get_urls(lib_root, "/test.txt")
        assert "https://example.com" not in urls2
        assert "https://other.com" in urls2

    def test_batch_file_counts_with_library_root(self, memory_db, tmp_path):
        from AssetsManager.application.metadata_service import MetadataService
        from AssetsManager.application.library_service import LibraryService
        conn = _make_db(memory_db)
        lib_root = str(tmp_path)
        LibraryService().open_session(lib_root)
        svc = MetadataService(connection_provider=lambda _root: conn)
        svc.batch_set_cached_file_counts(lib_root, {"/dir1": 10, "/dir2": 20})
        result = svc.batch_get_cached_file_counts(lib_root, ["/dir1", "/dir2", "/dir3"])
        assert result["/dir1"] == 10
        assert result["/dir2"] == 20
        assert "/dir3" not in result

    def test_library_total_size(self, memory_db, tmp_path):
        from AssetsManager.application.metadata_service import MetadataService
        from AssetsManager.application.library_service import LibraryService
        conn = _make_db(memory_db)
        lib_root = str(tmp_path)
        LibraryService().open_session(lib_root)
        svc = MetadataService(connection_provider=lambda _root: conn)
        # Initially 0
        assert svc.get_library_total_size(lib_root) == 0
