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


class TestByteLRUCache:
    """Byte-budgeted LRU: bounded by total weight (primary) and item count."""

    def make_cache(self, max_bytes, max_items=100):
        from AssetsManager.core.cache import ByteLRUCache
        # size_of uses the scalar value directly as its byte weight for control.
        return ByteLRUCache(max_items=max_items, max_bytes=max_bytes, size_of=lambda v: v)

    def test_insert_accumulates_bytes(self):
        cache = self.make_cache(max_bytes=1000)
        cache.set("a", 300)
        cache.set("b", 400)
        assert cache.cache_bytes == 700
        assert len(cache) == 2

    def test_byte_excess_evicts_oldest_lru(self):
        cache = self.make_cache(max_bytes=1000)
        cache.set("a", 300)
        cache.set("b", 300)
        cache.set("c", 300)
        assert cache.cache_bytes == 900  # all three fit
        cache.set("d", 300)  # would be 1200 > 1000 → evict "a" (LRU)
        assert cache.get("a") is None
        assert cache.get("b") == 300
        assert cache.get("c") == 300
        assert cache.get("d") == 300
        assert cache.cache_bytes == 900

    def test_item_limit_still_evicts_small_entries(self):
        cache = self.make_cache(max_bytes=10_000, max_items=3)
        # Weights are tiny relative to the byte budget, so the item cap rules.
        cache.set("a", 5)
        cache.set("b", 5)
        cache.set("c", 5)
        cache.set("d", 5)
        assert cache.get("a") is None
        assert cache.get("b") == 5
        assert cache.get("c") == 5
        assert cache.get("d") == 5
        assert len(cache) == 3

    def test_replace_updates_bytes_accounting(self):
        cache = self.make_cache(max_bytes=1000)
        cache.set("a", 300)
        cache.set("b", 300)
        cache.set("a", 800)  # replace: frees 300, adds 800 → 1100 > 1000 → evict "b"
        assert cache.get("a") == 800
        assert cache.get("b") is None
        assert cache.cache_bytes == 800

    def test_invalidate_decrements_bytes(self):
        cache = self.make_cache(max_bytes=1000)
        cache.set("a", 300)
        cache.set("b", 400)
        cache.invalidate("a")
        assert cache.get("a") is None
        assert cache.cache_bytes == 400

    def test_clear_resets_bytes_and_content(self):
        cache = self.make_cache(max_bytes=1000)
        cache.set("a", 300)
        cache.clear()
        assert len(cache) == 0
        assert cache.cache_bytes == 0

    def test_single_oversized_entry_is_not_cached(self):
        cache = self.make_cache(max_bytes=100)
        cache.set("a", 500)  # alone exceeds the budget
        assert cache.get("a") is None
        assert cache.cache_bytes == 0
        assert len(cache) == 0

    def test_uses_lru_not_insertion_order_after_gets(self):
        cache = self.make_cache(max_bytes=900)
        cache.set("a", 300)
        cache.set("b", 300)
        cache.set("c", 300)
        cache.get("a")  # "a" becomes MRU
        cache.set("d", 300)  # over budget → evict "b" (now LRU), keep "a"
        assert cache.get("b") is None
        assert cache.get("a") == 300
        assert cache.get("c") == 300
        assert cache.get("d") == 300

    def test_setitem_getitem_surface(self):
        from AssetsManager.core.cache import ByteLRUCache
        cache = ByteLRUCache(max_items=2, max_bytes=1000, size_of=lambda v: v)
        cache["a"] = 400
        cache["b"] = 400
        assert cache["a"] == 400  # makes "a" MRU → "b" becomes LRU
        cache["c"] = 400  # item cap 2 → evict LRU ("b")
        assert cache.get("a") == 400
        assert cache.get("b") is None
        assert cache.get("c") == 400
        assert cache.cache_bytes == 800

    def test_contains_and_iter(self):
        cache = self.make_cache(max_bytes=1000)
        cache.set("a", 100)
        assert "a" in cache
        assert "b" not in cache
        assert list(cache) == ["a"]
