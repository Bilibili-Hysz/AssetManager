"""Tests for ShareService and ShareLink domain model."""
import time
from dataclasses import FrozenInstanceError

import pytest

from AssetsManager.domain.share import ShareLink
from AssetsManager.application.share_service import ShareService
from AssetsManager.core import database
from AssetsManager.repositories.share_repository import ShareRepository


def _make_db(memory_db):
    conn = memory_db
    conn.executescript(database._SCHEMA)
    from AssetsManager.core.db_migrations import migrate
    migrate(conn)
    ShareRepository(conn).init_table()
    return conn


# ── ShareLink domain tests ──────────────────────────────────────

class TestShareLink:

    def test_from_db_row(self):
        row = {
            "id": "abc123",
            "paths": ["project/a", "project/b"],
            "created_by": "admin",
            "created_at": 1000.0,
            "expires_at": time.time() + 3600,
            "max_downloads": 10,
            "download_count": 3,
            "allow_preview": True,
            "password_hash": "hashed",
        }
        share = ShareLink.from_db_row(row)
        assert share.id == "abc123"
        assert share.paths == ("project/a", "project/b")
        assert share.has_password is True
        assert share.download_count == 3
        assert share.is_expired() is False
        assert share.is_download_limit_reached() is False
        assert share.can_download() is True

    def test_is_expired(self):
        share = ShareLink(
            id="x", paths=("a",), created_by="user",
            created_at=0, expires_at=time.time() - 10,
        )
        assert share.is_expired() is True
        assert share.can_download() is False

    def test_is_download_limit_reached(self):
        share = ShareLink(
            id="x", paths=("a",), created_by="user",
            created_at=0, max_downloads=5, download_count=5,
        )
        assert share.is_download_limit_reached() is True
        assert share.can_download() is False

    def test_is_path_allowed(self):
        share = ShareLink(
            id="x", paths=("project/sub",), created_by="user", created_at=0,
        )
        assert share.is_path_allowed("project/sub/file.txt") is True
        assert share.is_path_allowed("project/sub") is True
        assert share.is_path_allowed("other/file.txt") is False
        assert share.is_path_allowed("project/subfolder/file.txt") is False

    def test_is_path_allowed_blocks_dotdot_traversal(self):
        share = ShareLink(
            id="x", paths=("project",), created_by="user", created_at=0,
        )
        assert share.is_path_allowed("project/../public.txt") is False
        assert share.is_path_allowed("project/..") is False

    def test_to_public_dict_hides_sensitive_fields(self):
        share = ShareLink(
            id="x", paths=("a",), created_by="user",
            created_at=1000.0, has_password=True,
        )
        public = share.to_public_dict()
        assert "password_hash" not in public
        assert public["has_password"] is True
        assert public["id"] == "x"

    def test_frozen(self):
        share = ShareLink(id="x", paths=(), created_by="u", created_at=0)
        with pytest.raises(FrozenInstanceError):
            setattr(share, "id", "y")


# ── ShareService integration tests ──────────────────────────────

class TestShareService:

    def test_init_table_creates_share_schema(self, memory_db):
        ShareService(memory_db, "test-secret").init_table()

        tables = {
            row[0] for row in memory_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "share_links" in tables

    def test_create_and_get_share(self, tmp_path, memory_db):
        conn = _make_db(memory_db)
        svc = ShareService(conn, "test-secret")

        share = svc.create_share(paths=["project"], created_by="admin")
        assert share is not None
        assert share.id
        assert share.paths == ("project",)

        retrieved = svc.get_share(share.id)
        assert retrieved is not None
        assert retrieved.id == share.id

    def test_list_shares(self, tmp_path, memory_db):
        conn = _make_db(memory_db)
        svc = ShareService(conn, "test-secret")

        svc.create_share(paths=["a"], created_by="alice")
        svc.create_share(paths=["b"], created_by="bob")

        all_shares = svc.list_shares()
        assert len(all_shares) == 2

        alice_shares = svc.list_shares(created_by="alice")
        assert len(alice_shares) == 1
        assert alice_shares[0].created_by == "alice"

    def test_delete_share(self, tmp_path, memory_db):
        conn = _make_db(memory_db)
        svc = ShareService(conn, "test-secret")

        share = svc.create_share(paths=["a"])
        assert share is not None
        assert svc.delete_share(share.id) is True
        assert svc.get_share(share.id) is None

    def test_verify_password(self, tmp_path, memory_db):
        conn = _make_db(memory_db)
        svc = ShareService(conn, "test-secret")

        share = svc.create_share(paths=["a"], password="secret123")
        assert share is not None
        assert svc.verify_password(share.id, "secret123") is True
        assert svc.verify_password(share.id, "wrong") is False

    def test_generate_and_verify_token(self, tmp_path, memory_db):
        conn = _make_db(memory_db)
        svc = ShareService(conn, "test-secret")

        share = svc.create_share(paths=["a"], password="secret")
        assert share is not None
        token = svc.generate_token(share.id)
        assert svc.verify_token(token, share.id) is True
        assert svc.verify_token("invalid", share.id) is False

    def test_validate_access_no_password(self, tmp_path, memory_db):
        conn = _make_db(memory_db)
        svc = ShareService(conn, "test-secret")

        share = svc.create_share(paths=["project"])
        assert share is not None
        result_share, err = svc.validate_access(share.id, "project/file.txt")
        assert result_share is not None
        assert err == ""

    def test_validate_access_with_password(self, tmp_path, memory_db):
        conn = _make_db(memory_db)
        svc = ShareService(conn, "test-secret")

        share = svc.create_share(paths=["project"], password="secret")
        assert share is not None

        _, err = svc.validate_access(share.id, "project/file.txt")
        assert err == "Unauthorized"

        token = svc.generate_token(share.id)
        result_share, err = svc.validate_access(share.id, "project/file.txt", token=token)
        assert result_share is not None
        assert err == ""

    def test_validate_access_expired(self, tmp_path, memory_db):
        conn = _make_db(memory_db)
        svc = ShareService(conn, "test-secret")

        share = svc.create_share(paths=["project"], expires_hours=1)
        assert share is not None
        # Manually set expires_at to the past
        conn.execute("UPDATE share_links SET expires_at=? WHERE id=?",
                     (time.time() - 10, share.id))
        conn.commit()

        result_share, err = svc.validate_access(share.id, "project/file.txt")
        assert result_share is not None
        assert err == "Share expired"

    def test_validate_access_download_limit_reached(self, tmp_path, memory_db):
        conn = _make_db(memory_db)
        svc = ShareService(conn, "test-secret")

        share = svc.create_share(paths=["project"], max_downloads=1)
        assert share is not None
        conn.execute("UPDATE share_links SET download_count=1 WHERE id=?", (share.id,))
        conn.commit()

        result_share, err = svc.validate_access(share.id, "project/file.txt")
        assert result_share is not None
        assert err == "Download limit reached"

    def test_validate_access_path_not_allowed(self, tmp_path, memory_db):
        conn = _make_db(memory_db)
        svc = ShareService(conn, "test-secret")

        share = svc.create_share(paths=["project"])
        assert share is not None
        _, err = svc.validate_access(share.id, "other/file.txt")
        assert err == "File not in share scope"
