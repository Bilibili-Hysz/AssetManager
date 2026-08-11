"""Low-batch regression tests for path_resolver identity and slot fixes.

Covers:
* Bug 2  — root identity map_key stays stable when a root flips between
           existing and missing states (symlink/junction target switching);
           the key is a pure lexical normalization and never follows links.
* Bug 9  — 40-bit digest collisions between two same-basename roots select a
           deterministic secondary slot (``-2``) instead of rejecting the
           open; the primary name stays unchanged for the owning root.
* Bug 14 — empty/degenerate roots get a deterministic independent slot
           instead of sharing the generic ``RuntimeData/_temp`` directory.
"""
import os
from pathlib import Path
from unittest import mock

from AssetsManager.core import path_resolver


def _runtime(tmp_path, monkeypatch):
    runtime = tmp_path / "RuntimeData"
    monkeypatch.setattr(path_resolver, "runtime_root", lambda: runtime)
    return runtime


# ── Bug 2: stable lexical map_key across existence states ────────────────


def test_root_identity_map_key_is_stable_across_existence_states(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    root = tmp_path / "Libs" / "MyLibrary"
    real_resolve = Path.resolve

    def identity_for(exists, resolve_raises):
        def resolve_side(*args, **kwargs):
            if resolve_raises:
                raise RuntimeError("strict resolve failed")
            return real_resolve(*args, **kwargs)

        with mock.patch.object(Path, "exists", return_value=exists), mock.patch.object(
            Path, "resolve", resolve_side
        ):
            return path_resolver.root_identity(str(root), strict=False)

    online = identity_for(exists=True, resolve_raises=False)
    offline = identity_for(exists=False, resolve_raises=False)
    offline_missing_parent = identity_for(exists=False, resolve_raises=True)

    # Same physical library must keep one key whether its symlink/junction
    # target is online, offline, or its parent chain is entirely missing.
    assert online.map_key == offline.map_key == offline_missing_parent.map_key
    assert online.display_path == offline.display_path

    # The key is the pure lexical normalization — no symlink resolution.
    expected = os.path.normcase(os.path.normpath(os.path.abspath(str(root))))
    assert online.map_key == expected

    # Derived names, lock, and identity marker all follow the stable key.
    assert path_resolver.library_data_name(online) == path_resolver.library_data_name(offline)
    assert path_resolver.library_lock_path(online) == path_resolver.library_lock_path(offline)
    assert path_resolver.library_data_identity_path(online) == path_resolver.library_data_identity_path(offline)
    assert path_resolver.library_lock_path(online).parent == runtime / "Shared"


# ── Bug 9: collision probe picks a secondary slot ─────────────────────────


def _force_digest_collision(monkeypatch, digest="deadbeef42"):
    def fake_sha256(_data):
        fake = mock.Mock()
        fake.hexdigest.return_value = digest
        return fake

    monkeypatch.setattr(path_resolver.hashlib, "sha256", fake_sha256)


def test_library_data_name_probes_secondary_slot_on_digest_collision(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    root_a = tmp_path / "A" / "Assets"
    root_b = tmp_path / "B" / "Assets"
    root_a.mkdir(parents=True)
    root_b.mkdir(parents=True)
    _force_digest_collision(monkeypatch)

    # Both roots would map to the same primary slot: same basename + same digest.
    primary = path_resolver.library_data_name(root_a)
    assert primary == "Assets_deadbeef42"
    assert path_resolver.library_data_name(root_b) == primary

    # The owning root published its identity marker and created its data slot.
    shared = runtime / "Shared"
    shared.mkdir(parents=True)
    (shared / f"{primary}.identity").write_text(
        path_resolver.root_identity(root_a, strict=False).map_key, encoding="utf-8"
    )
    (runtime / primary).mkdir()

    # The colliding root must probe a secondary slot instead of failing.
    name_b = path_resolver.library_data_name(root_b)
    assert name_b == f"{primary}-2"
    assert name_b == path_resolver.library_data_name(root_b)  # deterministic
    assert path_resolver.library_data_dir(root_b) == runtime / name_b
    assert path_resolver.db_path(root_b) == runtime / name_b / "assetmanager.db"
    assert path_resolver.library_data_identity_path(root_b) == shared / f"{name_b}.identity"

    # The owning root still resolves to its primary slot.
    assert path_resolver.library_data_name(root_a) == primary
    assert path_resolver.library_data_dir(root_a) == runtime / primary


def test_library_data_name_keeps_primary_for_foreign_marker_without_data_dir(
    tmp_path, monkeypatch
):
    """A foreign marker alone is not treated as an occupied slot.

    The database layer's formal-marker validation keeps the fail-closed
    contract for stale/corrupt marker states (marker without its data dir).
    """
    runtime = _runtime(tmp_path, monkeypatch)
    root = tmp_path / "Assets"
    root.mkdir(parents=True)
    _force_digest_collision(monkeypatch)

    primary = path_resolver.library_data_name(root)
    shared = runtime / "Shared"
    shared.mkdir(parents=True)
    (shared / f"{primary}.identity").write_text("different-root", encoding="utf-8")

    assert path_resolver.library_data_name(root) == primary
    assert path_resolver.library_data_dir(root) == runtime / primary


def test_library_data_name_probe_skips_corrupt_marker_entries(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    root = tmp_path / "Assets"
    root.mkdir(parents=True)
    _force_digest_collision(monkeypatch)

    primary = path_resolver.library_data_name(root)
    shared = runtime / "Shared"
    (shared / f"{primary}.identity").mkdir(parents=True)  # corrupt: a directory

    # A corrupt marker is not treated as ownership; the primary slot is kept so
    # the database layer's formal-marker validation still surfaces corruption.
    assert path_resolver.library_data_name(root) == primary


def test_library_data_name_keeps_primary_for_matching_marker(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    root = tmp_path / "Assets"
    root.mkdir(parents=True)
    _force_digest_collision(monkeypatch)

    primary = path_resolver.library_data_name(root)
    shared = runtime / "Shared"
    shared.mkdir(parents=True)
    (shared / f"{primary}.identity").write_text(
        path_resolver.root_identity(root, strict=False).map_key, encoding="utf-8"
    )

    assert path_resolver.library_data_name(root) == primary


# ── Bug 14: empty roots get a deterministic independent slot ──────────────


def test_empty_root_gets_deterministic_independent_slot(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)

    slot = path_resolver.library_data_dir("")
    assert slot == path_resolver.library_data_dir(None)
    assert slot == path_resolver.library_data_dir("")
    assert slot.parent == runtime
    assert slot.name != "_temp"
    assert slot.name.startswith("_empty_")

    # Every data-path helper follows the same deterministic slot.
    assert path_resolver.db_path("") == slot / "assetmanager.db"
    assert path_resolver.thumb_dir("") == slot / ".thumbnails"
    assert path_resolver.favorites_path("") == slot / "favorites.json"
    assert path_resolver.legacy_library_data_dir("") == slot

    # The slot is independent of any real library's hashed slot.
    lib = tmp_path / "Somewhere" / "Assets"
    lib.mkdir(parents=True)
    assert path_resolver.library_data_dir(str(lib)) != slot
    assert path_resolver.library_data_dir(str(lib)).name != slot.name
