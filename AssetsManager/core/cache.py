"""Unified cache framework for AssetsManager.

Provides:
- DictCache: simple dict-based cache (unbounded)
- LRUCache: bounded by count (least-recently-used eviction, thread-safe)
- ByteLRUCache: bounded by total byte weight and item count (LRU, thread-safe)
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


class ByteLRUCache:
    """LRU cache bounded by total byte weight (primary) and item count.

    ``size_of(value)`` returns the weight of an entry — e.g.
    ``pixmap.width() * pixmap.height() * 4`` for ARGB32 pixmaps.  A new entry
    is inserted when there is room; otherwise least-recently-used entries are
    evicted until both the byte budget and the item budget are satisfied.
    Entries whose weight alone exceeds the byte budget are not cached at all.

    Thread-safe; identical surface to :class:`LRUCache`.
    """

    def __init__(self, max_items: int = 1000, *, max_bytes: int | None = None, size_of=None):
        if max_items < 1:
            raise ValueError(f"max_items must be >= 1, got {max_items}")
        if max_bytes is not None and max_bytes < 1:
            raise ValueError(f"max_bytes must be >= 1, got {max_bytes}")
        self._store: OrderedDict = OrderedDict()
        self._max_items = max_items
        self._max_bytes = max_bytes
        self._size_of = size_of
        self._cache_bytes: int = 0
        self._lock = threading.RLock()

    @property
    def cache_bytes(self) -> int:
        """Total byte weight of the cached entries (0 when size_of is None)."""
        with self._lock:
            return self._cache_bytes

    def _entry_bytes(self, value) -> int:
        if self._size_of is None:
            return 0
        try:
            size = self._size_of(value)
        except Exception:
            return 0
        try:
            return max(0, int(size))
        except (TypeError, ValueError):
            return 0

    def _evict_oldest(self) -> None:
        if not self._store:
            return
        _key, value = self._store.popitem(last=False)
        self._cache_bytes -= self._entry_bytes(value)
        if self._cache_bytes < 0:
            self._cache_bytes = 0

    def get(self, key):
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
                return self._store[key]
            return None

    def _insert(self, key, value) -> None:
        """Add or replace ``value`` under ``key`` after making room for it.

        The caller must have already released the old entry's byte weight when
        replacing an existing key.
        """
        size = self._entry_bytes(value)
        if self._max_bytes is not None and size > self._max_bytes:
            # A single oversized entry cannot fit; do not cache it.
            return
        # Byte budget: evict LRU entries until the new entry fits.
        while (
            self._max_bytes is not None
            and self._cache_bytes + size > self._max_bytes
            and len(self._store) >= 1
        ):
            self._evict_oldest()
        if self._max_bytes is None or self._cache_bytes + size <= self._max_bytes:
            self._store[key] = value
            self._cache_bytes += size

    def set(self, key, value):
        with self._lock:
            old = self._store.pop(key, None)
            if old is not None:
                self._cache_bytes = max(0, self._cache_bytes - self._entry_bytes(old))
            while len(self._store) >= self._max_items:
                self._evict_oldest()
            self._insert(key, value)

    def invalidate(self, key):
        with self._lock:
            value = self._store.pop(key, None)
            if value is not None:
                self._cache_bytes = max(0, self._cache_bytes - self._entry_bytes(value))

    def clear(self):
        with self._lock:
            self._store.clear()
            self._cache_bytes = 0

    def __contains__(self, key):
        with self._lock:
            return self._store.get(key, _MISSING) is not _MISSING

    def __getitem__(self, key):
        with self._lock:
            self._store.move_to_end(key)
            return self._store[key]

    def __setitem__(self, key, value):
        with self._lock:
            old = self._store.pop(key, None)
            if old is not None:
                self._cache_bytes = max(0, self._cache_bytes - self._entry_bytes(old))
            while len(self._store) >= self._max_items:
                self._evict_oldest()
            self._insert(key, value)

    def __delitem__(self, key):
        with self._lock:
            value = self._store.pop(key, None)
            if value is not None:
                self._cache_bytes = max(0, self._cache_bytes - self._entry_bytes(value))

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
