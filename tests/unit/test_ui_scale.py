"""Tests for core/ui_scale.py — global zoom factor."""
import pytest


@pytest.fixture(autouse=True)
def _reset_settings():
    """Reset AppSettings before each test."""
    from AssetsManager.core.settings import AppSettings
    AppSettings.instance()._data = {}
    yield


class TestUiScale:

    def test_default_scale(self):
        from AssetsManager.core.ui_scale import get_ui_scale
        assert get_ui_scale() == 1.0

    def test_custom_scale(self):
        from AssetsManager.core.settings import AppSettings
        from AssetsManager.core.ui_scale import get_ui_scale
        AppSettings.instance().set("ui_scale", 1.5)
        assert get_ui_scale() == 1.5

    def test_scale_clamped_min(self):
        from AssetsManager.core.settings import AppSettings
        from AssetsManager.core.ui_scale import get_ui_scale
        AppSettings.instance().set("ui_scale", 0.1)
        assert get_ui_scale() == 0.5

    def test_scale_clamped_max(self):
        from AssetsManager.core.settings import AppSettings
        from AssetsManager.core.ui_scale import get_ui_scale
        AppSettings.instance().set("ui_scale", 5.0)
        assert get_ui_scale() == 3.0

    def test_scaled_px_default(self):
        from AssetsManager.core.ui_scale import scaled_px
        assert scaled_px(100) == 100

    def test_scaled_px_custom(self):
        from AssetsManager.core.settings import AppSettings
        from AssetsManager.core.ui_scale import scaled_px
        AppSettings.instance().set("ui_scale", 2.0)
        assert scaled_px(100) == 200

    def test_scaled_px_minimum(self):
        from AssetsManager.core.settings import AppSettings
        from AssetsManager.core.ui_scale import scaled_px
        AppSettings.instance().set("ui_scale", 0.1)
        # Even with very small scale, minimum is 1
        assert scaled_px(1) == 1

    def test_scaled_pt_default(self):
        from AssetsManager.core.ui_scale import scaled_pt
        assert scaled_pt(12) == 12

    def test_scaled_pt_custom(self):
        from AssetsManager.core.settings import AppSettings
        from AssetsManager.core.ui_scale import scaled_pt
        AppSettings.instance().set("ui_scale", 1.5)
        assert scaled_pt(12) == 18

    def test_scaled_pt_minimum(self):
        from AssetsManager.core.settings import AppSettings
        from AssetsManager.core.ui_scale import scaled_pt
        AppSettings.instance().set("ui_scale", 0.1)
        # Minimum is 6
        assert scaled_pt(10) == 6

    def test_scale_none_returns_default(self):
        from AssetsManager.core.settings import AppSettings
        from AssetsManager.core.ui_scale import get_ui_scale
        AppSettings.instance().set("ui_scale", None)
        assert get_ui_scale() == 1.0
