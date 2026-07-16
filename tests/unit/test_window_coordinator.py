from AssetsManager.window import MainWindow
from AssetsManager.window_coordinator import WindowCoordinator


class _Signal:
    def __init__(self):
        self.callback = None

    def connect(self, callback):
        self.callback = callback


class _Animation:
    created = []

    def __init__(self, *_args):
        self.finished = _Signal()
        self.stopped = False
        _Animation.created.append(self)

    def setDuration(self, _value): pass
    def setStartValue(self, _value): pass
    def setEndValue(self, _value): pass
    def setEasingCurve(self, _value): pass
    def start(self): pass
    def stop(self): self.stopped = True


class _Window:
    def __init__(self):
        self.opacity = []
        self.applied = 0
        self._workspace = type("_Workspace", (), {"_apply_style": lambda _self: None})()
        self.file_list = None

    def setWindowOpacity(self, value): self.opacity.append(value)
    def refresh_bg(self): self.applied += 1


def test_main_window_theme_refresh_delegates_to_coordinator():
    calls: list[str] = []

    class _Coordinator:
        def on_theme_refresh(self):
            calls.append("refresh")

    window = type("_Window", (), {"_coordinator": _Coordinator()})()

    MainWindow._on_theme_refresh(window)

    assert calls == ["refresh"]


def test_reduce_motion_applies_without_constructing_animation(monkeypatch):
    window = _Window()
    coordinator = WindowCoordinator(window)
    monkeypatch.setattr("AssetsManager.window_coordinator.AppSettings.instance", lambda: type("_Settings", (), {"get": lambda _self, _key, _default: True})())
    monkeypatch.setattr(coordinator, "_apply_theme", lambda: setattr(window, "applied", window.applied + 1))
    monkeypatch.setattr("AssetsManager.window_coordinator.QPropertyAnimation", lambda *_args: (_ for _ in ()).throw(AssertionError("animation created")))

    coordinator.on_theme_refresh()

    assert window.applied == 1
    assert window.opacity == [1.0]


def test_stale_fade_out_callback_cannot_start_fade_in(monkeypatch):
    _Animation.created = []
    window = _Window()
    coordinator = WindowCoordinator(window)
    monkeypatch.setattr("AssetsManager.window_coordinator.AppSettings.instance", lambda: type("_Settings", (), {"get": lambda _self, _key, _default: False})())
    monkeypatch.setattr("AssetsManager.window_coordinator.QPropertyAnimation", _Animation)
    monkeypatch.setattr(coordinator, "_apply_theme", lambda: setattr(window, "applied", window.applied + 1))

    coordinator.on_theme_refresh()
    first = _Animation.created[0]
    coordinator.on_theme_refresh()
    second = _Animation.created[1]
    first.finished.callback()
    assert window.applied == 0
    assert len(_Animation.created) == 2
    second.finished.callback()
    assert window.applied == 1
    assert len(_Animation.created) == 3


def test_theme_refresh_stops_startup_fade_before_taking_opacity_ownership(monkeypatch):
    window = _Window()
    window._startup_anim = _Animation()
    coordinator = WindowCoordinator(window)
    monkeypatch.setattr("AssetsManager.window_coordinator.AppSettings.instance", lambda: type("_Settings", (), {"get": lambda _self, _key, _default: True})())
    monkeypatch.setattr(coordinator, "_apply_theme", lambda: None)

    coordinator.on_theme_refresh()

    assert window._startup_anim.stopped is True
    assert window.opacity == [1.0]
