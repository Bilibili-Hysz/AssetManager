"""Tests for TagRepository, MetadataRepository, ShareRepository, AuthRepository."""
import pytest
from AssetsManager.repositories.tag_repository import TagRepository
from AssetsManager.repositories.metadata_repository import MetadataRepository
from AssetsManager.repositories.share_repository import ShareRepository
from AssetsManager.repositories.auth_repository import AuthRepository
from AssetsManager.repositories.asset_index_repository import AssetIndexRepository
from AssetsManager.core import database


def _make_db(memory_db):
    conn = memory_db
    conn.executescript(database._SCHEMA)
    from AssetsManager.core.db_migrations import migrate
    migrate(conn)
    AuthRepository(conn).init_tables()
    ShareRepository(conn).init_table()
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

    def test_delete_path_removes_direct_and_descendant_tags(self, memory_db):
        conn = _make_db(memory_db)
        repo = TagRepository(conn)
        repo.add_tag("C:/library/folder", "root")
        repo.add_tag("C:/library/folder/child.txt", "child")
        repo.add_tag("C:/library/folder-copy/keep.txt", "keep")

        assert repo.delete_path("C:/library/folder") == 2
        assert repo.get_tags("C:/library/folder") == []
        assert repo.get_tags("C:/library/folder/child.txt") == []
        assert repo.get_tags("C:/library/folder-copy/keep.txt") == ["keep"]

    @pytest.mark.parametrize(
        ("root", "child", "sibling"),
        [
            (
                r"C:\library\folder",
                r"C:\library\folder\child.txt",
                r"C:\library\folder-copy\keep.txt",
            ),
            ("/library/folder", "/library/folder/child.txt", "/library/folder-copy/keep.txt"),
        ],
    )
    def test_get_tags_for_tree_uses_path_boundary(self, memory_db, root, child, sibling):
        repo = TagRepository(_make_db(memory_db))
        repo.add_tag(root, "root")
        repo.add_tag(child, "child")
        repo.add_tag(sibling, "keep")

        assert repo.get_tags_for_tree(root) == ["child"]

    @pytest.mark.parametrize(
        ("root", "child", "sibling"),
        [
            (
                r"C:\library\folder",
                r"C:\library\folder\child.txt",
                r"C:\library\folder-copy\keep.txt",
            ),
            ("/library/folder", "/library/folder/child.txt", "/library/folder-copy/keep.txt"),
        ],
    )
    def test_delete_path_uses_path_boundary(self, memory_db, root, child, sibling):
        repo = TagRepository(_make_db(memory_db))
        repo.add_tag(root, "root")
        repo.add_tag(child, "child")
        repo.add_tag(sibling, "keep")

        assert repo.delete_path(root) == 2
        assert repo.get_tags(root) == []
        assert repo.get_tags(child) == []
        assert repo.get_tags(sibling) == ["keep"]

    @pytest.mark.parametrize(
        ("old_root", "old_child", "sibling", "new_root", "new_child"),
        [
            (
                r"C:\library\folder",
                r"C:\library\folder\child.txt",
                r"C:\library\folder-copy\keep.txt",
                r"C:\archive\folder",
                r"C:\archive\folder\child.txt",
            ),
            (
                "/library/folder",
                "/library/folder/child.txt",
                "/library/folder-copy/keep.txt",
                "/archive/folder",
                "/archive/folder/child.txt",
            ),
        ],
    )
    def test_migrate_path_remaps_only_the_selected_tag_subtree(
        self, memory_db, old_root, old_child, sibling, new_root, new_child
    ):
        repo = TagRepository(_make_db(memory_db))
        repo.add_tag(old_root, "root")
        repo.add_tag(old_child, "child")
        repo.add_tag(sibling, "keep")

        assert repo.migrate_path(old_root, new_root) == 2
        assert repo.get_tags(old_root) == []
        assert repo.get_tags(old_child) == []
        assert repo.get_tags(new_root) == ["root"]
        assert repo.get_tags(new_child) == ["child"]
        assert repo.get_tags(sibling) == ["keep"]


# ── AssetIndexRepository ─────────────────────────────────────────

class TestAssetIndexRepository:

    def test_replace_parent_entries_and_query_by_parent(self, memory_db):
        repo = AssetIndexRepository(_make_db(memory_db))
        entries = [
            ("C:/library/folder/a.txt", "a.txt", ".txt", "file", 1, 1.0,
             "C:/library/folder", "C:/library", 1.0, 1.0),
            ("C:/library/folder/b.jpg", "b.jpg", ".jpg", "file", 2, 2.0,
             "C:/library/folder", "C:/library", 1.0, 1.0),
        ]

        repo.replace_parent_entries("C:/library/folder", "C:/library", entries, clear_existing=True)

        assert [entry.name for entry in repo.query_by_parent("C:/library", "C:/library/folder")] == [
            "a.txt", "b.jpg",
        ]
        assert [entry.name for entry in repo.query_by_extension("C:/library", ".jpg")] == ["b.jpg"]
        assert [entry.name for entry in repo.search_by_name("C:/library", "a.", 10)] == ["a.txt"]

    def test_delete_path_removes_descendants_without_prefix_collision(self, memory_db):
        repo = AssetIndexRepository(_make_db(memory_db), library_root="C:/library")
        entries = [
            ("C:/library/folder/child.txt", "child.txt", ".txt", "file", 1, 1.0,
             "C:/library/folder", "C:/library", 1.0, 1.0),
            ("C:/library/folder-copy/keep.txt", "keep.txt", ".txt", "file", 1, 1.0,
             "C:/library/folder-copy", "C:/library", 1.0, 1.0),
        ]
        repo.replace_parent_entries("C:/library/folder", "C:/library", [entries[0]], clear_existing=True)
        repo.replace_parent_entries("C:/library/folder-copy", "C:/library", [entries[1]], clear_existing=True)

        assert repo.delete_path("C:/library/folder") == 1
        assert repo.get_entry("C:/library/folder/child.txt") is None
        assert repo.get_entry("C:/library/folder-copy/keep.txt") is not None


class TestAssetIndexStructuredSearch:
    """search_structured: combined extension/size/mtime predicates."""

    LIB = "C:/library"

    @staticmethod
    def _populate(repo):
        entries = [
            # name, ext, kind, size, mtime
            ("C:/library/a.png", "a.png", ".png", "file", 100, 1000.0),
            ("C:/library/b.jpg", "b.jpg", ".jpg", "file", 2000, 2000.0),
            ("C:/library/c.png", "c.png", ".png", "file", 3000, 3000.0),
            ("C:/library/big_pack%100.zip", "big_pack%100.zip", ".zip", "file", 9999, 4000.0),
            ("C:/library/dir", "dir", "", "dir", 0, 1500.0),
        ]
        rows = [
            (path, name, ext, kind, size, mtime,
             path.rsplit("/", 1)[0], "C:/library", 1.0, 1.0)
            for (path, name, ext, kind, size, mtime) in entries
        ]
        for parent in ("C:/library", "C:/library/dir"):
            repo.replace_parent_entries(
                parent, "C:/library",
                [row for row in rows if row[7] == parent],
                clear_existing=True,
            )

    def _repo(self, memory_db):
        repo = AssetIndexRepository(_make_db(memory_db))
        self._populate(repo)
        return repo

    def _names(self, entries):
        return [entry.name for entry in entries]

    def test_no_filters_returns_every_entry_ordered_by_name(self, memory_db):
        repo = self._repo(memory_db)
        assert self._names(repo.search_structured(self.LIB)) == [
            "a.png", "b.jpg", "big_pack%100.zip", "c.png", "dir",
        ]

    def test_extension_filter_normalizes_case_and_leading_dot(self, memory_db):
        repo = self._repo(memory_db)
        assert self._names(repo.search_structured(self.LIB, extensions=["PNG", ".Jpg"])) == [
            "a.png", "b.jpg", "c.png",
        ]
        assert self._names(repo.search_structured(self.LIB, extensions=[])) == [
            "a.png", "b.jpg", "big_pack%100.zip", "c.png", "dir",
        ]

    def test_size_range_bounds_are_inclusive(self, memory_db):
        repo = self._repo(memory_db)
        assert self._names(repo.search_structured(self.LIB, size_min=2000, size_max=3000)) == [
            "b.jpg", "c.png",
        ]
        # Exact boundary value on one side only.
        assert self._names(repo.search_structured(self.LIB, size_min=3000)) == [
            "big_pack%100.zip", "c.png",
        ]
        assert self._names(repo.search_structured(self.LIB, size_max=100)) == [
            "a.png", "dir",
        ]

    def test_mtime_range_bounds_are_inclusive(self, memory_db):
        repo = self._repo(memory_db)
        assert self._names(repo.search_structured(self.LIB, mtime_after=2000.0, mtime_before=3000.0)) == [
            "b.jpg", "c.png",
        ]
        assert self._names(repo.search_structured(self.LIB, mtime_before=1000.0)) == ["a.png"]

    def test_combined_predicates(self, memory_db):
        repo = self._repo(memory_db)
        entries = repo.search_structured(
            self.LIB,
            extensions=[".png"],
            size_min=100,
            size_max=2000,
            mtime_after=500.0,
            mtime_before=2500.0,
        )
        assert self._names(entries) == ["a.png"]

    def test_name_substring_matches_and_escapes_like_wildcards(self, memory_db):
        repo = self._repo(memory_db)
        assert self._names(repo.search_structured(self.LIB, name_substring="pack")) == [
            "big_pack%100.zip",
        ]
        # A literal % / _ must not act as a wildcard: only the name that
        # actually contains the character matches (unescaped, both would
        # match every entry).
        assert self._names(repo.search_structured(self.LIB, name_substring="%")) == [
            "big_pack%100.zip",
        ]
        assert self._names(repo.search_structured(self.LIB, name_substring="_")) == [
            "big_pack%100.zip",
        ]
        assert self._names(repo.search_structured(self.LIB, name_substring="100")) == [
            "big_pack%100.zip",
        ]

    def test_sql_injection_vector_stays_literal(self, memory_db):
        repo = self._repo(memory_db)
        payload = "x%' ; DROP TABLE assets; --"
        assert repo.search_structured(self.LIB, name_substring=payload) == []
        # The assets table survived the injected statement.
        assert self._names(repo.search_structured(self.LIB, extensions=[".png"])) == [
            "a.png", "c.png",
        ]

    def test_order_by_whitelist_and_direction(self, memory_db):
        repo = self._repo(memory_db)
        assert self._names(repo.search_structured(self.LIB, order_by="size")) == [
            "dir", "a.png", "b.jpg", "c.png", "big_pack%100.zip",
        ]
        assert self._names(repo.search_structured(self.LIB, order_by="size", descending=True)) == [
            "big_pack%100.zip", "c.png", "b.jpg", "a.png", "dir",
        ]
        assert self._names(repo.search_structured(self.LIB, order_by="mtime", descending=True)) == [
            "big_pack%100.zip", "c.png", "b.jpg", "dir", "a.png",
        ]
        with pytest.raises(ValueError):
            repo.search_structured(self.LIB, order_by="name; DROP TABLE assets")

    def test_limit_offset_paging(self, memory_db):
        repo = self._repo(memory_db)
        assert self._names(repo.search_structured(self.LIB, limit=2)) == ["a.png", "b.jpg"]
        assert self._names(repo.search_structured(self.LIB, limit=2, offset=2)) == [
            "big_pack%100.zip", "c.png",
        ]
        assert repo.search_structured(self.LIB, limit=2, offset=99) == []
        with pytest.raises(ValueError):
            repo.search_structured(self.LIB, limit=0)
        with pytest.raises(ValueError):
            repo.search_structured(self.LIB, limit=True)
        with pytest.raises(ValueError):
            repo.search_structured(self.LIB, offset=-1)

    def test_library_root_isolation(self, memory_db):
        repo = self._repo(memory_db)
        assert repo.search_structured("C:/other-library") == []

    # ── v40: rating and favorite predicates ──────────────────────

    def _rate(self, memory_db, path, rating):
        memory_db.execute(
            "INSERT INTO file_meta(file_path, rating) VALUES (?, ?) "
            "ON CONFLICT(file_path) DO UPDATE SET rating=excluded.rating",
            (path, rating),
        )
        memory_db.commit()

    def test_rating_range_excludes_unrated_and_bounds_are_inclusive(self, memory_db):
        repo = self._repo(memory_db)
        self._rate(memory_db, "C:/library/a.png", 2)
        self._rate(memory_db, "C:/library/b.jpg", 4)
        self._rate(memory_db, "C:/library/c.png", None)

        # NULL (unrated) rows never match a positive rating bound.
        assert self._names(repo.search_structured(self.LIB, rating_min=1)) == [
            "a.png", "b.jpg",
        ]
        assert self._names(repo.search_structured(self.LIB, rating_min=2, rating_max=4)) == [
            "a.png", "b.jpg",
        ]
        assert self._names(repo.search_structured(self.LIB, rating_min=3)) == ["b.jpg"]
        assert self._names(repo.search_structured(self.LIB, rating_max=3)) == ["a.png"]
        assert repo.search_structured(self.LIB, rating_min=5) == []

    def test_order_by_rating_sorts_unrated_as_zero(self, memory_db):
        repo = self._repo(memory_db)
        self._rate(memory_db, "C:/library/b.jpg", 5)
        self._rate(memory_db, "C:/library/a.png", 1)
        # Unrated rows COALESCE to 0 and tie-break by name: first ascending,
        # last descending.
        assert self._names(repo.search_structured(self.LIB, order_by="rating")) == [
            "big_pack%100.zip", "c.png", "dir", "a.png", "b.jpg",
        ]
        assert self._names(repo.search_structured(self.LIB, order_by="rating", descending=True)) == [
            "b.jpg", "a.png", "big_pack%100.zip", "c.png", "dir",
        ]

    def test_favorite_keeps_only_viewer_scoped_rows(self, memory_db):
        repo = self._repo(memory_db)
        memory_db.executemany(
            "INSERT INTO library_favorites(owner_key, file_path) VALUES (?, ?)",
            [
                ("user:1", "C:/library/a.png"),
                ("user:1", "C:/library/c.png"),
                ("user:2", "C:/library/b.jpg"),
            ],
        )
        memory_db.commit()

        assert self._names(
            repo.search_structured(self.LIB, favorite=True, favorite_owner_key="user:1")
        ) == ["a.png", "c.png"]
        assert self._names(
            repo.search_structured(self.LIB, favorite=True, favorite_owner_key="user:2")
        ) == ["b.jpg"]
        # A viewer with no favorites matches nothing.
        assert repo.search_structured(
            self.LIB, favorite=True, favorite_owner_key="user:3"
        ) == []
        # favorite without an owner key is a hard error, never a full scan.
        with pytest.raises(ValueError):
            repo.search_structured(self.LIB, favorite=True)
        with pytest.raises(ValueError):
            repo.count_structured(self.LIB, favorite=True, favorite_owner_key="")

    def test_rating_predicate_rejects_non_integer_bounds(self, memory_db):
        repo = self._repo(memory_db)
        with pytest.raises(ValueError):
            repo.search_structured(self.LIB, rating_min=True)
        with pytest.raises(ValueError):
            repo.search_structured(self.LIB, rating_max="3")

    def test_count_structured_shares_predicates_without_paging(self, memory_db):
        repo = self._repo(memory_db)
        self._rate(memory_db, "C:/library/a.png", 5)
        memory_db.execute(
            "INSERT INTO library_favorites(owner_key, file_path) VALUES (?, ?)",
            ("user:1", "C:/library/a.png"),
        )
        memory_db.commit()

        assert repo.count_structured(self.LIB) == 5
        assert repo.count_structured(self.LIB, extensions=[".png"]) == 2
        assert repo.count_structured(self.LIB, rating_min=1) == 1
        assert repo.count_structured(
            self.LIB, favorite=True, favorite_owner_key="user:1"
        ) == 1
        assert repo.count_structured(
            self.LIB, rating_min=1, favorite=True, favorite_owner_key="user:1"
        ) == 1
        assert repo.count_structured(self.LIB, favorite=True, favorite_owner_key="nobody") == 0


# ── MetadataRepository ───────────────────────────────────────────

class TestMetadataRepository:

    def test_delete_path_removes_direct_and_descendant_metadata(self, memory_db):
        conn = _make_db(memory_db)
        repo = MetadataRepository(conn)
        repo.set_notes("C:/library/folder", "root")
        repo.set_notes("C:/library/folder/child.txt", "child")
        repo.set_notes("C:/library/folder-copy/keep.txt", "keep")

        assert repo.delete_path("C:/library/folder") == 2
        assert repo.get_notes("C:/library/folder") == ""
        assert repo.get_notes("C:/library/folder/child.txt") == ""
        assert repo.get_notes("C:/library/folder-copy/keep.txt") == "keep"

    @pytest.mark.parametrize(
        ("root", "child", "sibling"),
        [
            (
                r"C:\library\folder",
                r"C:\library\folder\child.txt",
                r"C:\library\folder-copy\keep.txt",
            ),
            ("/library/folder", "/library/folder/child.txt", "/library/folder-copy/keep.txt"),
        ],
    )
    def test_invalidate_size_cache_uses_path_boundary(self, memory_db, root, child, sibling):
        repo = MetadataRepository(_make_db(memory_db))
        for path, size in ((root, 1), (child, 2), (sibling, 3)):
            repo.set_cached_size(path, size, float(size))
            repo.set_cached_file_count(path, size, float(size))

        repo.invalidate_size_cache(root)

        assert repo.get_cached_size(root) is None
        assert repo.get_cached_size(child) is None
        assert repo.get_cached_size(sibling) == (3, 3.0)
        assert repo.get_cached_file_count(root) is None
        assert repo.get_cached_file_count(child) is None
        assert repo.get_cached_file_count(sibling) == 3

    @pytest.mark.parametrize(
        ("root", "child", "sibling"),
        [
            (
                r"C:\library\folder",
                r"C:\library\folder\child.txt",
                r"C:\library\folder-copy\keep.txt",
            ),
            ("/library/folder", "/library/folder/child.txt", "/library/folder-copy/keep.txt"),
        ],
    )
    def test_delete_path_uses_path_boundary(self, memory_db, root, child, sibling):
        repo = MetadataRepository(_make_db(memory_db))
        repo.set_notes(root, "root")
        repo.set_notes(child, "child")
        repo.set_notes(sibling, "keep")

        assert repo.delete_path(root) == 2
        assert repo.get_notes(root) == ""
        assert repo.get_notes(child) == ""
        assert repo.get_notes(sibling) == "keep"

    @pytest.mark.parametrize(
        ("old_root", "old_child", "sibling", "new_root", "new_child"),
        [
            (
                r"C:\library\folder",
                r"C:\library\folder\child.txt",
                r"C:\library\folder-copy\keep.txt",
                r"C:\archive\folder",
                r"C:\archive\folder\child.txt",
            ),
            (
                "/library/folder",
                "/library/folder/child.txt",
                "/library/folder-copy/keep.txt",
                "/archive/folder",
                "/archive/folder/child.txt",
            ),
        ],
    )
    def test_migrate_path_remaps_only_the_selected_metadata_subtree(
        self, memory_db, old_root, old_child, sibling, new_root, new_child
    ):
        repo = MetadataRepository(_make_db(memory_db))
        repo.set_notes(old_root, "root")
        repo.set_notes(old_child, "child")
        repo.set_notes(sibling, "keep")

        assert repo.migrate_path(old_root, new_root) == 2
        assert repo.get_notes(old_root) == ""
        assert repo.get_notes(old_child) == ""
        assert repo.get_notes(new_root) == "root"
        assert repo.get_notes(new_child) == "child"
        assert repo.get_notes(sibling) == "keep"

    def test_notes_roundtrip(self, memory_db):
        conn = _make_db(memory_db)
        repo = MetadataRepository(conn)
        repo.set_notes("/file.txt", "hello")
        assert repo.get_notes("/file.txt") == "hello"

    def test_library_total_size_preserves_existing_stats(self, memory_db):
        conn = _make_db(memory_db)
        conn.execute(
            "INSERT INTO library_stats "
            "(library_path, total_size, total_files, total_projects, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("/library", 10, 7, 3, 1.0),
        )
        conn.commit()

        MetadataRepository(conn).set_library_total_size("/library", 99)

        row = conn.execute(
            "SELECT total_size, total_files, total_projects, updated_at "
            "FROM library_stats WHERE library_path=?",
            ("/library",),
        ).fetchone()
        assert row[:3] == (99, 7, 3)
        assert row[3] > 1.0

    def test_library_total_size_supports_fixture_without_updated_at(self, memory_db):
        conn = memory_db
        conn.execute(
            "CREATE TABLE library_stats ("
            "library_path TEXT PRIMARY KEY, total_size INTEGER DEFAULT 0, "
            "total_files INTEGER DEFAULT 0, total_projects INTEGER DEFAULT 0)"
        )
        conn.execute(
            "INSERT INTO library_stats "
            "(library_path, total_size, total_files, total_projects) "
            "VALUES (?, ?, ?, ?)",
            ("/library", 10, 7, 3),
        )
        conn.commit()

        MetadataRepository(conn).set_library_total_size("/library", 99)

        assert conn.execute(
            "SELECT total_size, total_files, total_projects "
            "FROM library_stats WHERE library_path=?",
            ("/library",),
        ).fetchone() == (99, 7, 3)

    def test_urls_roundtrip(self, memory_db):
        conn = _make_db(memory_db)
        repo = MetadataRepository(conn)
        repo.set_urls("/file.txt", ["https://a.com", "https://b.com"])
        assert repo.get_urls("/file.txt") == ["https://a.com", "https://b.com"]

    def test_get_notes_and_urls_reads_both_columns_and_validates_urls(self, memory_db):
        conn = _make_db(memory_db)
        repo = MetadataRepository(conn)
        conn.execute(
            "INSERT INTO file_meta (file_path, notes, urls) VALUES (?, ?, ?)",
            ("/asset.txt", "note", '["https://example.com"]'),
        )
        conn.commit()

        assert repo.get_notes_and_urls("/asset.txt") == ("note", ["https://example.com"])

    def test_get_notes_and_urls_rejects_non_list_json(self, memory_db):
        conn = _make_db(memory_db)
        repo = MetadataRepository(conn)
        conn.execute(
            "INSERT INTO file_meta (file_path, notes, urls) VALUES (?, ?, ?)",
            ("/asset.txt", "note", '{"url": "https://example.com"}'),
        )
        conn.commit()

        assert repo.get_notes_and_urls("/asset.txt") == ("note", [])

    def test_get_notes_and_urls_normalizes_null_notes_to_empty_text(self):
        class _NullNotesConnection:
            def execute(self, _statement, _parameters):
                return type("_Cursor", (), {"fetchone": lambda _self: (None, "[]")})()

        repo = MetadataRepository(_NullNotesConnection())

        assert repo.get_notes_and_urls("/asset.txt") == ("", [])

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
        repo.set_cached_file_count("/dir", 42, 1000.0)
        assert repo.get_cached_file_count("/dir") == 42
        assert repo.get_cached_file_count_with_mtime("/dir") == (42, 1000.0)

    def test_cached_file_count_without_mtime_is_a_miss(self, memory_db):
        conn = _make_db(memory_db)
        repo = MetadataRepository(conn)
        # Legacy (pre-v35) row shape: a count with no mtime stamp is treated
        # as stale on every read path until it is rewritten with a stamp.
        conn.execute(
            "INSERT INTO file_meta (file_path, cached_file_count, cached_file_count_mtime) "
            "VALUES ('/legacy', 5, NULL)"
        )
        conn.commit()
        assert repo.get_cached_file_count("/legacy") is None
        assert repo.get_cached_file_count_with_mtime("/legacy") is None
        assert repo.batch_get_cached_file_counts(["/legacy"]) == {}
        assert repo.batch_get_cached_file_counts_with_mtime(["/legacy"]) == {}

        repo.set_cached_file_count("/legacy", 6, 123.0)
        assert repo.get_cached_file_count("/legacy") == 6
        assert repo.get_cached_file_count_with_mtime("/legacy") == (6, 123.0)
        assert repo.batch_get_cached_file_counts(["/legacy"]) == {"/legacy": 6}
        assert repo.batch_get_cached_file_counts_with_mtime(["/legacy"]) == {
            "/legacy": (6, 123.0)
        }

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

    def test_init_tables_does_not_create_share_schema(self, memory_db):
        conn = memory_db
        AuthRepository(conn).init_tables()

        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"users", "invite_codes"}.issubset(tables)
        assert "share_links" not in tables

    def test_auth_and_share_repositories_initialize_their_own_schemas(self, memory_db):
        AuthRepository(memory_db).init_tables()
        ShareRepository(memory_db).init_table()

        tables = {
            row[0]
            for row in memory_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"users", "invite_codes", "share_links"}.issubset(tables)

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


def test_list_tags_with_counts(memory_db):
    conn = _make_db(memory_db)
    repo = TagRepository(conn)
    repo.add_tag("/first.txt", "hero")
    repo.add_tag("/second.txt", "hero")
    repo.add_tag("/second.txt", "villain")

    assert repo.list_tags_with_counts() == [
        {"name": "hero", "count": 2},
        {"name": "villain", "count": 1},
    ]


def test_get_files_by_tag_case_insensitive(memory_db):
    conn = _make_db(memory_db)
    repo = TagRepository(conn)
    repo.add_tag("/first.txt", "Hero")

    assert repo.get_files_by_tag_case_insensitive("hero") == ["/first.txt"]


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
        file_path = str((tmp_path / "test.txt").resolve())
        LibraryService().open_session(lib_root)
        svc = MetadataService(connection_provider=lambda _root: conn)
        svc.set_notes(lib_root, file_path, "hello world")
        assert svc.get_notes(lib_root, file_path) == "hello world"
        svc.set_notes(lib_root, file_path, "")
        assert svc.get_notes(lib_root, file_path) == ""

    def test_urls_roundtrip(self, memory_db, tmp_path):
        from AssetsManager.application.metadata_service import MetadataService
        from AssetsManager.application.library_service import LibraryService
        conn = _make_db(memory_db)
        lib_root = str(tmp_path)
        file_path = str((tmp_path / "test.txt").resolve())
        LibraryService().open_session(lib_root)
        svc = MetadataService(connection_provider=lambda _root: conn)
        svc.add_url(lib_root, file_path, "https://example.com")
        svc.add_url(lib_root, file_path, "https://other.com")
        urls = svc.get_urls(lib_root, file_path)
        assert "https://example.com" in urls
        assert "https://other.com" in urls
        svc.remove_url(lib_root, file_path, "https://example.com")
        urls2 = svc.get_urls(lib_root, file_path)
        assert "https://example.com" not in urls2
        assert "https://other.com" in urls2

    def test_batch_file_counts_with_library_root(self, memory_db, tmp_path):
        from AssetsManager.application.metadata_service import MetadataService
        from AssetsManager.application.library_service import LibraryService
        conn = _make_db(memory_db)
        lib_root = str(tmp_path)
        LibraryService().open_session(lib_root)
        svc = MetadataService(connection_provider=lambda _root: conn)
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir3 = tmp_path / "dir3"
        svc.batch_set_cached_file_counts(lib_root, {str(dir1): 10, str(dir2): 20})
        # Service-level writes carry no directory mtime, so v35 records them
        # as stale entries: the row exists but reads treat it as a miss.
        assert svc.batch_get_cached_file_counts(
            lib_root, [str(dir1), str(dir2), str(dir3)]
        ) == {}
        MetadataRepository(conn).batch_set_cached_file_counts({
            str(dir1): (10, 111.0),
            str(dir2): (20, 222.0),
        })
        result = svc.batch_get_cached_file_counts(lib_root, [str(dir1), str(dir2), str(dir3)])
        assert result[str(dir1)] == 10
        assert result[str(dir2)] == 20
        assert str(dir3) not in result

    def test_batch_file_counts_alias_parity_and_single_db_key(self, memory_db, tmp_path):
        from AssetsManager.application.metadata_service import MetadataService
        from AssetsManager.application.library_service import LibraryService

        conn = _make_db(memory_db)
        lib_root = str(tmp_path)
        LibraryService().open_session(lib_root)
        svc = MetadataService(connection_provider=lambda _root: conn)
        target = tmp_path / "nested" / "dir1"
        alias = tmp_path / "nested" / "child" / ".." / "dir1"

        svc.batch_set_cached_file_counts(lib_root, {str(alias): 10, str(target): 20})

        # Mtime-less (service-level) writes stay stale on read...
        assert svc.batch_get_cached_file_counts(lib_root, [str(alias), str(target)]) == {}
        rows = conn.execute(
            "SELECT file_path, cached_file_count, cached_file_count_mtime FROM file_meta"
        ).fetchall()
        assert rows == [(str(target.resolve()), 20, None)]

        # ...while stamped writes keep alias/target parity on a single
        # canonical DB key and read back through the service.
        MetadataRepository(conn, library_root=lib_root).batch_set_cached_file_counts({
            str(alias): (10, 111.0),
            str(target): (20, 222.0),
        })
        result = svc.batch_get_cached_file_counts(lib_root, [str(alias), str(target)])
        assert result == {str(alias): 20, str(target): 20}
        rows = conn.execute(
            "SELECT file_path, cached_file_count, cached_file_count_mtime FROM file_meta "
            "WHERE cached_file_count_mtime IS NOT NULL"
        ).fetchall()
        assert rows == [(str(target.resolve()), 20, 222.0)]

    def test_get_cached_stats_alias_parity(self, memory_db, tmp_path):
        from AssetsManager.application.metadata_service import MetadataService
        from AssetsManager.application.library_service import LibraryService

        conn = _make_db(memory_db)
        lib_root = str(tmp_path)
        LibraryService().open_session(lib_root)
        svc = MetadataService(connection_provider=lambda _root: conn)
        target = tmp_path / "nested" / "file.bin"
        alias = tmp_path / "nested" / "child" / ".." / "file.bin"
        repo = MetadataRepository(conn)
        repo.set_cached_size(str(target.resolve()), 123, 456.0)

        result = svc.get_cached_stats(lib_root, [str(alias), str(target)])
        assert result == {str(alias): (123, 456.0), str(target): (123, 456.0)}

    def test_library_total_size(self, memory_db, tmp_path):
        from AssetsManager.application.metadata_service import MetadataService
        from AssetsManager.application.library_service import LibraryService
        conn = _make_db(memory_db)
        lib_root = str(tmp_path)
        LibraryService().open_session(lib_root)
        svc = MetadataService(connection_provider=lambda _root: conn)
        # Initially 0
        assert svc.get_library_total_size(lib_root) == 0
