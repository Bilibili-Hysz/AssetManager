"""Tests for AppSettings singleton."""
from AssetsManager.core.settings import AppSettings


def test_singleton():
    a = AppSettings.instance()
    b = AppSettings.instance()
    assert a is b


def test_set_get():
    s = AppSettings.instance()
    s.set("key1", "value1")
    assert s.get("key1") == "value1"
    assert s.get("nonexistent") is None
    assert s.get("nonexistent", "default") == "default"


def test_list_operations():
    s = AppSettings.instance()
    s.set_list("test_list", [1, 2, 3])
    assert s.get_list("test_list") == [1, 2, 3]
    s.set_list("test_list", [1, 2, 3, 4, 5], max_items=3)
    assert s.get_list("test_list") == [1, 2, 3]


def test_prepend_list():
    s = AppSettings.instance()
    s.set_list("prepend_test", ["b", "c"])
    s.prepend_list("prepend_test", "a", max_items=3)
    assert s.get_list("prepend_test") == ["a", "b", "c"]
    s.prepend_list("prepend_test", "a")
    assert s.get_list("prepend_test") == ["a", "b", "c"]


def test_remove_from_list():
    s = AppSettings.instance()
    s.set_list("remove_test", ["a", "b", "c"])
    s.remove_from_list("remove_test", "b")
    assert s.get_list("remove_test") == ["a", "c"]


def test_save_load_prefers_current_settings_over_legacy_file(tmp_path, monkeypatch):
    legacy_path = tmp_path / ".assetmanager" / "settings.json"
    legacy_path.parent.mkdir()
    legacy_path.write_text('{"theme": "Navy", "legacy_only": true}', encoding="utf-8")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    writer = AppSettings.__new__(AppSettings)
    writer._path = tmp_path / "settings.json"
    writer._data = {"theme": "Forest"}
    writer._dirty = True
    writer.save()
    reader = AppSettings.__new__(AppSettings)
    reader._path = tmp_path / "settings.json"
    reader._data = {}
    reader._dirty = False
    reader.load()

    assert reader.get("theme") == "Forest"
    assert reader.get("legacy_only") is True


def test_malformed_legacy_settings_marks_migration_complete(tmp_path, monkeypatch):
    legacy_path = tmp_path / ".assetmanager" / "settings.json"
    legacy_path.parent.mkdir()
    legacy_path.write_text("not json", encoding="utf-8")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    first = AppSettings.__new__(AppSettings)
    first._path = tmp_path / "settings.json"
    first._data = {}
    first._dirty = False
    first.load()

    assert first.get("_legacy_migrated") is True

    legacy_path.unlink()
    second = AppSettings.__new__(AppSettings)
    second._path = tmp_path / "settings.json"
    second._data = {}
    second._dirty = False
    second.load()

    assert second.get("_legacy_migrated") is True
