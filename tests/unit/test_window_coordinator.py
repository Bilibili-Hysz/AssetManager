import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

from AssetsManager.core import themes
from AssetsManager.core.settings import AppSettings
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
    def refresh_bg(self, keep_rendered: bool = False): self.applied += 1


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


# ── Theme path must keep the rendered wallpaper cache ─────────────


class _ThemeWindow(QMainWindow):
    """Minimal window surface satisfying the coordinator protocol."""

    def __init__(self):
        super().__init__()
        self._menu_widget = QWidget()
        self._menu_bar = QWidget()
        self._share_status_label = QWidget()
        self._workspace = SimpleNamespace(_apply_style=lambda: None)
        self.file_list = None
        self.refresh_bg_calls: list[bool] = []

    def refresh_bg(self, keep_rendered: bool = False):
        self.refresh_bg_calls.append(keep_rendered)


def test_apply_theme_refreshes_bg_without_dropping_wallpaper_cache():
    app = QApplication.instance() or QApplication([])
    window = _ThemeWindow()
    coordinator = WindowCoordinator(window)
    previous_stylesheet = app.styleSheet()
    try:
        coordinator._apply_theme()
    finally:
        app.setStyleSheet(previous_stylesheet)
        window.deleteLater()
        app.processEvents()

    # The theme path must repaint but must NOT invalidate the rendered
    # wallpaper (theme colors never affect the wallpaper output).
    assert window.refresh_bg_calls == [True]


class _CountingRenderer:
    """Fake wallpaper effect renderer that only counts render passes."""

    def __init__(self):
        self.render_calls = 0

    def render(self, image, _effect, _intensity, _preset):
        self.render_calls += 1
        return image


class _WallpaperHost(QMainWindow):
    """Bare host borrowing the real MainWindow wallpaper pipeline."""

    _bg_renderer = MainWindow._bg_renderer
    _render_bg_image = MainWindow._render_bg_image
    _paint_image_wallpaper = MainWindow._paint_image_wallpaper
    refresh_bg = MainWindow.refresh_bg

    def __init__(self):
        super().__init__()
        self._bg_cache: tuple = ("", None, None)
        self._bg_effects_cache_key: str = ""
        self._bg_dirty = False
        self._bg_effect_renderer = _CountingRenderer()
        self.resize(200, 150)


_BG_SETTING_KEYS = (
    "bg_enabled", "bg_image", "bg_effect", "bg_effect_intensity",
    "bg_shader_preset", "bg_overall_opacity",
)


def test_theme_refresh_does_not_rerender_wallpaper(tmp_path):
    app = QApplication.instance() or QApplication([])
    image = QImage(8, 8, QImage.Format.Format_RGB32)
    image.fill(0xFF336699)
    path = tmp_path / "bg.png"
    assert image.save(str(path))

    themes.invalidate_cache()
    settings = AppSettings.instance()
    # Snapshot the raw entries: validated keys (bg_effect, bg_shader_preset)
    # reject None via set(), so absent originals must be restored by deleting
    # the entry instead of setting it back.
    keys = list(_BG_SETTING_KEYS)
    originals = {key: settings._data.get(key) for key in keys}
    had_key = {key: key in settings._data for key in keys}
    settings.set("bg_enabled", True)
    settings.set("bg_image", str(path))
    settings.set("bg_effect", "none")
    host = _WallpaperHost()
    try:
        host.show()
        app.processEvents()

        # First paint renders once and caches the processed pixmap.
        host._paint_image_wallpaper(str(path), 0.5)
        assert host._bg_cache[0] == str(path)
        assert host._bg_effect_renderer.render_calls == 1

        # An unchanged repaint is a pure cache hit.
        host._paint_image_wallpaper(str(path), 0.5)
        assert host._bg_effect_renderer.render_calls == 1

        # Theme refresh keeps the rendered cache: still exactly one render.
        host.refresh_bg(keep_rendered=True)
        host._paint_image_wallpaper(str(path), 0.5)
        assert host._bg_effect_renderer.render_calls == 1

        # A settings-driven full refresh still invalidates and re-renders.
        host.refresh_bg()
        host._paint_image_wallpaper(str(path), 0.5)
        assert host._bg_effect_renderer.render_calls == 2
    finally:
        host.close()
        host.deleteLater()
        app.processEvents()
        for key in keys:
            if had_key[key]:
                settings._data[key] = originals[key]
            else:
                settings._data.pop(key, None)
        themes.invalidate_cache()
