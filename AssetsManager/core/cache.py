"""Unified cache framework for AssetsManager.

Provides:
- DictCache: simple dict-based cache (unbounded)
- LRUCache: bounded by count (least-recently-used eviction, thread-safe)
- TTLCache: bounded by time-to-live

All caches share the same interface:
    cache = LRUCache(500)
    cache.get(key) -> value | None
    cache.set(key, value)
    cache.invalidate(key)
    cache.clear()
    key in cache -> bool
    len(cache) -> int
"""
from collections import OrderedDict
import threading
import time


_MISSING = object()


class DictCache:
    """Simple dict-based cache. No eviction. Thread-safe."""

    def __init__(self):
        self._store: dict = {}
        self._lock = threading.RLock()

    def get(self, key):
        with self._lock:
            return self._store.get(key)

    def set(self, key, value):
        with self._lock:
            self._store[key] = value

    def invalidate(self, key):
        with self._lock:
            self._store.pop(key, None)

    def clear(self):
        with self._lock:
            self._store.clear()

    def __contains__(self, key):
        with self._lock:
            return key in self._store

    def __len__(self):
        with self._lock:
            return len(self._store)

    def __iter__(self):
        with self._lock:
            return iter(list(self._store))


class LRUCache:
    """Bounded cache with least-recently-used eviction. Thread-safe."""

    def __init__(self, max_size: int = 1000):
        if max_size < 1:
            raise ValueError(f"max_size must be >= 1, got {max_size}")
        self._store: OrderedDict = OrderedDict()
        self._max = max_size
        self._lock = threading.RLock()

    def get(self, key):
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
                return self._store[key]
            return None

    def set(self, key, value):
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            else:
                while len(self._store) >= self._max:
                    self._store.popitem(last=False)
            self._store[key] = value

    def invalidate(self, key):
        with self._lock:
            self._store.pop(key, None)

    def clear(self):
        with self._lock:
            self._store.clear()

    def __contains__(self, key):
        with self._lock:
            return self._store.get(key, _MISSING) is not _MISSING

    def __getitem__(self, key):
        with self._lock:
            self._store.move_to_end(key)
            return self._store[key]

    def __setitem__(self, key, value):
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            else:
                while len(self._store) >= self._max:
                    self._store.popitem(last=False)
            self._store[key] = value

    def __delitem__(self, key):
        with self._lock:
            del self._store[key]

    def __len__(self):
        with self._lock:
            return len(self._store)

    def __iter__(self):
        with self._lock:
            return iter(list(self._store))


class TTLCache:
    """Cache with time-to-live eviction. Thread-safe."""

    def __init__(self, ttl_seconds: float = 300, max_size: int = 1000):
        if max_size < 1:
            raise ValueError(f"max_size must be >= 1, got {max_size}")
        self._store: OrderedDict = OrderedDict()
        self._timestamps: dict = {}
        self._ttl = ttl_seconds
        self._max = max_size
        self._lock = threading.RLock()

    def get(self, key):
        with self._lock:
            if key in self._store:
                ts = self._timestamps.get(key, 0)
                if time.time() - ts < self._ttl:
                    self._store.move_to_end(key)
                    return self._store[key]
                else:
                    del self._store[key]
                    del self._timestamps[key]
            return None

    def set(self, key, value):
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            else:
                while len(self._store) >= self._max:
                    oldest_key, _ = self._store.popitem(last=False)
                    self._timestamps.pop(oldest_key, None)
            self._store[key] = value
            self._timestamps[key] = time.time()

    def invalidate(self, key):
        with self._lock:
            self._store.pop(key, None)
            self._timestamps.pop(key, None)

    def clear(self):
        with self._lock:
            self._store.clear()
            self._timestamps.clear()

    def __contains__(self, key):
        with self._lock:
            if key not in self._store:
                return False
            ts = self._timestamps.get(key, 0)
            return time.time() - ts < self._ttl

    def __len__(self):
        with self._lock:
            return len(self._store)
