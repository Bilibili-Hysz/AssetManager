"""Low-batch fixes: core services and controller defect regression tests.

Covers the H+I fix batch:
  - themes: stylesheet cache keyed by ui_scale; _merge_theme type safety
  - crash_handler: hook reentrancy guard
  - tool_scheduler: Windows .cmd/.bat launching; atomic save
  - json_store: _save/_ensure_loaded failure containment
  - sidebar_favorites: no cross-library fallback copy on library switch
  - tag_tree_controller: single batch query; TagLibrary sync on rename
  - directory_cache: stale-row pruning
  - settings: non-dict settings file quarantined
"""
import json
import os
import sqlite3
import time
from pathlib import Path

import pytest

from AssetsManager.core.json_store import JsonStore

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# ── themes (A1/A2) ──────────────────────────────────────────────


def test_stylesheet_cache_key_includes_ui_scale(monkeypatch):
    """Scaling the UI must regenerate the QSS (cache key must include scale)."""
    from AssetsManager.core import themes
    from AssetsManager.core import ui_scale

    if not themes._THEMES:
        pytest.skip("no themes loaded in this environment")
    themes.invalidate_cache()
    try:
        monkeypatch.setattr(ui_scale, "get_ui_scale", lambda: 1.0)
        s1 = themes.stylesheet()
        monkeypatch.setattr(ui_scale, "get_ui_scale", lambda: 2.0)
        s2 = themes.stylesheet()
        assert s1 != s2, "stylesheet cache must be invalidated on ui_scale change"
        # Same scale again hits the cache.
        s3 = themes.stylesheet()
        assert s3 == s2
    finally:
        themes.invalidate_cache()


def test_merge_theme_discards_malformed_input():
    """Illegal colors / non-dict properties must never crash the merge."""
    from AssetsManager.core import themes

    # Exact shape from the bug report: missing required tokens, bad color,
    # non-dict properties → discarded, no exception.
    assert themes._merge_theme({"colors": {"a": "red"}, "properties": []}) is None


def test_merge_theme_discards_invalid_color_with_all_required_tokens():
    from AssetsManager.core import themes

    colors = {t: "#123456" for t in themes._REQUIRED_TOKENS}
    colors["accent"] = "red"  # not a hex color
    assert themes._merge_theme({"name": "Bad", "colors": colors}) is None


def test_merge_theme_sanitizes_non_dict_properties():
    from AssetsManager.core import themes

    colors = {t: "#ffffff" for t in themes._REQUIRED_TOKENS}
    merged = themes._merge_theme(
        {"name": "OK", "colors": colors, "properties": []}
    )
    assert merged is not None
    assert merged["properties"] == {}


def test_merge_theme_discards_non_dict_colors():
    from AssetsManager.core import themes

    assert themes._merge_theme({"name": "X", "colors": ["#000000"]}) is None


# ── crash_handler (B1) ──────────────────────────────────────────


def test_excepthook_recovers_from_hook_internal_failure(monkeypatch):
    """An exception inside the hook must be swallowed, not re-raised."""
    from AssetsManager.core import crash_handler

    def _boom():
        raise RuntimeError("rotate failed")

    monkeypatch.setattr(crash_handler, "_rotate_log", _boom)
    monkeypatch.setattr(crash_handler, "_original_hook", None)
    crash_handler._in_hook = False
    # Must not raise despite _rotate_log failing.
    crash_handler._excepthook(ValueError, ValueError("x"), None)
    assert crash_handler._in_hook is False, "reentrancy flag must reset"


def test_excepthook_reentrancy_flag_short_circuits(monkeypatch):
    """A nested invocation while the hook is active must return immediately."""
    from AssetsManager.core import crash_handler

    calls = []
    monkeypatch.setattr(crash_handler, "_rotate_log", lambda: calls.append(1))
    monkeypatch.setattr(crash_handler, "_original_hook", None)
    crash_handler._in_hook = True
    try:
        crash_handler._excepthook(ValueError, ValueError("x"), None)
    finally:
        crash_handler._in_hook = False
    assert calls == [], "hook body must not run while reentrant"


# ── tool_scheduler (C1) ─────────────────────────────────────────


def test_windows_launch_command_wraps_batch_files():
    from AssetsManager.core.tool_scheduler import _windows_launch_command

    assert _windows_launch_command(["build.cmd", "x"]) == ["cmd", "/c", "build.cmd", "x"]
    assert _windows_launch_command(["run.bat"]) == ["cmd", "/c", "run.bat"]
    assert _windows_launch_command(["C:\\Tools\\deploy.CMD", "--flag"]) == [
        "cmd", "/c", "C:\\Tools\\deploy.CMD", "--flag",
    ]
    assert _windows_launch_command(["blender.exe", "--version"]) == ["blender.exe", "--version"]
    assert _windows_launch_command(["code"]) == ["code"]
    assert _windows_launch_command([]) == []


# ── json_store (F1) ─────────────────────────────────────────────


class _Store(JsonStore):
    def _default_data(self):
        return {}


class _BrokenOnLoaded(JsonStore):
    def __init__(self, path):
        super().__init__(path)
        self.items = None

    def _default_data(self):
        return {"default": True}

    def _on_loaded(self, data):
        if data != {"default": True}:
            raise RuntimeError("bad payload")
        self.items = data


def test_save_swallows_unserializable_data(tmp_path):
    store = _Store(tmp_path / "x.json")
    store._save({"bad": {1, 2}})  # set is not JSON-serializable
    assert not store._path.exists()


def test_save_creates_parent_dirs_and_writes_atomically(tmp_path):
    store = _Store(tmp_path / "a" / "b" / "x.json")
    store._save({"ok": 1})
    assert store._path.exists()
    assert json.loads(store._path.read_text(encoding="utf-8")) == {"ok": 1}


def test_save_swallows_mkdir_failure(tmp_path, monkeypatch):
    store = _Store(tmp_path / "sub" / "x.json")

    def _boom(*args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "mkdir", _boom)
    store._save({"ok": 1})  # must not raise
    assert not store._path.exists()


def test_ensure_loaded_survives_broken_on_loaded(tmp_path):
    path = tmp_path / "x.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    store = _BrokenOnLoaded(path)
    store._ensure_loaded()  # must not raise
    assert store.items == {"default": True}


# ── sidebar_favorites (I1) ──────────────────────────────────────


def test_set_library_root_does_not_migrate_old_library_favorites(tmp_path):
    from AssetsManager.dialogs.sidebar_favorites import SidebarFavorites

    data1 = tmp_path / "data1"
    data2 = tmp_path / "data2"
    fav = SidebarFavorites()
    fav.set_library_root(str(tmp_path / "root1"), data1)
    target = tmp_path / "root1" / "work"
    target.mkdir(parents=True)
    fav.add(str(target), "Work")
    assert len(fav.list_all()) == 1

    # Switch to a second library with no favorites of its own.
    fav.set_library_root(str(tmp_path / "root2"), data2)
    assert fav.list_all() == [], "old library favorites leaked into new library"

    new_file = data2 / "favorites.json"
    if new_file.exists():
        assert json.loads(new_file.read_text(encoding="utf-8")) == []


# ── tag_tree_controller (K1/K2) ─────────────────────────────────


def test_get_tag_with_files_uses_single_batch_query():
    from AssetsManager.controllers.tag_tree_controller import TagTreeController

    class _FakeRepo:
        def __init__(self):
            self.list_file_tags_calls = 0

        def list_file_tags(self, source="human"):
            self.list_file_tags_calls += 1
            return [
                ("/lib/a.txt", "hero"),
                ("/lib/b.txt", "hero"),
                ("/lib/b.txt", "villain"),
            ]

    class _FakeTagSvc:
        def __init__(self):
            self.repo = _FakeRepo()

        def _repo(self, db_conn, library_root):
            return self.repo

        def get_all_tags(self, library_root, source="human"):
            return ["hero", "villain"]

        def get_tags_with_metadata(self, library_root):
            return [{"name": "hero", "icon": "star"}, {"name": "villain", "icon": ""}]

        def get_files_by_tag(self, library_root, tag):
            raise AssertionError("per-tag query must not be used when batch exists")

    ctrl = TagTreeController("/lib", tag_svc=_FakeTagSvc())
    result = ctrl.get_tag_with_files()
    # Three-source aggregation (v36): one batched call per source
    # (human/ai/plugin), never per-tag or per-file queries.
    assert ctrl._tag_svc.repo.list_file_tags_calls == 3
    by_tag = {entry["tag"]: entry["files"] for entry in result}
    assert by_tag == {"hero": ["/lib/a.txt", "/lib/b.txt"], "villain": ["/lib/b.txt"]}


def test_rename_tag_syncs_tag_library():
    from AssetsManager.controllers.tag_tree_controller import TagTreeController
    from AssetsManager.core.tag_library import get_library

    library = get_library()
    library.register_tag("old_hero")

    class _FakeTagSvc:
        def __init__(self):
            self.renamed = []

        def rename_tag(self, library_root, old_name, new_name):
            self.renamed.append((old_name, new_name))

    ctrl = TagTreeController("/lib", tag_svc=_FakeTagSvc())
    ctrl.rename_tag("old_hero", "new_hero")
    assert ctrl._tag_svc.renamed == [("old_hero", "new_hero")]
    canonicals = [c.lower() for c in library.all_canonicals()]
    assert "new_hero" in canonicals
    assert "old_hero" not in canonicals


# ── directory_cache (D2) ────────────────────────────────────────


def test_directory_cache_prunes_stale_rows(monkeypatch):
    from AssetsManager.core import directory_cache
    from AssetsManager.core.directory_cache import DirectoryCache

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.execute(
        "CREATE TABLE directory_cache (dir_path TEXT PRIMARY KEY, item_count INTEGER, "
        "preview_path TEXT, mtime REAL, scanned_at REAL)"
    )
    now = time.time()
    conn.execute(
        "INSERT INTO directory_cache VALUES (?,?,?,?,?)",
        ("/old", 1, None, now, now - 31 * 86400),
    )
    conn.execute(
        "INSERT INTO directory_cache VALUES (?,?,?,?,?)",
        ("/fresh", 2, None, now, now),
    )
    conn.commit()
    cache = DirectoryCache(conn)  # library_root=None → raw-connection mode
    # Force the 1% probabilistic prune to fire.
    monkeypatch.setattr(directory_cache.random, "random", lambda: 0.0)
    cache._maybe_prune()
    rows = conn.execute("SELECT dir_path FROM directory_cache").fetchall()
    assert [r[0] for r in rows] == ["/fresh"]
    conn.close()


# ── settings (E2) ───────────────────────────────────────────────


def test_settings_load_quarantines_non_dict_json(tmp_path):
    from AssetsManager.core.settings import AppSettings

    settings = AppSettings()  # plain instance; the singleton is untouched
    path = tmp_path / "settings.json"
    path.write_text('["not", "a", "dict"]', encoding="utf-8")
    settings._path = path
    settings.load()
    assert settings._data.get("_legacy_migrated") is True
    assert (tmp_path / "settings.json.corrupt").exists()
    assert not path.exists()
