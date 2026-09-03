"""Tests for AppSettings singleton."""
import json

import pytest

import AssetsManager.core.settings as settings_module
from AssetsManager.core.config_migrator import (
    CURRENT_VERSION,
    FutureConfigVersionError,
    migrate,
)
from AssetsManager.core.settings import (
    SHARE_LAST_SUCCESSFUL_AUTH_KEY,
    SHARE_LAST_SUCCESSFUL_BIND_KEY,
    SHARE_SAFETY_ACK_VERSION_KEY,
    TRUSTED_NETWORK_CONFIRMED_KEY,
    AppSettings,
)


def test_singleton():
    a = AppSettings.instance()
    b = AppSettings.instance()
    assert a is b


def test_bg_effect_validator_accepts_kuwahara_and_shader():
    """Regression: the settings validator blocked saving the Kuwahara effect,
    so picking it in the dialog raised ValueError and the choice was lost."""
    settings_module._validate_setting("bg_effect", "kuwahara")
    settings_module._validate_setting("bg_effect", "mosaic")
    settings_module._validate_setting("bg_effect", "shader")
    with pytest.raises(ValueError):
        settings_module._validate_setting("bg_effect", "not-an-effect")


def test_bg_shader_preset_validator_requires_nonempty_string():
    settings_module._validate_setting("bg_shader_preset", "plasma")
    settings_module._validate_setting("bg_shader_preset", "grid-flow")
    with pytest.raises(ValueError):
        settings_module._validate_setting("bg_shader_preset", "")
    with pytest.raises(ValueError):
        settings_module._validate_setting("bg_shader_preset", None)


def test_future_config_version_rejected_without_mutating_payload():
    payload = {
        "_cfg_version": CURRENT_VERSION + 1,
        "future_setting": {"enabled": True},
    }
    original = dict(payload)

    with pytest.raises(FutureConfigVersionError) as exc_info:
        migrate(payload)

    assert exc_info.value.version == CURRENT_VERSION + 1
    assert payload == original


def test_future_settings_are_preserved_and_write_blocked(tmp_path, monkeypatch):
    import AssetsManager.core.library_manager as library_manager

    legacy_path = tmp_path / ".assetmanager" / "settings.json"
    legacy_path.parent.mkdir()
    legacy_path.write_text('{"legacy_only": true}', encoding="utf-8")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    path = tmp_path / "settings.json"
    original_bytes = b'{"_cfg_version": 3, "future_setting": {"x": 1}}\n'
    path.write_bytes(original_bytes)
    settings = _settings_at(path, data={"stale": "memory"}, dirty=True)
    settings.load()

    assert settings.is_write_blocked is True
    assert settings._future_config_version == CURRENT_VERSION + 1
    assert settings._data == {}
    assert settings._dirty is False
    assert path.read_bytes() == original_bytes
    assert settings.get("legacy_only") is None

    settings.set("ordinary", "value")
    settings.set_list("items", [1, 2])
    settings.prepend_list("items", 0)
    settings.remove_from_list("items", 1)
    settings.set_share_security_history(
        "127.0.0.1", {"enabled": True, "mode": "password"}
    )
    assert settings.commit_share_security_history(
        "127.0.0.1", {"enabled": True, "mode": "password"}
    ) is False
    assert settings.commit_share_safety_confirmation(3, True) is False
    assert settings.save() is False
    monkeypatch.setattr(settings, "save", lambda: pytest.fail("blocked atexit save"))
    settings._atexit_save()

    assert settings._data == {}
    assert settings._dirty is False
    assert path.read_bytes() == original_bytes

    monkeypatch.setattr(library_manager.AppSettings, "instance", lambda: settings)
    assert library_manager.record_visit(str(tmp_path / "library")) == ""
    library_manager.remove("missing")
    assert settings._data == {}
    assert path.read_bytes() == original_bytes


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
    legacy_path.write_text(
        json.dumps({
            "theme": "Navy",
            "recent_libraries": ["D:/old/library"],
            "legacy_only": True,
            "key1": "value1",
            "test_list": [1, 2, 3],
        }),
        encoding="utf-8",
    )
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
    assert reader.get("legacy_only") is None
    assert reader.get("key1") is None
    assert reader.get("test_list") is None


def test_legacy_migration_carries_only_allowlisted_keys(tmp_path, monkeypatch):
    """Regression: the legacy ~/.assetmanager migration used to copy every
    key into the fresh profile, so unit-test leftovers recorded in an old
    profile (key1/prepend_test/...) leaked into new installs — including the
    packaged portable app's first-launch settings.json."""
    legacy_path = tmp_path / ".assetmanager" / "settings.json"
    legacy_path.parent.mkdir()
    legacy_path.write_text(
        json.dumps({
            "theme": "Navy",
            "recent_libraries": ["D:/old/library"],
            "tab_state": {"tabs": ["D:/old/library"], "active": 0},
            "key1": "value1",
            "test": 123,
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    reader = AppSettings.__new__(AppSettings)
    reader._path = tmp_path / "settings.json"
    reader._data = {}
    reader._dirty = False
    reader.load()

    assert reader.get("theme") == "Navy"
    assert reader.get("recent_libraries") == ["D:/old/library"]
    assert reader.get("tab_state") is None
    assert reader.get("key1") is None
    assert reader.get("test") is None
    assert reader.get("_cfg_version") == CURRENT_VERSION
    saved = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert saved["_cfg_version"] == CURRENT_VERSION
    assert "key1" not in saved and "tab_state" not in saved


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


def _settings_at(path, *, data=None, dirty=False):
    settings = AppSettings.__new__(AppSettings)
    settings._path = path
    settings._data = {} if data is None else data
    settings._dirty = dirty
    return settings


def test_save_returns_true_and_clears_dirty_after_atomic_replace(tmp_path):
    settings = _settings_at(tmp_path / "settings.json", data={"theme": "Forest"}, dirty=True)

    assert settings.save() is True
    assert settings._dirty is False
    assert json.loads(settings.path.read_text(encoding="utf-8")) == {"theme": "Forest"}
    assert settings.save() is True


def test_save_returns_false_and_keeps_dirty_on_os_error(tmp_path, monkeypatch):
    settings = _settings_at(tmp_path / "settings.json", data={"theme": "Forest"}, dirty=True)

    def fail_replace(*args, **kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr(settings_module.os, "replace", fail_replace)

    assert settings.save() is False
    assert settings._dirty is True
    assert not settings.path.exists()


def test_share_security_history_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    writer = _settings_at(path)
    auth_status = {"enabled": True, "mode": "password"}

    writer.set_share_security_history("0.0.0.0", auth_status)
    assert writer.save() is True

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload[SHARE_LAST_SUCCESSFUL_BIND_KEY] == "0.0.0.0"
    assert payload[SHARE_LAST_SUCCESSFUL_AUTH_KEY] == auth_status
    assert "password" not in payload
    assert "access_key" not in payload

    reader = _settings_at(path, data={"_legacy_migrated": True})
    reader.load()
    assert reader.get_share_security_history() == ("0.0.0.0", auth_status)


@pytest.mark.parametrize(
    "data",
    [
        {},
        {SHARE_LAST_SUCCESSFUL_BIND_KEY: "0.0.0.0"},
        {SHARE_LAST_SUCCESSFUL_AUTH_KEY: {"enabled": True, "mode": "password"}},
        {SHARE_LAST_SUCCESSFUL_BIND_KEY: 123, SHARE_LAST_SUCCESSFUL_AUTH_KEY: {"enabled": True, "mode": "password"}},
        {SHARE_LAST_SUCCESSFUL_BIND_KEY: "0.0.0.0", SHARE_LAST_SUCCESSFUL_AUTH_KEY: {"enabled": 1, "mode": "password"}},
        {SHARE_LAST_SUCCESSFUL_BIND_KEY: "0.0.0.0", SHARE_LAST_SUCCESSFUL_AUTH_KEY: {"enabled": True, "mode": "password", "secret": "no"}},
    ],
)
def test_share_security_history_invalid_values_read_as_no_history(data):
    settings = _settings_at(None, data=data)

    assert settings.get_share_security_history() == (None, None)


@pytest.mark.parametrize(
    "bind, auth_status",
    [
        (None, {"enabled": True, "mode": "password"}),
        ("", {"enabled": True, "mode": "password"}),
        ("0.0.0.0", {"enabled": 1, "mode": "password"}),
        ("0.0.0.0", {"enabled": True}),
        ("0.0.0.0", {"enabled": True, "mode": "password", "secret": "no"}),
    ],
)
def test_share_security_history_invalid_values_raise_value_error(bind, auth_status):
    settings = _settings_at(None)

    with pytest.raises(ValueError):
        settings.set_share_security_history(bind, auth_status)

    assert settings._data == {}
    assert settings._dirty is False


def test_commit_share_security_history_rolls_back_memory_on_save_failure(monkeypatch):
    old_auth_status = {"enabled": False, "mode": "none"}
    settings = _settings_at(
        None,
        data={
            SHARE_LAST_SUCCESSFUL_BIND_KEY: "127.0.0.1",
            SHARE_LAST_SUCCESSFUL_AUTH_KEY: old_auth_status,
        },
        dirty=False,
    )
    monkeypatch.setattr(settings, "save", lambda: False)

    assert settings.commit_share_security_history("0.0.0.0", {"enabled": True, "mode": "password"}) is False
    assert settings._data == {
        SHARE_LAST_SUCCESSFUL_BIND_KEY: "127.0.0.1",
        SHARE_LAST_SUCCESSFUL_AUTH_KEY: old_auth_status,
    }
    assert settings._dirty is False
    assert settings.get_share_security_history() == ("127.0.0.1", old_auth_status)


def test_commit_share_security_history_restores_absent_keys_and_dirty_on_failure(monkeypatch):
    settings = _settings_at(None, data={"other": "value"}, dirty=True)
    monkeypatch.setattr(settings, "save", lambda: False)

    assert settings.commit_share_security_history("0.0.0.0", {"enabled": True, "mode": "password"}) is False
    assert settings._data == {"other": "value"}
    assert settings._dirty is True
    assert settings.get_share_security_history() == (None, None)


def test_commit_share_security_history_returns_true_after_save(tmp_path):
    settings = _settings_at(tmp_path / "settings.json")

    assert settings.commit_share_security_history("0.0.0.0", {"enabled": True, "mode": "password"}) is True
    assert settings._dirty is False
    assert settings.get_share_security_history() == (
        "0.0.0.0",
        {"enabled": True, "mode": "password"},
    )


def test_commit_share_security_history_rolls_back_on_save_exception(monkeypatch):
    settings = _settings_at(
        None,
        data={
            SHARE_LAST_SUCCESSFUL_BIND_KEY: "127.0.0.1",
            SHARE_LAST_SUCCESSFUL_AUTH_KEY: {"enabled": False, "mode": "none"},
        },
        dirty=False,
    )

    def fail_save():
        raise RuntimeError("serialization failed")

    monkeypatch.setattr(settings, "save", fail_save)

    assert settings.commit_share_security_history(
        "0.0.0.0", {"enabled": True, "mode": "password"}
    ) is False
    assert settings.get_share_security_history() == (
        "127.0.0.1",
        {"enabled": False, "mode": "none"},
    )
    assert settings._dirty is False


def test_commit_share_safety_confirmation_returns_true_after_save(tmp_path):
    settings = _settings_at(tmp_path / "settings.json")

    assert settings.commit_share_safety_confirmation(3, True) is True
    assert settings.get_share_safety_ack_version() == 3
    assert settings.get_trusted_network_confirmed() is True
    assert settings._dirty is False


def test_commit_share_safety_confirmation_rolls_back_on_save_false(monkeypatch):
    settings = _settings_at(
        None,
        data={
            SHARE_SAFETY_ACK_VERSION_KEY: 2,
            TRUSTED_NETWORK_CONFIRMED_KEY: False,
        },
        dirty=False,
    )
    monkeypatch.setattr(settings, "save", lambda: False)

    assert settings.commit_share_safety_confirmation(3, True) is False
    assert settings.get_share_safety_ack_version() == 2
    assert settings.get_trusted_network_confirmed() is False
    assert settings._dirty is False


def test_commit_share_safety_confirmation_rolls_back_on_save_exception(monkeypatch):
    settings = _settings_at(None, data={"other": "value"}, dirty=True)

    def fail_save():
        raise RuntimeError("save failed")

    monkeypatch.setattr(settings, "save", fail_save)

    assert settings.commit_share_safety_confirmation(3, True) is False
    assert SHARE_SAFETY_ACK_VERSION_KEY not in settings._data
    assert TRUSTED_NETWORK_CONFIRMED_KEY not in settings._data
    assert settings._data == {"other": "value"}
    assert settings._dirty is True
