"""Low-batch unit tests for FileOperationService Windows-name validation
and structured error classification (bugs 9 and 22)."""
import errno
import os

import pytest

from AssetsManager.application.file_operation_service import (
    _windows_name_error,
    error_category,
)


# ── Bug 9: Windows reserved names / trailing dot-space / control chars ──

@pytest.mark.skipif(os.name != "nt", reason="Windows filename rules")
@pytest.mark.parametrize("name", [
    "CON", "con", "Con", "PRN", "AUX", "NUL",
    *(f"COM{n}" for n in range(1, 10)),
    *(f"LPT{n}" for n in range(1, 10)),
    "CON.txt", "con.log", "LPT1.bak", "con.con",
])
def test_windows_name_error_flags_reserved_device_names(name):
    assert _windows_name_error(name) == "reserved_name"


@pytest.mark.skipif(os.name != "nt", reason="Windows filename rules")
@pytest.mark.parametrize("name", [
    "foo.", "folder.", "name ", "name. ", "a" * 256, "\x01", "tab\tname",
])
def test_windows_name_error_flags_invalid_names(name):
    assert _windows_name_error(name) == "invalid_name"


@pytest.mark.skipif(os.name != "nt", reason="Windows filename rules")
@pytest.mark.parametrize("name", [
    "foo.txt", "My Folder", "COM10", "LPT10", "a" * 255, "123",
])
def test_windows_name_error_accepts_valid_names(name):
    assert _windows_name_error(name) is None


@pytest.mark.skipif(os.name != "nt", reason="Windows filename rules")
def test_create_folder_rejects_reserved_name(tmp_path):
    from AssetsManager.application import FileOperationService

    with pytest.raises(OSError, match="reserved_name"):
        FileOperationService().create_folder(tmp_path, "CON")


@pytest.mark.skipif(os.name != "nt", reason="Windows filename rules")
def test_rename_rejects_trailing_dot_name(tmp_path):
    from AssetsManager.application import FileOperationService

    old = tmp_path / "old.txt"
    old.write_text("asset", encoding="utf-8")

    with pytest.raises(OSError, match="invalid_name"):
        FileOperationService().rename(old, "foo.")

    assert old.exists()
    assert not (tmp_path / "foo.").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows filename rules")
def test_move_rejects_reserved_destination_name(tmp_path):
    from AssetsManager.application import FileOperationService

    src = tmp_path / "src.txt"
    src.write_text("asset", encoding="utf-8")

    with pytest.raises(OSError, match="reserved_name"):
        FileOperationService().move(src, tmp_path / "NUL")

    assert src.exists()


# ── Bug 22: structured error classification ──

@pytest.mark.parametrize("exc,expected", [
    (PermissionError(13, "Permission denied"), "permission_denied"),
    (FileNotFoundError(2, "No such file or directory"), "not_found"),
    (OSError(errno.ENOSPC, "No space left on device"), "disk_full"),
    # errno.EIO promotes to plain OSError, so the message keyword is the
    # only signal — and OSError(1, ...) would promote to PermissionError.
    (OSError(errno.EIO, "No space left on device"), "disk_full"),
    (OSError(28, "磁盘空间不足"), "disk_full"),
    (OSError(errno.EIO, "Operation not permitted"), "operation_failed"),
    (ValueError("bad value"), "operation_failed"),
    (RuntimeError("boom"), "operation_failed"),
])
def test_error_category_classifies_exceptions(exc, expected):
    assert error_category(exc) == expected


def test_move_to_directory_errors_are_category_prefixed(tmp_path):
    from AssetsManager.application import FileOperationService

    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()

    result = FileOperationService().move_to_directory(
        [src_dir / "missing.txt"], dst_dir
    )

    assert not result.ok
    assert len(result.errors) == 1
    assert result.errors[0].startswith("[not_found] ")


def test_delete_permanent_errors_are_category_prefixed(tmp_path):
    from AssetsManager.application import FileOperationService

    result = FileOperationService().delete_permanent(
        [tmp_path / "missing.txt"]
    )

    assert not result.ok
    assert len(result.errors) == 1
    assert result.errors[0].startswith("[not_found] ")
