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


def test_save_load(tmp_path):
    original_path = AppSettings.instance()._path
    AppSettings.instance()._path = tmp_path / "settings.json"
    try:
        s = AppSettings.instance()
        s.set("theme", "Forest")
        s.save()
        s2 = AppSettings.__new__(AppSettings)
        s2._path = tmp_path / "settings.json"
        s2._data = {}
        s2._dirty = False
        s2.load()
        assert s2.get("theme") == "Forest"
    finally:
        AppSettings.instance()._path = original_path
