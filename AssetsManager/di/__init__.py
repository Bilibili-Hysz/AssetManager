"""Dependency injection container.

Provides a simple service locator for managing application-wide dependencies.
Services are registered by type and resolved by type. Supports both singleton
and factory registration patterns.

Usage:
    container = ServiceContainer()
    container.register(DatabaseManager)
    container.register(LibraryService, deps=[DatabaseManager])

    db = container.resolve(DatabaseManager)
    lib = container.resolve(LibraryService)
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, TypeVar

_log = logging.getLogger(__name__)

T = TypeVar("T")


class CircularDependencyError(Exception):
    """Raised when a circular dependency is detected during resolution."""


class ServiceContainer:
    """Simple dependency injection container.

    Thread-safe for resolve; register should be called during initialization.
    Uses RLock to allow reentrant resolution (service A resolving service B
    which resolves service A's dependency).
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._singletons: dict[type, Any] = {}
        self._factories: dict[type, Callable] = {}
        self._deps: dict[type, list[type]] = {}

    def register(
        self,
        service_type: type[T],
        instance: T | None = None,
        factory: Callable[..., T] | None = None,
        deps: list[type] | None = None,
    ) -> None:
        """Register a service.

        Args:
            service_type: The service class type.
            instance: A pre-created singleton instance.
            factory: A callable that creates instances.
            deps: Dependency types to auto-inject when using factory.
        """
        with self._lock:
            if instance is not None:
                self._singletons[service_type] = instance
            elif factory is not None:
                self._factories[service_type] = factory
            else:
                self._factories[service_type] = service_type
            if deps:
                self._deps[service_type] = deps

    def register_instance(self, service_type: type[T], instance: T) -> None:
        """Register a pre-created singleton instance."""
        with self._lock:
            self._singletons[service_type] = instance

    def register_factory(
        self,
        service_type: type[T],
        factory: Callable[..., T],
        deps: list[type] | None = None,
    ) -> None:
        """Register a factory function."""
        with self._lock:
            self._factories[service_type] = factory
            if deps:
                self._deps[service_type] = deps

    def resolve(self, service_type: type[T], _resolving: set[type] | None = None) -> T:
        """Resolve a service by type.

        Returns the singleton if registered, otherwise creates a new instance
        using the registered factory.  Detects circular dependencies and raises
        ``CircularDependencyError`` if found.
        """
        with self._lock:
            # Check singletons first
            if service_type in self._singletons:
                return self._singletons[service_type]

            # Check factories
            if service_type not in self._factories:
                raise KeyError(f"Service not registered: {service_type.__name__}")

            # Circular dependency detection
            if _resolving is None:
                _resolving = set()
            if service_type in _resolving:
                chain = " -> ".join(t.__name__ for t in _resolving) + f" -> {service_type.__name__}"
                raise CircularDependencyError(f"Circular dependency detected: {chain}")
            _resolving.add(service_type)

            factory = self._factories[service_type]
            deps = self._deps.get(service_type, [])
            cache_singleton = factory is service_type

            # Resolve dependencies and create class-registered singletons while
            # holding the RLock so concurrent first resolves cannot duplicate them.
            if cache_singleton:
                resolved_deps = [self.resolve(dep, _resolving) for dep in deps]
                instance = factory(*resolved_deps)
                self._singletons[service_type] = instance
                _resolving.discard(service_type)
                return instance

        # Custom factories are intentionally not cached, so they can run outside
        # the container lock while preserving circular dependency tracking.
        resolved_deps = [self.resolve(dep, _resolving) for dep in deps]
        instance = factory(*resolved_deps)

        with self._lock:
            if service_type in self._factories and self._factories[service_type] is service_type:
                self._singletons[service_type] = instance
            _resolving.discard(service_type)

        return instance

    def has(self, service_type: type) -> bool:
        """Check if a service type is registered."""
        with self._lock:
            return service_type in self._singletons or service_type in self._factories

    def clear(self) -> None:
        """Remove all registrations."""
        with self._lock:
            self._singletons.clear()
            self._factories.clear()
            self._deps.clear()

    def registered_types(self) -> list[type]:
        """Return all registered service types."""
        with self._lock:
            return list(set(self._singletons.keys()) | set(self._factories.keys()))
