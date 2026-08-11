"""Low-batch unit tests for AppSettings atomicity and lifecycle.

Covers three defects:

* Bug 3: ``prepend_list`` / ``remove_from_list`` performed a read-modify-write
  across two separate lock acquisitions (``get_list`` then ``set_list``), so
  concurrent callers could interleave and lose updates.  The read-modify-write
  must now happen under a single lock acquisition, without calling
  ``get_list``/``set_list``.
* Bug 4: directly constructed ``AppSettings`` instances re-registered the
  atexit flush handler, so two instances could both save at interpreter exit
  (the second overwriting the first's snapshot).  Registration must happen at
  most once per process and never for a duplicate of an existing singleton.
* Bug 5: a config migration applied during ``load()`` was never persisted
  because ``_dirty`` was not set; the upgraded schema must be written back.
"""
import json
import threading

import AssetsManager.core.settings as settings_module
from AssetsManager.core.config_migrator import CURRENT_VERSION
from AssetsManager.core.settings import AppSettings
from AssetsManager.core.singleton import ThreadSafeSingleton


def _settings_at(path, *, data=None, dirty=False):
    settings = AppSettings.__new__(AppSettings)
    settings._path = path
    settings._data = {} if data is None else data
    settings._dirty = dirty
    # Production instances always carry their lock from ``__init__``; pre-set
    # it here so ``_get_lock`` cannot race on lazy creation in concurrency
    # tests.
    settings._lock = threading.RLock()
    return settings


# ── Bug 3: atomic prepend_list / remove_from_list ─────────────────

def test_prepend_list_moves_existing_value_to_front():
    s = _settings_at(None, data={"k": ["b", "c"]})
    s.prepend_list("k", "a")
    assert s.get_list("k") == ["a", "b", "c"]
    s.prepend_list("k", "b")
    assert s.get_list("k") == ["b", "a", "c"]
    assert s._dirty is True


def test_prepend_list_creates_missing_list_and_truncates():
    s = _settings_at(None, data={})
    s.prepend_list("k", "x", max_items=2)
    assert s.get_list("k") == ["x"]
    s.prepend_list("k", "y", max_items=2)
    s.prepend_list("k", "z", max_items=2)
    assert s.get_list("k") == ["z", "y"]


def test_prepend_list_no_max_items_keeps_everything():
    s = _settings_at(None, data={"k": ["a"]})
    s.prepend_list("k", "b", max_items=None)
    assert s.get_list("k") == ["b", "a"]


def test_remove_from_list_touches_dirty_only_when_removing():
    s = _settings_at(None, data={"k": ["a", "b"]})
    s.remove_from_list("k", "b")
    assert s.get_list("k") == ["a"]
    assert s._dirty is True
    s._dirty = False
    s.remove_from_list("k", "missing")
    assert s.get_list("k") == ["a"]
    assert s._dirty is False


def test_remove_from_list_ignores_non_list_values():
    s = _settings_at(None, data={"k": "not-a-list"})
    s.remove_from_list("k", "a")
    assert s._data["k"] == "not-a-list"
    assert s._dirty is False


def _forbidden(message):
    def boom(*args, **kwargs):
        raise AssertionError(message)

    return boom


def test_prepend_list_is_single_lock_read_modify_write(monkeypatch):
    """prepend_list must not delegate to get_list/set_list (separate locks)."""
    s = _settings_at(None, data={"k": ["b"]})
    monkeypatch.setattr(s, "get_list", _forbidden("prepend_list must not call get_list"))
    monkeypatch.setattr(s, "set_list", _forbidden("prepend_list must not call set_list"))
    acquisitions = []
    orig_lock = s._get_lock
    monkeypatch.setattr(s, "_get_lock", lambda: (acquisitions.append(1), orig_lock())[1])

    s.prepend_list("k", "a")

    assert acquisitions == [1]  # exactly one lock acquisition
    assert s._data["k"] == ["a", "b"]


def test_remove_from_list_is_single_lock_read_modify_write(monkeypatch):
    """remove_from_list must not delegate to get_list/set_list (separate locks)."""
    s = _settings_at(None, data={"k": ["a", "b"]})
    monkeypatch.setattr(s, "get_list", _forbidden("remove_from_list must not call get_list"))
    monkeypatch.setattr(s, "set_list", _forbidden("remove_from_list must not call set_list"))
    acquisitions = []
    orig_lock = s._get_lock
    monkeypatch.setattr(s, "_get_lock", lambda: (acquisitions.append(1), orig_lock())[1])

    s.remove_from_list("k", "b")

    assert acquisitions == [1]  # exactly one lock acquisition
    assert s._data["k"] == ["a"]


def test_concurrent_prepend_list_does_not_lose_updates():
    """Short concurrency run: every prepended value must survive."""
    s = _settings_at(None, data={})
    n_threads, per_thread = 4, 25
    barrier = threading.Barrier(n_threads)

    def worker(tid):
        barrier.wait()
        for i in range(per_thread):
            # max_items=None so the default 50-item cap cannot mask
            # interleaved lost updates.
            s.prepend_list("k", f"{tid}-{i}", max_items=None)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    items = s.get_list("k")
    assert len(items) == n_threads * per_thread
    assert len(set(items)) == len(items)


# ── Bug 4: atexit flush registered at most once ────────────────────

class _FakeAtexit:
    def __init__(self):
        self.registered = []

    def register(self, func):
        self.registered.append(func)


def _reset_atexit_state():
    ThreadSafeSingleton.reset(AppSettings)
    AppSettings._atexit_registered = False


def test_atexit_flush_registered_once_for_singleton_and_duplicates(monkeypatch):
    """Directly constructed duplicates of the singleton must not register."""
    fake_atexit = _FakeAtexit()
    monkeypatch.setattr(settings_module, "atexit", fake_atexit)
    _reset_atexit_state()
    try:
        singleton = AppSettings.instance()
        AppSettings()  # direct construction ...
        AppSettings()  # ... must not add further handlers
        assert len(fake_atexit.registered) == 1
        assert fake_atexit.registered[0].__self__ is singleton
    finally:
        _reset_atexit_state()


def test_atexit_flush_registered_once_for_direct_constructions(monkeypatch):
    """Even without a singleton, multiple direct constructions register once."""
    fake_atexit = _FakeAtexit()
    monkeypatch.setattr(settings_module, "atexit", fake_atexit)
    _reset_atexit_state()
    try:
        first = AppSettings()
        second = AppSettings()
        assert second is not first
        assert len(fake_atexit.registered) == 1
        assert fake_atexit.registered[0].__self__ is first
    finally:
        _reset_atexit_state()


def test_no_dead_class_attribute_instance():
    assert not hasattr(AppSettings, "_instance")


# ── Bug 5: migration applied in load() is persisted ────────────────

def test_load_marks_dirty_when_config_migration_applies(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"_legacy_migrated": True}), encoding="utf-8")
    s = _settings_at(path)
    s.load()

    assert s._dirty is True
    assert s.get("_cfg_version") == CURRENT_VERSION
    assert s.get("search_history") == []


def test_load_does_not_mark_dirty_when_config_is_current(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {"_cfg_version": CURRENT_VERSION, "_legacy_migrated": True, "search_history": []}
        ),
        encoding="utf-8",
    )
    s = _settings_at(path)
    s.load()

    assert s._dirty is False
    assert s.get("_cfg_version") == CURRENT_VERSION


def test_load_migration_result_is_persisted_on_save(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"_legacy_migrated": True}), encoding="utf-8")
    s = _settings_at(path)
    s.load()
    assert s._dirty is True

    assert s.save() is True
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["_cfg_version"] == CURRENT_VERSION
    assert payload["search_history"] == []
    assert payload["_legacy_migrated"] is True
