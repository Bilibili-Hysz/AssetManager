"""Final-open containment and handle identity tests."""
from __future__ import annotations

import os
import subprocess

import pytest

from AssetsManager.core import file_snapshot
from AssetsManager.lan.path_guard import PathEscapeError
from AssetsManager.lan.safe_open import (
    FileIdentity,
    SafeOpenError,
    read_safe_file,
    safe_open_under_root,
)


def test_safe_open_reads_from_owned_handle_and_identity(tmp_path):
    target = tmp_path / "asset.bin"
    target.write_bytes(b"payload")

    with safe_open_under_root(tmp_path, target) as opened:
        assert opened.file.read() == b"payload"
        assert opened.size == 7
        assert opened.identity == FileIdentity.from_stat(target.stat())


def test_safe_open_rejects_escape_and_directories(tmp_path):
    outside = tmp_path.parent / "outside.bin"
    outside.write_bytes(b"outside")
    with pytest.raises(PathEscapeError):
        safe_open_under_root(tmp_path, outside)
    with pytest.raises(SafeOpenError):
        safe_open_under_root(tmp_path, tmp_path)


def test_safe_open_expected_identity_rejects_replacement(tmp_path):
    target = tmp_path / "asset.bin"
    target.write_bytes(b"old")
    expected = FileIdentity.from_stat(target.stat())
    target.write_bytes(b"new content")

    with pytest.raises(SafeOpenError):
        safe_open_under_root(tmp_path, target, expected_identity=expected)


def test_safe_open_rejects_ancestor_symlink_when_supported(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "asset.bin").write_bytes(b"outside")
    link = tmp_path / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    with pytest.raises(PathEscapeError):
        safe_open_under_root(tmp_path, link / "asset.bin")


def test_read_safe_file_binds_bytes_before_return(tmp_path):
    target = tmp_path / "asset.bin"
    target.write_bytes(b"payload")
    body, identity = read_safe_file(tmp_path, target)
    assert body == b"payload"
    assert identity.size == len(body)


def test_safe_open_fails_closed_when_ancestor_inspection_fails(
    tmp_path, monkeypatch
):
    if os.name != "nt":
        pytest.skip("reparse inspection leg is Windows-only")
    (tmp_path / "sub").mkdir()
    target = tmp_path / "sub" / "asset.bin"
    target.write_bytes(b"payload")
    real_lstat = file_snapshot.os.lstat

    def failing_lstat(path, *args, **kwargs):
        if str(path).endswith("sub"):
            raise OSError("inspection unavailable")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(file_snapshot.os, "lstat", failing_lstat)
    with pytest.raises(PathEscapeError):
        safe_open_under_root(tmp_path, target)


def _create_junction(link, target) -> bool:
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return result.returncode == 0


def test_safe_open_rejects_broken_junction_ancestor(tmp_path):
    if os.name != "nt":
        pytest.skip("Windows junction test")
    outside = tmp_path / "junction-target"
    outside.mkdir()
    (outside / "asset.bin").write_bytes(b"outside")
    junction = tmp_path / "broken-junction"
    import shutil

    try:
        if not _create_junction(junction, outside):
            pytest.skip("junction creation unavailable")
        # Removing the target leaves a dangling junction behind.
        shutil.rmtree(outside)

        with pytest.raises(PathEscapeError):
            safe_open_under_root(junction, junction / "asset.bin")
    finally:
        shutil.rmtree(junction, ignore_errors=True)
