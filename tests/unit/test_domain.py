"""Tests for domain value objects: LibraryPath, AssetPath, AssetType, errors."""
from pathlib import Path

import pytest

from AssetsManager.domain.asset import AssetPath, AssetType, assert_under_root
from AssetsManager.domain.errors import (
    DomainError,
    DuplicateError,
    MissingPathError,
    NotFoundError,
    OperationNotPermitted,
    PathEscapeError,
    ValidationError,
)
from AssetsManager.domain.library import LibraryPath


# ── LibraryPath ──────────────────────────────────────────────────

class TestLibraryPath:

    def test_from_root_creates_deterministic_paths(self, tmp_path):
        lib = LibraryPath.from_root(tmp_path / "mylib", tmp_path / "runtime")
        assert lib.root == (tmp_path / "mylib").resolve()
        assert lib.data_dir.name.startswith("mylib_")
        assert lib.thumb_dir == lib.data_dir / ".thumbnails"

    def test_same_root_same_data_dir(self, tmp_path):
        a = LibraryPath.from_root(tmp_path / "lib", tmp_path / "runtime")
        b = LibraryPath.from_root(tmp_path / "lib", tmp_path / "runtime")
        assert a.data_dir == b.data_dir

    def test_different_root_different_data_dir(self, tmp_path):
        a = LibraryPath.from_root(tmp_path / "lib1", tmp_path / "runtime")
        b = LibraryPath.from_root(tmp_path / "lib2", tmp_path / "runtime")
        assert a.data_dir != b.data_dir

    def test_db_path(self, tmp_path):
        lib = LibraryPath.from_root(tmp_path / "lib", tmp_path / "runtime")
        assert lib.db_path == lib.data_dir / "assetmanager.db"

    def test_frozen(self, tmp_path):
        lib = LibraryPath.from_root(tmp_path / "lib", tmp_path / "runtime")
        with pytest.raises(AttributeError):
            lib.root = Path("/other")


# ── AssetPath ────────────────────────────────────────────────────

class TestAssetPath:

    def test_from_absolute(self, tmp_path):
        root = tmp_path / "library"
        root.mkdir()
        (root / "sub").mkdir()
        (root / "sub" / "file.txt").write_text("x")

        ap = AssetPath.from_absolute(root / "sub" / "file.txt", root)
        assert ap.relative == "sub/file.txt"
        assert ap.name == "file.txt"
        assert ap.extension == ".txt"
        assert ap.is_image is False

    def test_from_relative(self, tmp_path):
        root = tmp_path / "library"
        root.mkdir()
        (root / "image.png").write_bytes(b"png")

        ap = AssetPath.from_relative("image.png", root)
        assert ap.absolute == (root / "image.png").resolve()
        assert ap.name == "image.png"
        assert ap.is_image is True

    def test_frozen(self, tmp_path):
        root = tmp_path / "lib"
        root.mkdir()
        (root / "f.txt").write_text("x")
        ap = AssetPath.from_absolute(root / "f.txt", root)
        with pytest.raises(AttributeError):
            ap.relative = "other"


# ── AssetType ────────────────────────────────────────────────────

class TestAssetType:

    def test_file_type(self, tmp_path):
        (tmp_path / "image.png").write_bytes(b"png")
        at = AssetType.from_path(tmp_path / "image.png")
        assert at.is_dir is False
        assert at.category == "images"
        assert at.extension == ".png"

    def test_dir_type(self, tmp_path):
        tmp_path / "folder"
        at = AssetType.from_path(tmp_path)
        assert at.is_dir is True
        assert at.category == "folder"


# ── Domain errors ────────────────────────────────────────────────

class TestDomainErrors:

    def test_hierarchy(self):
        assert issubclass(PathEscapeError, DomainError)
        assert issubclass(MissingPathError, DomainError)
        assert issubclass(DuplicateError, DomainError)
        assert issubclass(NotFoundError, DomainError)
        assert issubclass(ValidationError, DomainError)

    def test_path_escape_error(self):
        e = PathEscapeError(path="../../etc", root="/data")
        assert e.path == "../../etc"
        assert e.root == "/data"
        assert "../../etc" in str(e)

    def test_not_found_error(self):
        e = NotFoundError(entity="Share", key="abc123")
        assert e.entity == "Share"
        assert e.key == "abc123"

    def test_validation_error(self):
        e = ValidationError(field="password", message="too short")
        assert e.field == "password"
        assert "too short" in str(e)

    def test_operation_not_permitted_hierarchy(self):
        assert issubclass(OperationNotPermitted, DomainError)
        e = OperationNotPermitted("cannot delete system folder")
        assert "cannot delete" in str(e)

    def test_operation_not_permitted_default_message(self):
        e = OperationNotPermitted()
        assert "not permitted" in str(e).lower()


# ── assert_under_root ─────────────────────────────────────────

class TestAssertUnderRoot:

    def test_valid_path(self, tmp_path):
        root = tmp_path / "lib"
        root.mkdir()
        (root / "file.txt").write_text("x")
        result = assert_under_root(root / "file.txt", root)
        assert result == (root / "file.txt").resolve()

    def test_escaped_path_raises(self, tmp_path):
        root = tmp_path / "lib"
        root.mkdir()
        with pytest.raises(PathEscapeError) as exc_info:
            assert_under_root(root / "../escape.txt", root)
        assert exc_info.value.path != ""
        assert exc_info.value.root != ""

    def test_absolute_outside_root_raises(self, tmp_path):
        root = tmp_path / "lib"
        root.mkdir()
        outside = tmp_path / "other" / "file.txt"
        outside.parent.mkdir()
        outside.write_text("x")
        with pytest.raises(PathEscapeError):
            assert_under_root(outside, root)
