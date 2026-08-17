"""Tests for ShareService and ShareLink domain model."""
import time
from contextlib import nullcontext
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from AssetsManager.domain.errors import ValidationError
from AssetsManager.domain.share import ShareLink
from AssetsManager.application.share_service import ShareService
from AssetsManager.core import database
from AssetsManager.repositories.share_repository import ShareRepository

if TYPE_CHECKING:
    from AssetsManager.application.context import LibrarySession


def _make_db(memory_db):
    conn = memory_db
    conn.executescript(database._SCHEMA)
    from AssetsManager.core.db_migrations import migrate
    migrate(conn)
    ShareRepository(conn).init_table()
    return conn


def _bound_service(memory_db, root):
    conn = _make_db(memory_db)
    session = SimpleNamespace(
        root_str=str(root),
        event_token="test-session-token",
        operation=nullcontext,
    )
    return ShareService(conn, "test-secret", session=cast("LibrarySession", session))


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

    def test_is_path_allowed_root_share_covers_whole_library(self):
        share = ShareLink(
            id="x", paths=(".",), created_by="user", created_at=0,
        )
        assert share.is_path_allowed("any/deep/path.txt") is True
        assert share.is_path_allowed("project/../public.txt") is True
        empty_scope = ShareLink(
            id="y", paths=("",), created_by="user", created_at=0,
        )
        assert empty_scope.is_path_allowed("file.txt") is True

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

    def test_bound_create_share_rejects_empty_path(self, tmp_path, memory_db):
        svc = _bound_service(memory_db, tmp_path)

        with pytest.raises(ValidationError) as exc_info:
            svc.create_share(paths=[""])

        assert exc_info.value.field == "paths"
        assert exc_info.value.message == "No valid paths"

    def test_bound_create_share_rejects_more_than_100_paths(self, tmp_path, memory_db):
        svc = _bound_service(memory_db, tmp_path)

        with pytest.raises(ValidationError) as exc_info:
            svc.create_share(paths=["asset.txt"] * 101)

        assert exc_info.value.field == "paths"
        assert exc_info.value.message == "Too many paths (max 100)"

    def test_bound_create_share_rejects_path_outside_library(self, tmp_path, memory_db):
        root = tmp_path / "library"
        root.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        svc = _bound_service(memory_db, root)

        with pytest.raises(ValidationError) as exc_info:
            svc.create_share(paths=[str(outside)])

        assert exc_info.value.field == "paths"
        assert exc_info.value.message == "Path escape detected"

    def test_bound_create_share_rejects_missing_path(self, tmp_path, memory_db):
        svc = _bound_service(memory_db, tmp_path)

        with pytest.raises(ValidationError) as exc_info:
            svc.create_share(paths=["missing.txt"])

        assert exc_info.value.field == "paths"
        assert exc_info.value.message == "No valid paths"

    def test_bound_create_share_normalizes_relative_and_absolute_paths(self, tmp_path, memory_db):
        root = tmp_path / "library"
        nested = root / "folder"
        nested.mkdir(parents=True)
        asset = nested / "asset.txt"
        asset.write_text("asset", encoding="utf-8")
        svc = _bound_service(memory_db, root)

        relative_share = svc.create_share(paths=["folder\\asset.txt"])
        absolute_share = svc.create_share(paths=[str(asset)])

        assert relative_share is not None
        assert absolute_share is not None
        assert relative_share.paths == ("folder/asset.txt",)
        assert absolute_share.paths == ("folder/asset.txt",)

    @pytest.mark.parametrize(
        ("kwargs", "field", "message"),
        [
            ({"password": 42}, "password", "Invalid password format"),
            ({"password": "abc"}, "password", "Password must be at least 8 characters"),
            ({"password": "1234567"}, "password", "Password must be at least 8 characters"),
            ({"password": "x" * 129}, "password", "Password must be less than 128 characters"),
            ({"expires_hours": "1"}, "expires_hours", "Invalid expiry format"),
            ({"expires_hours": True}, "expires_hours", "Invalid expiry format"),
            ({"expires_hours": 1.0}, "expires_hours", "Invalid expiry format"),
            ({"expires_hours": 0}, "expires_hours", "Expiry must be between 1 and 8760 hours"),
            ({"expires_hours": 8761}, "expires_hours", "Expiry must be between 1 and 8760 hours"),
            ({"max_downloads": "1"}, "max_downloads", "Invalid max downloads format"),
            ({"max_downloads": False}, "max_downloads", "Invalid max downloads format"),
            ({"max_downloads": 1.0}, "max_downloads", "Invalid max downloads format"),
            ({"max_downloads": 0}, "max_downloads", "Max downloads must be between 1 and 10000"),
            ({"max_downloads": 10001}, "max_downloads", "Max downloads must be between 1 and 10000"),
        ],
    )
    def test_create_share_rejects_invalid_options(self, memory_db, kwargs, field, message):
        conn = _make_db(memory_db)
        svc = ShareService(conn, "test-secret")

        with pytest.raises(ValidationError) as exc_info:
            svc.create_share(paths=["project"], **kwargs)

        assert exc_info.value.field == field
        assert exc_info.value.message == message

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"password": "abcd1234"},
            {"password": "x" * 128},
            {"expires_hours": 1},
            {"expires_hours": 8760},
            {"max_downloads": 1},
            {"max_downloads": 10000},
        ],
    )
    def test_create_share_accepts_option_boundaries(self, memory_db, kwargs):
        conn = _make_db(memory_db)
        svc = ShareService(conn, "test-secret")

        share = svc.create_share(paths=["project"], **kwargs)

        assert share is not None

    def test_empty_password_is_consistently_unprotected(self, memory_db):
        conn = _make_db(memory_db)
        svc = ShareService(conn, "test-secret")

        share = svc.create_share(paths=["project"], password="")

        assert share is not None
        assert share.has_password is False
        persisted = svc.get_share(share.id)
        assert persisted is not None
        assert persisted.has_password is False

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

    def test_verify_password_migrates_legacy_hash(self, tmp_path, memory_db):
        """A legacy-cost share hash is re-stamped after a successful verify."""
        import hashlib

        from AssetsManager.domain.auth import (
            LEGACY_PASSWORD_ITERATIONS,
            PASSWORD_ITERATIONS,
            verify_password,
        )

        conn = _make_db(memory_db)
        svc = ShareService(conn, "test-secret")
        share = svc.create_share(paths=["a"], password="secret123")
        assert share is not None

        salt = b"\x44" * 32
        key = hashlib.pbkdf2_hmac(
            "sha256", b"secret123", salt, LEGACY_PASSWORD_ITERATIONS
        )
        legacy = f"{salt.hex()}:{key.hex()}"
        conn.execute(
            "UPDATE share_links SET password_hash=? WHERE id=?", (legacy, share.id)
        )
        conn.commit()

        assert svc.verify_password(share.id, "secret123") is True

        stored = conn.execute(
            "SELECT password_hash FROM share_links WHERE id=?", (share.id,)
        ).fetchone()[0]
        assert stored.startswith(f"pbkdf2_sha256${PASSWORD_ITERATIONS}$")
        assert verify_password("secret123", stored) is True

    def test_failed_verify_does_not_migrate(self, tmp_path, memory_db):
        import hashlib

        from AssetsManager.domain.auth import LEGACY_PASSWORD_ITERATIONS

        conn = _make_db(memory_db)
        svc = ShareService(conn, "test-secret")
        share = svc.create_share(paths=["a"], password="secret123")
        assert share is not None

        salt = b"\x55" * 32
        key = hashlib.pbkdf2_hmac(
            "sha256", b"secret123", salt, LEGACY_PASSWORD_ITERATIONS
        )
        legacy = f"{salt.hex()}:{key.hex()}"
        conn.execute(
            "UPDATE share_links SET password_hash=? WHERE id=?", (legacy, share.id)
        )
        conn.commit()

        assert svc.verify_password(share.id, "wrong") is False
        stored = conn.execute(
            "SELECT password_hash FROM share_links WHERE id=?", (share.id,)
        ).fetchone()[0]
        assert stored == legacy

    def test_verify_password_survives_a_failed_migration(
        self, tmp_path, memory_db, monkeypatch
    ):
        import hashlib

        from AssetsManager.domain.auth import LEGACY_PASSWORD_ITERATIONS

        conn = _make_db(memory_db)
        svc = ShareService(conn, "test-secret")
        share = svc.create_share(paths=["a"], password="secret123")
        assert share is not None

        salt = b"\x66" * 32
        key = hashlib.pbkdf2_hmac(
            "sha256", b"secret123", salt, LEGACY_PASSWORD_ITERATIONS
        )
        legacy = f"{salt.hex()}:{key.hex()}"
        conn.execute(
            "UPDATE share_links SET password_hash=? WHERE id=?", (legacy, share.id)
        )
        conn.commit()

        def boom(_share_id, _password_hash):
            raise RuntimeError("disk on fire")

        monkeypatch.setattr(svc._repo, "set_password_hash", boom)

        # Access still granted; the migration retries on the next attempt.
        assert svc.verify_password(share.id, "secret123") is True

    def test_generate_and_verify_token(self, tmp_path, memory_db):
        conn = _make_db(memory_db)
        svc = ShareService(conn, "test-secret")

        share = svc.create_share(paths=["a"], password="secret123")
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

        share = svc.create_share(paths=["project"], password="secret123")
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

    def test_validate_access_root_share_allows_all_paths(self, tmp_path, memory_db):
        conn = _make_db(memory_db)
        svc = ShareService(conn, "test-secret")

        share = svc.create_share(paths=["."])
        assert share is not None
        result_share, err = svc.validate_access(share.id, "any/deep/file.txt")
        assert result_share is not None
        assert err == ""


# ── Brute-force protection ──────────────────────────────────────

class TestPasswordBruteForceGuard:

    def _service(self, memory_db):
        conn = _make_db(memory_db)
        return ShareService(conn, "test-secret")

    def test_attempts_allowed_below_threshold(self, memory_db):
        svc = self._service(memory_db)
        share = svc.create_share(paths=["a"], password="secret123")
        assert share is not None

        for _ in range(4):
            assert svc.password_attempt_blocked(share.id) == 0
            svc.record_password_failure(share.id)
        assert svc.password_attempt_blocked(share.id) == 0

    def test_fifth_failure_blocks_subsequent_attempts(self, memory_db):
        svc = self._service(memory_db)
        share = svc.create_share(paths=["a"], password="secret123")
        assert share is not None

        for _ in range(5):
            svc.record_password_failure(share.id)
        assert svc.password_attempt_blocked(share.id) > 0

    def test_success_resets_failure_counter(self, memory_db):
        svc = self._service(memory_db)
        share = svc.create_share(paths=["a"], password="secret123")
        assert share is not None

        for _ in range(4):
            svc.record_password_failure(share.id)
        assert svc.password_attempt_blocked(share.id) == 0

        svc.reset_password_failures(share.id)

        for _ in range(3):
            svc.record_password_failure(share.id)
        assert svc.password_attempt_blocked(share.id) == 0

    def test_lockout_expires_after_cooldown(self, memory_db):
        svc = self._service(memory_db)
        svc.MAX_PASSWORD_FAILURES = 2
        svc.PASSWORD_COOLDOWN_SECONDS = 0.05
        share = svc.create_share(paths=["a"], password="secret123")
        assert share is not None

        svc.record_password_failure(share.id)
        svc.record_password_failure(share.id)
        assert svc.password_attempt_blocked(share.id) > 0

        time.sleep(0.06)
        assert svc.password_attempt_blocked(share.id) == 0

    def test_verify_password_still_works_after_guard(self, memory_db):
        svc = self._service(memory_db)
        share = svc.create_share(paths=["a"], password="secret123")
        assert share is not None

        assert svc.verify_password(share.id, "secret123") is True
        assert svc.verify_password(share.id, "wrong-pass") is False
        assert svc.verify_password(share.id, "wrong-pass") is False
