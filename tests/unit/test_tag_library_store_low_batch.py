"""Low-batch tests for tag_library.py / tag_store.py defect fixes.

Covers:
- Bug 15: add_synonym rejects aliases that already map to a different
  canonical tag instead of silently overwriting _reverse.
- Bug 17: _save persists (flush + fsync) and a library file missing the
  'synonyms' key falls back to defaults (with a warning) instead of
  silently loading an empty library.
- Bug 19: TagStore.get_files_by_tag canonicalizes the query tag the same
  way add_tag does, so aliases resolve to the stored canonical name.
"""
import json
import logging

import pytest

from AssetsManager.core.tag_library import TagLibrary


@pytest.fixture
def tag_library(tmp_path):
    """Create a TagLibrary instance with a temporary file."""
    lib = TagLibrary()
    lib._path = tmp_path / "tag_library.json"
    lib._loaded = False
    lib._synonyms = {}
    lib._reverse = {}
    return lib


class TestAddSynonymConflicts:
    """Bug 15: add_synonym must reject, not silently overwrite."""

    def test_rejects_alias_already_mapped_to_another_canonical(self, tag_library):
        tag_library._synonyms = {"Texture": ["贴图"], "Model": []}
        tag_library._build_reverse()
        tag_library._loaded = True

        # 贴图 already belongs to Texture; Model must not steal it.
        assert tag_library.add_synonym("Model", "贴图") is False
        assert tag_library.canonical("贴图") == "Texture"
        assert "贴图" not in tag_library._synonyms["Model"]
        assert tag_library._reverse["贴图"] == "Texture"

    def test_rejects_case_variant_of_another_canonical(self, tag_library):
        tag_library._synonyms = {"Texture": [], "Model": []}
        tag_library._build_reverse()
        tag_library._loaded = True

        # "model" is the canonical name Model (case-insensitive).
        assert tag_library.add_synonym("Texture", "model") is False
        assert tag_library.canonical("model") == "Model"

    def test_rejects_own_canonical_name_as_alias(self, tag_library):
        tag_library._synonyms = {"Texture": ["贴图"]}
        tag_library._build_reverse()
        tag_library._loaded = True

        assert tag_library.add_synonym("Texture", "texture") is False
        assert tag_library.synonyms_of("Texture") == ["贴图"]

    def test_returns_true_when_registered(self, tag_library):
        tag_library._synonyms = {"Texture": ["贴图"]}
        tag_library._build_reverse()
        tag_library._loaded = True

        assert tag_library.add_synonym("Texture", "テクスチャ") is True
        assert tag_library.canonical("テクスチャ") == "Texture"

    def test_duplicate_alias_returns_false_without_duplication(self, tag_library):
        tag_library._synonyms = {"Texture": ["贴图"]}
        tag_library._build_reverse()
        tag_library._loaded = True

        assert tag_library.add_synonym("Texture", "贴图") is False
        assert tag_library.synonyms_of("Texture").count("贴图") == 1

    def test_rejected_conflict_does_not_rewrite_file(self, tag_library):
        tag_library._synonyms = {"Texture": ["贴图"], "Model": []}
        tag_library._build_reverse()
        tag_library._loaded = True
        tag_library._save()
        before = tag_library._path.read_text(encoding="utf-8")

        assert tag_library.add_synonym("Model", "贴图") is False
        assert tag_library._path.read_text(encoding="utf-8") == before


class TestSavePersistence:
    """Bug 17a: _save writes the file durably and readably."""

    def test_save_writes_file_readable_by_fresh_instance(self, tag_library, tmp_path):
        tag_library._synonyms = {"Custom": ["别名"]}
        tag_library._build_reverse()
        tag_library._save()

        assert tag_library._path.exists()
        data = json.loads(tag_library._path.read_text(encoding="utf-8"))
        assert data["synonyms"] == {"Custom": ["别名"]}

        fresh = TagLibrary()
        fresh._path = tmp_path / "tag_library.json"
        fresh._ensure_loaded()
        assert fresh.canonical("别名") == "Custom"

    def test_save_after_add_synonym_round_trips(self, tag_library, tmp_path):
        tag_library._synonyms = {"Texture": ["贴图"]}
        tag_library._build_reverse()
        tag_library._loaded = True
        tag_library.add_synonym("Texture", "テクスチャ")

        fresh = TagLibrary()
        fresh._path = tmp_path / "tag_library.json"
        fresh._ensure_loaded()
        assert fresh.canonical("テクスチャ") == "Texture"


class TestLoadTolerance:
    """Bug 17b: missing/invalid 'synonyms' key must not silently empty the library."""

    def test_missing_synonyms_key_falls_back_to_defaults(self, tag_library):
        tag_library._path.write_text(json.dumps({"version": 1}), encoding="utf-8")

        tag_library._ensure_loaded()

        assert tag_library._loaded is True
        assert "Texture" in tag_library._synonyms
        assert tag_library.canonical("贴图") == "Texture"
        # The damaged file is repaired with a valid synonyms object.
        data = json.loads(tag_library._path.read_text(encoding="utf-8"))
        assert isinstance(data.get("synonyms"), dict)
        assert "Texture" in data["synonyms"]

    def test_non_dict_synonyms_key_falls_back_to_defaults(self, tag_library):
        tag_library._path.write_text(json.dumps({"synonyms": ["oops"]}), encoding="utf-8")

        tag_library._ensure_loaded()

        assert "Texture" in tag_library._synonyms
        assert tag_library.canonical("贴图") == "Texture"

    def test_missing_synonyms_key_logs_warning(self, tag_library, caplog):
        tag_library._path.write_text(json.dumps({"version": 1}), encoding="utf-8")

        with caplog.at_level(logging.WARNING, logger="AssetsManager.core.tag_library"):
            tag_library._ensure_loaded()

        assert any("synonyms" in r.message for r in caplog.records)

    def test_explicit_empty_synonyms_stays_empty(self, tag_library):
        # An empty but well-formed library is valid, not damaged.
        tag_library._path.write_text(json.dumps({"synonyms": {}}), encoding="utf-8")

        tag_library._ensure_loaded()

        assert tag_library._synonyms == {}
        assert tag_library._path.read_text(encoding="utf-8") == json.dumps({"synonyms": {}})


class TestTagStoreGetFilesByTagCanonical:
    """Bug 19: TagStore.get_files_by_tag canonicalizes like add_tag."""

    def test_alias_query_returns_files_of_canonical_tag(self, tmp_path, monkeypatch):
        import sqlite3

        import AssetsManager.core.tag_store as tag_store_mod
        from AssetsManager.core import database
        from AssetsManager.core.tag_store import TagStore

        # Controlled, isolated TagLibrary (avoids touching the process-global
        # singleton and the real shared tag_library.json).
        lib = TagLibrary()
        lib._path = tmp_path / "tag_library.json"
        lib._synonyms = {"Heroic": ["hero", "英雄"]}
        lib._build_reverse()
        lib._loaded = True
        monkeypatch.setattr(tag_store_mod, "get_library", lambda: lib)

        root = tmp_path / "lib"
        root.mkdir()
        file_path = str((root / "a.png").resolve())
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            store = TagStore(str(root), db_conn=conn)
            store.add_tag(file_path, "hero")

            # add_tag stores the canonical name.
            assert store.get_tags(file_path) == ["Heroic"]

            # Alias and canonical queries both resolve to the stored key.
            assert store.get_files_by_tag("hero") == {file_path}
            assert store.get_files_by_tag("英雄") == {file_path}
            assert store.get_files_by_tag("Heroic") == {file_path}
            assert store.get_files_by_tag("unmatched") == set()
        finally:
            conn.close()

    def test_unknown_tag_query_passes_through(self, tmp_path, monkeypatch):
        import sqlite3

        import AssetsManager.core.tag_store as tag_store_mod
        from AssetsManager.core import database
        from AssetsManager.core.tag_store import TagStore

        lib = TagLibrary()
        lib._path = tmp_path / "tag_library.json"
        lib._synonyms = {}
        lib._build_reverse()
        lib._loaded = True
        monkeypatch.setattr(tag_store_mod, "get_library", lambda: lib)

        root = tmp_path / "lib2"
        root.mkdir()
        file_path = str((root / "b.png").resolve())
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            conn.executescript(database._SCHEMA)
            store = TagStore(str(root), db_conn=conn)
            store.add_tag(file_path, "unique_tag")
            assert store.get_files_by_tag("unique_tag") == {file_path}
            # Unknown tags keep the caller's exact spelling (same as add_tag).
            assert store.get_files_by_tag("UNIQUE_TAG") == set()
        finally:
            conn.close()
