"""Regression checks for bounded reads and all-or-nothing ZIP generation."""
import zipfile

import pytest

from AssetsManager.core.file_snapshot import FileSnapshotError, iter_snapshot
from AssetsManager.lan.routes import _helpers
from AssetsManager.lan.zip_sources import ZipLimitExceeded
from AssetsManager.lan import zip_sources


def test_growing_snapshot_never_returns_more_than_admitted_bytes(tmp_path):
    path = tmp_path / "growing.bin"
    path.write_bytes(b"abcd")
    source = iter_snapshot(tmp_path, path, max_bytes=4, chunk_size=2)
    assert next(source) == b"ab"
    with path.open("ab") as writer:
        writer.write(b"x" * 100)
    assert next(source) == b"cd"
    with pytest.raises(FileSnapshotError, match="changed"):
        next(source)
    assert source._opened.file.closed


def test_truncated_snapshot_cannot_finish_successfully(tmp_path):
    path = tmp_path / "shrinking.bin"
    path.write_bytes(b"abcd")
    source = iter_snapshot(tmp_path, path, chunk_size=2)
    with path.open("wb") as writer:
        writer.write(b"a")
    assert next(source) == b"a"
    with pytest.raises(FileSnapshotError, match="changed"):
        next(source)
    assert source._opened.file.closed


def test_zip_aggregate_budget_is_checked_on_opened_members(tmp_path, monkeypatch):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.write_bytes(b"abc")
    second.write_bytes(b"def")
    archive = tmp_path / "out.zip"
    monkeypatch.setattr(_helpers, "MAX_ZIP_SOURCE_BYTES", 5)
    with pytest.raises(ZipLimitExceeded):
        _helpers.build_zip_sync([(first, None), (second, None)], str(archive))
    assert not archive.exists()


def test_zip_budget_accepts_exact_boundary(tmp_path, monkeypatch):
    path = tmp_path / "source"
    path.write_bytes(b"abc")
    archive = tmp_path / "out.zip"
    monkeypatch.setattr(_helpers, "MAX_ZIP_SOURCE_BYTES", 3)
    assert _helpers.build_zip_sync([(path, None)], str(archive)) == str(archive)
    with zipfile.ZipFile(archive) as result:
        assert result.read("source") == b"abc"


@pytest.mark.parametrize("failure", ["source_changed", "write_failed"])
def test_zip_partial_failure_removes_archive_and_closes_source(tmp_path, monkeypatch, failure):
    path = tmp_path / "source"
    path.write_bytes(b"abcdef")
    archive = tmp_path / "out.zip"
    opened = []
    real_iter = _helpers.iter_safe_file
    real_write = zipfile._ZipWriteFile.write

    def capture_source(*args, **kwargs):
        source = real_iter(*args, **kwargs, chunk_size=2)
        opened.append(source)
        return source

    def fail_after_write(entry, data):
        result = real_write(entry, data)
        if failure == "write_failed":
            raise OSError("simulated disk failure after partial write")
        with path.open("ab") as writer:
            writer.write(b"x")
        return result

    monkeypatch.setattr(_helpers, "iter_safe_file", capture_source)
    monkeypatch.setattr(zipfile._ZipWriteFile, "write", fail_after_write)
    assert _helpers.build_zip_sync([(path, None)], str(archive)) is None
    assert opened and all(source._opened.file.closed for source in opened)
    assert not archive.exists()


def test_zip_missing_requested_source_is_not_reported_as_success(tmp_path):
    archive = tmp_path / "out.zip"
    assert _helpers.build_zip_sync([(tmp_path / "missing", None)], str(archive)) is None
    assert not archive.exists()


def test_zip_directory_scan_error_invalidates_archive(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    archive = tmp_path / "out.zip"

    def denied_scan(_path):
        raise PermissionError("subdirectory denied")

    with monkeypatch.context() as patch:
        patch.setattr(zip_sources.os, "scandir", denied_scan)
        assert _helpers.build_zip_sync([(root, None)], str(archive)) is None
    assert not archive.exists()
