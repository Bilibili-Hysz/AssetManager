"""Tests for ServiceContainer."""
import pytest
import threading
import time

from AssetsManager.di import CircularDependencyError, ServiceContainer


class TestServiceContainer:

    def test_register_and_resolve_class(self):
        container = ServiceContainer()

        class Foo:
            pass

        container.register(Foo)
        result = container.resolve(Foo)
        assert isinstance(result, Foo)

    def test_register_instance(self):
        container = ServiceContainer()
        instance = object()
        container.register_instance(str, instance)
        assert container.resolve(str) is instance

    def test_register_factory(self):
        container = ServiceContainer()
        container.register_factory(int, lambda: 42)
        assert container.resolve(int) == 42

    def test_resolve_with_deps(self):
        container = ServiceContainer()

        class Dep:
            pass

        class Service:
            def __init__(self, dep: Dep):
                self.dep = dep

        container.register(Dep)
        container.register(Service, deps=[Dep])

        result = container.resolve(Service)
        assert isinstance(result, Service)
        assert isinstance(result.dep, Dep)

    def test_resolve_unregistered_raises(self):
        container = ServiceContainer()
        with pytest.raises(KeyError, match="Service not registered"):
            container.resolve(str)

    def test_has(self):
        container = ServiceContainer()
        assert container.has(str) is False
        container.register(str)
        assert container.has(str) is True

    def test_clear(self):
        container = ServiceContainer()
        container.register(int)
        container.register(str)
        assert len(container.registered_types()) == 2
        container.clear()
        assert len(container.registered_types()) == 0

    def test_singleton_behavior(self):
        container = ServiceContainer()

        class Foo:
            pass

        container.register(Foo)
        a = container.resolve(Foo)
        b = container.resolve(Foo)
        assert a is b

    def test_factory_creates_new_instances(self):
        container = ServiceContainer()
        counter = {"n": 0}

        def factory():
            counter["n"] += 1
            return counter["n"]

        container.register_factory(int, factory)
        assert container.resolve(int) == 1
        assert container.resolve(int) == 2

    def test_circular_dependency_raises(self):
        container = ServiceContainer()

        class A:
            def __init__(self, b: "B"):
                self.b = b

        class B:
            def __init__(self, a: A):
                self.a = a

        container.register(A, deps=[B])
        container.register(B, deps=[A])

        with pytest.raises(CircularDependencyError, match="Circular dependency"):
            container.resolve(A)

    def test_self_dependency_raises(self):
        container = ServiceContainer()

        class SelfRef:
            def __init__(self, s: "SelfRef"):
                self.s = s

        container.register(SelfRef, deps=[SelfRef])

        with pytest.raises(CircularDependencyError, match="Circular dependency"):
            container.resolve(SelfRef)

    def test_concurrent_first_resolve_creates_one_instance(self):
        container = ServiceContainer()
        created = 0

        class Foo:
            def __init__(self):
                nonlocal created
                created += 1
                time.sleep(0.01)

        container.register(Foo)

        results = []

        def worker():
            results.append(container.resolve(Foo))

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert created == 1
        assert results[0] is results[1]
