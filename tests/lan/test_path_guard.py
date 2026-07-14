from pathlib import Path

import pytest


def test_path_guard_resolves_root(tmp_path):
    from AssetsManager.lan.path_guard import PathGuard

    guard = PathGuard(tmp_path)

    assert guard.resolve("") == tmp_path.resolve()
    assert guard.resolve("/") == tmp_path.resolve()


def test_path_guard_resolves_child(tmp_path):
    from AssetsManager.lan.path_guard import PathGuard

    child = tmp_path / "folder" / "asset.txt"
    guard = PathGuard(tmp_path)

    assert guard.resolve("folder/asset.txt") == child.resolve()


def test_path_guard_blocks_parent_escape(tmp_path):
    from AssetsManager.lan.path_guard import PathEscapeError, PathGuard

    guard = PathGuard(tmp_path / "library")

    with pytest.raises(PathEscapeError):
        guard.resolve("../outside.txt")


def test_path_guard_blocks_absolute_escape(tmp_path):
    from AssetsManager.lan.path_guard import PathEscapeError, PathGuard

    root = tmp_path / "library"
    outside = tmp_path / "outside.txt"
    guard = PathGuard(root)

    with pytest.raises(PathEscapeError):
        guard.resolve(Path(outside))


def test_path_guard_existing_key_requires_existing_file(tmp_path):
    from AssetsManager.lan.path_guard import MissingPathError, PathGuard

    guard = PathGuard(tmp_path)

    with pytest.raises(MissingPathError):
        guard.existing_key("missing.txt")

    asset = tmp_path / "asset.txt"
    asset.write_text("ok", encoding="utf-8")
    assert guard.existing_key("asset.txt") == str(asset.resolve())
