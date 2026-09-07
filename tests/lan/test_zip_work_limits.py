"""Resource limits apply to traversal and the complete ZIP disk extent."""
from contextlib import closing
import io
import os
from pathlib import Path
import random
import subprocess
import threading
from types import SimpleNamespace
import zipfile

import pytest

from AssetsManager.lan import zip_resources, zip_sources
from AssetsManager.lan.routes import _helpers
from AssetsManager.lan.zip_sources import ZipLimitExceeded, estimate_zip_source_bytes


@pytest.mark.parametrize("count, rejected", [(2, False), (3, True)])
def test_empty_files_consume_member_budget(tmp_path, monkeypatch, count, rejected):
    root = tmp_path / "root"
    root.mkdir()
    for index in range(count):
        (root / str(index)).touch()
    monkeypatch.setattr(zip_sources, "MAX_ZIP_MEMBERS", 2)
    archive = tmp_path / "out.zip"
    if rejected:
        with pytest.raises(ZipLimitExceeded, match="members"):
            estimate_zip_source_bytes([(root, None)])
        with pytest.raises(ZipLimitExceeded, match="members"):
            _helpers.build_zip_sync([(root, None)], str(archive))
        assert not archive.exists()
    else:
        assert estimate_zip_source_bytes([(root, None)]) == 0
        assert _helpers.build_zip_sync([(root, None)], str(archive)) == str(archive)
        with zipfile.ZipFile(archive) as result:
            assert len(result.namelist()) == count


@pytest.mark.parametrize("count, rejected", [(2, False), (3, True)])
def test_hidden_entries_consume_scan_budget(tmp_path, monkeypatch, count, rejected):
    root = tmp_path / "root"
    root.mkdir()
    for index in range(count):
        (root / f".{index}").touch()
    # The selected root itself also consumes one scan entry.
    monkeypatch.setattr(zip_sources, "MAX_ZIP_SCAN_ENTRIES", 3)
    if rejected:
        with pytest.raises(ZipLimitExceeded, match="scan"):
            estimate_zip_source_bytes([(root, None)])
    else:
        assert estimate_zip_source_bytes([(root, None)]) == 0


@pytest.mark.parametrize("depth, rejected", [(2, False), (3, True)])
def test_directory_depth_is_bounded_even_without_files(tmp_path, monkeypatch, depth, rejected):
    root = tmp_path / "root"
    root.mkdir()
    leaf = root
    for _ in range(depth):
        leaf = leaf / "child"
        leaf.mkdir()
    monkeypatch.setattr(zip_sources, "MAX_ZIP_DIRECTORY_DEPTH", 2)
    if rejected:
        with pytest.raises(ZipLimitExceeded, match="depth"):
            estimate_zip_source_bytes([(root, None)])
    else:
        assert estimate_zip_source_bytes([(root, None)]) == 0


def test_source_budget_is_shared_across_targets(tmp_path, monkeypatch):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.write_bytes(b"123")
    second.write_bytes(b"45")
    monkeypatch.setattr(zip_sources, "MAX_ZIP_SOURCE_BYTES", 5)
    assert estimate_zip_source_bytes([(first, None), (second, None)]) == 5
    second.write_bytes(b"456")
    with pytest.raises(ZipLimitExceeded, match="source"):
        estimate_zip_source_bytes([(first, None), (second, None)])


def test_estimate_and_builder_use_same_hidden_and_archive_name_rules(tmp_path):
    root = tmp_path / "root"
    child = root / "nested"
    child.mkdir(parents=True)
    (child / "file").write_bytes(b"123")
    (child / ".hidden").write_bytes(b"hidden")
    (root / ".private").mkdir()
    (root / ".private" / "secret").write_bytes(b"secret")
    archive = tmp_path / "out.zip"
    assert estimate_zip_source_bytes([(root, "folder")]) == 3
    assert _helpers.build_zip_sync([(root, "folder")], str(archive)) == str(archive)
    with zipfile.ZipFile(archive) as result:
        assert result.namelist() == ["folder/nested/file"]
        assert result.read("folder/nested/file") == b"123"


def test_native_hidden_attribute_preserves_preexisting_export_members(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    (root / "visible-name").write_bytes(b"123")
    real_info = zip_sources._entry_info

    def native_hidden(entry):
        info = real_info(entry)
        return SimpleNamespace(
            st_mode=info.st_mode, st_size=info.st_size, st_file_attributes=0x2,
        )

    monkeypatch.setattr(zip_sources, "_entry_info", native_hidden)
    assert estimate_zip_source_bytes([(root, None)]) == 3
    archive = tmp_path / "out.zip"
    assert _helpers.build_zip_sync([(root, None)], str(archive)) == str(archive)
    with zipfile.ZipFile(archive) as result:
        assert result.read("root/visible-name") == b"123"


class _TrackedScan:
    def __init__(self, iterator):
        self.iterator = iterator
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.iterator)

    def close(self):
        self.closed = True
        self.iterator.close()


class _ScanOS:
    def __init__(self, scandir):
        self.scandir = scandir

    def __getattr__(self, name):
        return getattr(os, name)


@pytest.mark.parametrize("exit_kind", ["close", "limit", "cancel"])
def test_early_exit_closes_all_scandir_handles(tmp_path, monkeypatch, exit_kind):
    root = tmp_path / "root"
    leaf = root / "child"
    leaf.mkdir(parents=True)
    (leaf / "file").touch()
    (leaf / "second").touch()
    scans = []
    real_scandir = os.scandir

    def tracked_scan(path):
        result = _TrackedScan(real_scandir(path))
        scans.append(result)
        return result

    monkeypatch.setattr(zip_sources, "os", _ScanOS(tracked_scan))
    cancel = threading.Event()

    def check_cancelled():
        if cancel.is_set():
            raise RuntimeError("cancelled")

    with closing(zip_sources.scan_zip_sources(
        [(root, None)], check_cancelled=check_cancelled,
    )) as sources:
        next(sources)
        assert len(scans) == 2
        if exit_kind == "limit":
            monkeypatch.setattr(zip_sources, "MAX_ZIP_MEMBERS", 1)
            with pytest.raises(ZipLimitExceeded):
                next(sources)
        elif exit_kind == "cancel":
            cancel.set()
            with pytest.raises(RuntimeError, match="cancelled"):
                next(sources)
    assert all(scan.closed for scan in scans)


def test_cancel_during_hidden_only_scan_is_observed(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    for index in range(20):
        (root / f".{index}").touch()
    calls = 0

    def check_cancelled():
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        list(zip_sources.scan_zip_sources([(root, None)], check_cancelled=check_cancelled))
    assert calls == 3


def test_reparse_entries_are_skipped_before_descent_and_counted(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    (root / "junction").mkdir()
    calls = []
    real_scan = os.scandir
    real_info = zip_sources._entry_info

    def marked_reparse(entry):
        info = real_info(entry)
        return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)

    def scan(path):
        calls.append(Path(path))
        return real_scan(path)

    monkeypatch.setattr(zip_sources, "_entry_info", marked_reparse)
    monkeypatch.setattr(zip_sources, "os", _ScanOS(scan))
    assert estimate_zip_source_bytes([(root, None)]) == 0
    assert calls == [root]
    monkeypatch.setattr(zip_sources, "MAX_ZIP_SCAN_ENTRIES", 1)
    with pytest.raises(ZipLimitExceeded, match="scan"):
        estimate_zip_source_bytes([(root, None)])


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_windows_junction_is_not_traversed(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret").write_bytes(b"private")
    link = root / "junction"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
        capture_output=True, check=False,
    )
    if result.returncode:
        pytest.skip(f"junction creation unavailable: {result.returncode}")
    try:
        assert estimate_zip_source_bytes([(root, None)]) == 0
        assert list(zip_sources.scan_zip_sources([(root, None)])) == []
    finally:
        link.rmdir()
    assert (outside / "secret").read_bytes() == b"private"


@pytest.mark.parametrize("source_bytes", [b"", random.Random(7).randbytes(65536)], ids=["empty", "incompressible"])
def test_output_budget_includes_compression_and_central_directory(tmp_path, monkeypatch, source_bytes):
    source = tmp_path / "source"
    source.write_bytes(source_bytes)
    reference = io.BytesIO()
    with zipfile.ZipFile(reference, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        with zf.open("source", "w") as member:
            member.write(source_bytes)
    exact_size = len(reference.getvalue())
    archive = tmp_path / "out.zip"
    monkeypatch.setattr(zip_resources, "MAX_ZIP_OUTPUT_BYTES", exact_size)
    assert _helpers.build_zip_sync([(source, None)], str(archive)) == str(archive)
    assert archive.stat().st_size == exact_size
    monkeypatch.setattr(zip_resources, "MAX_ZIP_OUTPUT_BYTES", exact_size - 1)
    with pytest.raises(ZipLimitExceeded, match="output"):
        _helpers.build_zip_sync([(source, None)], str(archive))
    assert not archive.exists()


def test_output_limit_rejects_compressor_flush_before_write(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.write_bytes(random.Random(5).randbytes(65536))
    archive = tmp_path / "out.zip"
    monkeypatch.setattr(zip_resources, "MAX_ZIP_OUTPUT_BYTES", 100)
    with pytest.raises(ZipLimitExceeded, match="output"):
        _helpers.build_zip_sync([(source, None)], str(archive))
    assert not archive.exists()


def test_output_budget_counts_highest_offset_not_header_rewrites(tmp_path):
    path = tmp_path / "output"
    with io.FileIO(path, "w+") as raw:
        with _helpers._BoundedZipOutput(raw, 4) as output:
            output.write(b"1234")
            output.seek(0)
            output.write(b"ABCD")
            with pytest.raises(ZipLimitExceeded):
                output.write(b"5")
    assert path.read_bytes() == b"ABCD"


def test_growth_between_scan_and_open_is_budget_error(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.write_bytes(b"1")
    archive = tmp_path / "out.zip"
    real_scan = _helpers.scan_zip_sources

    def raced_scan(*args, **kwargs):
        with closing(real_scan(*args, **kwargs)) as sources:
            for member in sources:
                source.write_bytes(b"12345")
                yield member

    monkeypatch.setattr(_helpers, "scan_zip_sources", raced_scan)
    monkeypatch.setattr(_helpers, "MAX_ZIP_SOURCE_BYTES", 4)
    with pytest.raises(ZipLimitExceeded, match="source"):
        _helpers.build_zip_sync([(source, None)], str(archive))
    assert not archive.exists()
