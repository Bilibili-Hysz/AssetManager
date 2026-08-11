"""Regression tests for json_store corruption quarantine and cache fixes.

Covers:
- Bug 7: JsonStore quarantines a corrupt JSON file instead of retrying it
  forever, and never overwrites the original corrupt bytes.
- Bug 9: LRUCache/TTLCache reject max_size < 1 at construction.
- Bug 10: DictCache is thread-safe (locked like LRUCache/TTLCache).
"""
import threading

import pytest

from AssetsManager.core.cache import DictCache, LRUCache, TTLCache
from AssetsManager.core.json_store import JsonStore


class _Store(JsonStore):
    def _default_data(self):
        return {}

    def _on_loaded(self, data):
        self.items = data


class _BrokenOnLoaded(JsonStore):
    """Rejects any payload that is not the default (subclass bug, not corruption)."""

    def __init__(self, path):
        super().__init__(path)
        self.items = None

    def _default_data(self):
        return {"default": True}

    def _on_loaded(self, data):
        if data != {"default": True}:
            raise RuntimeError("bad payload")
        self.items = data


def _corrupt_backups(path):
    return sorted(p for p in path.parent.iterdir() if "corrupt" in p.name)


# ── Bug 7: corrupt file quarantine ──────────────────────────────


def test_corrupt_file_is_quarantined_and_defaults_returned(tmp_path):
    path = tmp_path / "x.json"
    path.write_text('{"a": broken', encoding="utf-8")
    store = _Store(path)
    store._ensure_loaded()  # must not raise

    # Original file moved aside as a backup, defaults returned in memory.
    assert not path.exists()
    backups = _corrupt_backups(path)
    assert len(backups) == 1, backups
    assert backups[0].name.startswith("x.json.corrupt")
    assert "broken" in backups[0].read_text(encoding="utf-8")
    assert store.items == {}
    assert store._loaded


def test_reconstructing_store_after_quarantine_does_not_raise(tmp_path):
    path = tmp_path / "x.json"
    path.write_text("{not json", encoding="utf-8")
    _Store(path)._ensure_loaded()

    # A fresh store on the same path sees no file: clean default load,
    # no further quarantine attempts.
    store2 = _Store(path)
    store2._ensure_loaded()
    assert store2.items == {}
    assert store2._loaded
    assert len(_corrupt_backups(path)) == 1


def test_second_quarantine_gets_timestamped_name(tmp_path):
    path = tmp_path / "x.json"
    path.write_text("corrupt-1", encoding="utf-8")
    _Store(path)._ensure_loaded()
    path.write_text("corrupt-2", encoding="utf-8")
    _Store(path)._ensure_loaded()

    backups = _corrupt_backups(path)
    assert len(backups) == 2, backups
    # The second backup must not have overwritten the first.
    assert backups[0].read_text(encoding="utf-8") == "corrupt-1"
    assert backups[1].read_text(encoding="utf-8") == "corrupt-2"


def test_valid_file_rejected_by_subclass_hook_is_not_quarantined(tmp_path):
    path = tmp_path / "x.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    store = _BrokenOnLoaded(path)
    store._ensure_loaded()

    # Data is fine; the hook bug falls back to defaults but the file stays put.
    assert store.items == {"default": True}
    assert path.exists()
    assert _corrupt_backups(path) == []


# ── Bug 9: max_size validation ──────────────────────────────────


@pytest.mark.parametrize("cls", [LRUCache, TTLCache])
@pytest.mark.parametrize("max_size", [0, -1, -100])
def test_max_size_zero_or_negative_raises(cls, max_size):
    with pytest.raises(ValueError):
        cls(max_size=max_size)


@pytest.mark.parametrize("cls", [LRUCache, TTLCache])
def test_valid_max_size_constructs_normally(cls):
    cache = cls(max_size=1)
    cache.set("a", 1)
    assert cache.get("a") == 1
    assert len(cache) == 1
    cache.set("b", 2)  # evicts "a"
    assert cache.get("a") is None
    assert cache.get("b") == 2


def test_default_max_size_still_works():
    cache = LRUCache()
    cache.set("a", 1)
    assert cache.get("a") == 1
    ttl = TTLCache()
    ttl.set("a", 1)
    assert ttl.get("a") == 1


# ── Bug 10: DictCache thread safety ─────────────────────────────


def test_dict_cache_concurrent_set_get(tmp_path):
    cache = DictCache()
    errors = []
    n_threads = 8
    per_thread = 250

    def writer(tid):
        try:
            for i in range(per_thread):
                cache.set((tid, i), tid * per_thread + i)
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    def reader():
        try:
            for _ in range(200):
                for key in list(cache):
                    cache.get(key)
                    assert key in cache
                len(cache)
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(t,)) for t in range(n_threads)]
    threads.append(threading.Thread(target=reader))
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(cache) == n_threads * per_thread
    for tid in range(n_threads):
        for i in range(per_thread):
            assert cache.get((tid, i)) == tid * per_thread + i


def test_dict_cache_concurrent_clear_and_set():
    cache = DictCache()
    errors = []
    stop = threading.Event()

    def clobber():
        try:
            while not stop.is_set():
                cache.clear()
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    def writer():
        try:
            for i in range(500):
                cache.set("k", i)
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    t1 = threading.Thread(target=clobber)
    t2 = threading.Thread(target=writer)
    t1.start()
    t2.start()
    t2.join()
    stop.set()
    t1.join()

    assert errors == []
    assert cache.get("k") is None or isinstance(cache.get("k"), int)
