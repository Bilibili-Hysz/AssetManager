"""Tests for signal bus singleton."""
from AssetsManager.core.signal_bus import get, _SignalBus


def test_singleton():
    a = get()
    b = get()
    assert a is b
    assert isinstance(a, _SignalBus)


def test_signals_exist():
    bus = get()
    assert hasattr(bus, 'directory_changed')
    assert hasattr(bus, 'file_focused')
    assert hasattr(bus, 'refresh_requested')
    assert hasattr(bus, 'theme_changed')
    assert hasattr(bus, 'sidebar_depth_changed')
