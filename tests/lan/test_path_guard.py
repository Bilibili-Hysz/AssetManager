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


def test_path_guard_rejects_nul_and_control_characters(tmp_path):
    from AssetsManager.lan.path_guard import InvalidPathError, PathGuard

    guard = PathGuard(tmp_path)

    with pytest.raises(InvalidPathError):
        guard.resolve("a\x00b.txt")
    with pytest.raises(InvalidPathError):
        guard.resolve("a\x1fb.txt")
    with pytest.raises(InvalidPathError):
        guard.resolve("dir/\x7fsecret.txt")


def test_path_guard_turns_invalid_syntax_into_guard_error(tmp_path, monkeypatch):
    """A filesystem-level OSError/ValueError during resolution (Windows
    invalid names, pathlib strictness, permission failures) must surface as a
    400-class InvalidPathError, never as a raw exception that would 500."""
    from pathlib import Path

    from AssetsManager.lan.path_guard import InvalidPathError, PathGuard

    guard = PathGuard(tmp_path)

    def boom_oserror(self, strict=False):
        raise OSError(123, "invalid name")

    monkeypatch.setattr(Path, "resolve", boom_oserror)
    with pytest.raises(InvalidPathError):
        guard.resolve("a<b.txt")

    def boom_valueerror(self, strict=False):
        raise ValueError("bad path")

    monkeypatch.setattr(Path, "resolve", boom_valueerror)
    with pytest.raises(InvalidPathError):
        guard.resolve("bad-name")

    # Control characters are still rejected before any filesystem access,
    # independent of the resolve backend (the URL layer decodes %00 first).
    monkeypatch.undo()
    with pytest.raises(InvalidPathError):
        guard.resolve("a\x00b.txt")


def test_path_guard_rejects_ads_separator_on_windows(tmp_path):
    import os

    from AssetsManager.lan.path_guard import InvalidPathError, PathGuard

    guard = PathGuard(tmp_path)
    if os.name == "nt":
        with pytest.raises(InvalidPathError):
            guard.resolve("file.txt:Zone.Identifier")
        with pytest.raises(InvalidPathError):
            guard.resolve("dir/file.txt:stream")
    else:
        # On POSIX ':' is a legal filename character; only escapes matter.
        assert guard.resolve("file.txt:Zone.Identifier") == (
            tmp_path / "file.txt:Zone.Identifier"
        ).resolve()
