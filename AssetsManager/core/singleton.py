"""Thread-safe singleton factory for core services.

Usage:
    from AssetsManager.core.singleton import ThreadSafeSingleton

    class MyService:
        _instance = None
        _lock = __import__('threading').Lock()

        @classmethod
        def instance(cls):
            return ThreadSafeSingleton.get(cls)

    # Or as a decorator (either form works):
    @ThreadSafeSingleton
    class MyService:
        pass

    @ThreadSafeSingleton()
    class MyOtherService:
        pass

    # The decorated name exposes instance()/reset() classmethods:
    service = MyService.instance()
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
    def _wrap(cls, target_cls):
        """Build the class-decorator wrapper around *target_cls*."""

        class SingletonWrapper:
            @classmethod
            def instance(cls):
                return ThreadSafeSingleton.get(target_cls)

            @classmethod
            def reset(cls):
                return ThreadSafeSingleton.reset(target_cls)

        SingletonWrapper.__name__ = target_cls.__name__
        SingletonWrapper.__qualname__ = target_cls.__qualname__
        SingletonWrapper.__doc__ = target_cls.__doc__
        return SingletonWrapper

    def __new__(cls, target_cls=None):
        """Support the bare ``@ThreadSafeSingleton`` decorator form."""
        if target_cls is not None:
            if not isinstance(target_cls, type):
                raise TypeError(
                    "ThreadSafeSingleton can only decorate classes, "
                    f"got {target_cls!r}"
                )
            return cls._wrap(target_cls)
        return super().__new__(cls)

    def __call__(self, target_cls):
        """Support the ``@ThreadSafeSingleton()`` decorator form."""
        if not isinstance(target_cls, type):
            raise TypeError(
                "ThreadSafeSingleton can only decorate classes, "
                f"got {target_cls!r}"
            )
        return self._wrap(target_cls)

    @classmethod
    def get(cls, target_cls):
        """Get or create the singleton instance of target_cls."""
        with cls._locks_guard:
            lock = cls._locks.get(target_cls)
            if lock is None:
                lock = threading.Lock()
                cls._locks[target_cls] = lock

        # Every read and write of _singleton_instance happens under the
        # per-class lock, so get() never returns an instance that a
        # concurrent reset() has already cleared.
        with lock:
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
