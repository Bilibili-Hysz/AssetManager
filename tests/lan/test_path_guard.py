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
    import os

    from AssetsManager.lan.path_guard import PathEscapeError, PathGuard

    root = tmp_path / "library"
    outside = tmp_path / "outside.txt"
    guard = PathGuard(root)

    if os.path.normcase("A") == "a":
        # Windows: a drive-absolute request keeps its root, so containment
        # fails with PathEscapeError.
        with pytest.raises(PathEscapeError):
            guard.resolve(Path(outside))
    else:
        # POSIX shape-unification contract: PathGuard.resolve strips leading
        # separators, so an absolute request is coerced to a library-relative
        # path. The security invariant still holds — the result stays inside
        # the root and never denotes the outside file.
        resolved = guard.resolve(Path(outside))
        assert resolved.is_relative_to(root.resolve())
        assert resolved != outside.resolve()


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


# ── Shared predicates + single-validation-channel contract ─────────

def test_reject_path_text_rejects_control_characters_and_ads():
    import os

    from AssetsManager.lan.path_guard import InvalidPathError, reject_path_text

    with pytest.raises(InvalidPathError):
        reject_path_text("a\x00b")
    with pytest.raises(InvalidPathError):
        reject_path_text("a\nb")
    if os.name == "nt":
        with pytest.raises(InvalidPathError):
            reject_path_text("file.txt:stream")
    else:
        # POSIX ':' is a legal filename character.
        reject_path_text("file.txt:stream")


def test_assert_under_root_accepts_and_rejects(tmp_path):
    from AssetsManager.lan.path_guard import PathEscapeError, assert_under_root

    inside = tmp_path / "dir" / "file.txt"
    inside.parent.mkdir()
    inside.write_text("x", encoding="utf-8")
    assert assert_under_root(tmp_path, inside) == inside.resolve()

    outside = tmp_path.parent / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(PathEscapeError):
        assert_under_root(tmp_path, outside)


def test_share_target_resolution_uses_the_shared_gate():
    import tempfile
    from types import SimpleNamespace

    from AssetsManager.lan.routes.shares import _resolve_share_target

    library = Path(tempfile.mkdtemp(prefix="am-lib-"))
    (library / "scoped").mkdir()
    (library / "scoped" / "asset.txt").write_text("x", encoding="utf-8")
    lan = SimpleNamespace(library_root=library)
    share = SimpleNamespace(paths=["scoped"])

    assert _resolve_share_target(lan, share, "scoped/asset.txt") is not None
    # NUL must be rejected by the shared character gate, never reach pathlib.
    assert _resolve_share_target(lan, share, "scoped\x00evil") is None
    # Parent escape is rejected by the shared containment predicate.
    assert _resolve_share_target(lan, share, "../outside.txt") is None


def test_routes_do_not_reimplement_the_library_root_check():
    """Contract: route modules must not inline is_relative_to against the
    library root.  The shared predicates (PathGuard / assert_under_root) are
    the only library-root containment checks; share-scope checks inside
    _resolve_share_target are the sole permitted is_relative_to use."""
    import re
    from pathlib import Path as _P

    routes_dir = _P(__file__).resolve().parent.parent.parent / "AssetsManager" / "lan" / "routes"
    allowed = {"shares.py"}
    violations = []
    for file in sorted(routes_dir.glob("*.py")):
        src = file.read_text(encoding="utf-8")
        for m in re.finditer(r"\.is_relative_to\(", src):
            if file.name not in allowed:
                line_no = src[: m.start()].count("\n") + 1
                violations.append(f"{file.name}:{line_no}")
    assert violations == [], f"inline is_relative_to outside the allowlist: {violations}"


# ── Domain/LAN error unification contract ────────────────────────

def test_lan_path_errors_are_domain_subclasses_and_path_guard_errors():
    """The LAN PathGuard errors must be catchable both as domain errors
    (error mapping) and as PathGuardError (route-local handlers)."""
    from AssetsManager.domain.errors import (
        MissingPathError as DomainMissingPathError,
    )
    from AssetsManager.domain.errors import PathEscapeError as DomainPathEscapeError
    from AssetsManager.lan.path_guard import (
        MissingPathError,
        PathEscapeError,
        PathGuardError,
    )

    assert issubclass(PathEscapeError, DomainPathEscapeError)
    assert issubclass(PathEscapeError, PathGuardError)
    assert issubclass(MissingPathError, DomainMissingPathError)
    assert issubclass(MissingPathError, PathGuardError)

    # Raise points carry path/root context for the domain error payload.
    escape = PathEscapeError("/outside", "/root")
    assert escape.path == "/outside" and escape.root == "/root"
    missing = MissingPathError("/missing")
    assert missing.path == "/missing"


def test_path_guard_raise_sites_are_domain_catchable(tmp_path):
    from AssetsManager.domain.errors import PathEscapeError as DomainPathEscapeError
    from AssetsManager.lan.path_guard import PathGuard

    guard = PathGuard(tmp_path / "library")
    with pytest.raises(DomainPathEscapeError):
        guard.resolve("../outside.txt")
