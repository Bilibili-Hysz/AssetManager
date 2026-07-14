"""Tests for core/cache.py LRUCache — bounded OrderedDict."""


class TestLRUCache:

    def test_basic_get_set(self):
        from AssetsManager.core.cache import LRUCache
        cache = LRUCache(max_size=3)
        cache.set("a", 1)
        assert cache.get("a") == 1

    def test_get_missing(self):
        from AssetsManager.core.cache import LRUCache
        cache = LRUCache(max_size=3)
        assert cache.get("missing") is None

    def test_eviction(self):
        from AssetsManager.core.cache import LRUCache
        cache = LRUCache(max_size=2)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)  # Should evict "a"
        assert cache.get("a") is None
        assert cache.get("b") == 2
        assert cache.get("c") == 3

    def test_lru_order(self):
        from AssetsManager.core.cache import LRUCache
        cache = LRUCache(max_size=2)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.get("a")  # "a" becomes most recent
        cache.set("c", 3)  # Should evict "b", not "a"
        assert cache.get("a") == 1
        assert cache.get("b") is None
        assert cache.get("c") == 3

    def test_contains(self):
        from AssetsManager.core.cache import LRUCache
        cache = LRUCache(max_size=3)
        cache.set("a", 1)
        assert "a" in cache
        assert "b" not in cache

    def test_len(self):
        from AssetsManager.core.cache import LRUCache
        cache = LRUCache(max_size=3)
        assert len(cache) == 0
        cache.set("a", 1)
        assert len(cache) == 1
        cache.set("b", 2)
        assert len(cache) == 2

    def test_remove(self):
        from AssetsManager.core.cache import LRUCache
        cache = LRUCache(max_size=3)
        cache.set("a", 1)
        cache.invalidate("a")
        assert cache.get("a") is None
        assert len(cache) == 0

    def test_remove_missing(self):
        from AssetsManager.core.cache import LRUCache
        cache = LRUCache(max_size=3)
        # Should not raise
        cache.invalidate("nonexistent")

    def test_clear(self):
        from AssetsManager.core.cache import LRUCache
        cache = LRUCache(max_size=3)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        assert len(cache) == 0

    def test_iter(self):
        from AssetsManager.core.cache import LRUCache
        cache = LRUCache(max_size=3)
        cache.set("a", 1)
        cache.set("b", 2)
        keys = list(cache)
        assert "a" in keys
        assert "b" in keys

    def test_getitem(self):
        from AssetsManager.core.cache import LRUCache
        cache = LRUCache(max_size=3)
        cache.set("a", 1)
        assert cache["a"] == 1

    def test_setitem(self):
        from AssetsManager.core.cache import LRUCache
        cache = LRUCache(max_size=3)
        cache["a"] = 1
        assert cache["a"] == 1

    def test_update_existing(self):
        from AssetsManager.core.cache import LRUCache
        cache = LRUCache(max_size=3)
        cache.set("a", 1)
        cache.set("a", 2)
        assert cache.get("a") == 2
        assert len(cache) == 1

    def test_max_size_one(self):
        from AssetsManager.core.cache import LRUCache
        cache = LRUCache(max_size=1)
        cache.set("a", 1)
        cache.set("b", 2)  # Should evict "a"
        assert cache.get("a") is None
        assert cache.get("b") == 2
