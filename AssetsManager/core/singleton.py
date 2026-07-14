"""Thread-safe singleton factory for core services.

Usage:
    from AssetsManager.core.singleton import ThreadSafeSingleton

    class MyService:
        _instance = None
        _lock = __import__('threading').Lock()

        @classmethod
        def instance(cls):
            return ThreadSafeSingleton.get(cls)

    # Or as a decorator:
    @ThreadSafeSingleton
    class MyService:
        pass
"""
import threading


class ThreadSafeSingleton:
    """Thread-safe singleton accessor.

    Ensures only one instance of the class is created, even when
    multiple threads call instance() simultaneously.
    """

    _locks: dict[type, threading.Lock] = {}
    _locks_guard = threading.Lock()

    @classmethod
    def get(cls, target_cls):
        """Get or create the singleton instance of target_cls."""
        with cls._locks_guard:
            lock = cls._locks.get(target_cls)
            if lock is None:
                lock = threading.Lock()
                cls._locks[target_cls] = lock

        # Fast path: instance already exists
        instance = getattr(target_cls, '_singleton_instance', None)
        if instance is not None:
            return instance

        # Slow path: create instance under lock
        with lock:
            # Double-check after acquiring lock
            instance = getattr(target_cls, '_singleton_instance', None)
            if instance is None:
                instance = target_cls()
                target_cls._singleton_instance = instance
        return instance

    @classmethod
    def reset(cls, target_cls):
        """Reset the singleton (for testing)."""
        with cls._locks_guard:
            lock = cls._locks.get(target_cls)
            if lock is None:
                lock = threading.Lock()
                cls._locks[target_cls] = lock
        with lock:
            target_cls._singleton_instance = None
