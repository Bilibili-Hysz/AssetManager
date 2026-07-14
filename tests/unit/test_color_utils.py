"""Tests for core/color_utils.py — color utility functions."""
import pytest


class TestHexToRgb:

    def test_basic_hex(self):
        from AssetsManager.core.color_utils import _hex_to_rgb
        assert _hex_to_rgb("#ff0000") == (255, 0, 0)
        assert _hex_to_rgb("#00ff00") == (0, 255, 0)
        assert _hex_to_rgb("#0000ff") == (0, 0, 255)

    def test_shorthand_hex(self):
        from AssetsManager.core.color_utils import _hex_to_rgb
        assert _hex_to_rgb("#f00") == (255, 0, 0)
        assert _hex_to_rgb("#0f0") == (0, 255, 0)

    def test_no_hash(self):
        from AssetsManager.core.color_utils import _hex_to_rgb
        assert _hex_to_rgb("ff0000") == (255, 0, 0)


class TestRgbToHex:

    def test_basic_rgb(self):
        from AssetsManager.core.color_utils import _rgb_to_hex
        assert _rgb_to_hex(255, 0, 0) == "#ff0000"
        assert _rgb_to_hex(0, 255, 0) == "#00ff00"
        assert _rgb_to_hex(0, 0, 255) == "#0000ff"


class TestAlpha:

    def test_full_opacity(self):
        from AssetsManager.core.color_utils import alpha
        result = alpha("#ff0000", 1.0)
        assert "rgba(255, 0, 0, 1.00)" == result

    def test_half_opacity(self):
        from AssetsManager.core.color_utils import alpha
        result = alpha("#ff0000", 0.5)
        assert "rgba(255, 0, 0, 0.50)" == result

    def test_zero_opacity(self):
        from AssetsManager.core.color_utils import alpha
        result = alpha("#ff0000", 0.0)
        assert "rgba(255, 0, 0, 0.00)" == result


class TestLighten:

    def test_lighten_basic(self):
        from AssetsManager.core.color_utils import lighten
        result = lighten("#1e1e2a", 1.3)
        assert result.startswith("#")
        assert len(result) == 7

    def test_lighten_identity(self):
        from AssetsManager.core.color_utils import lighten
        result = lighten("#808080", 1.0)
        assert result == "#808080"


class TestDarken:

    def test_darken_basic(self):
        from AssetsManager.core.color_utils import darken
        result = darken("#faf7f2", 0.9)
        assert result.startswith("#")
        assert len(result) == 7

    def test_darken_identity(self):
        from AssetsManager.core.color_utils import darken
        result = darken("#808080", 1.0)
        assert result == "#808080"


class TestContrastRatio:

    def test_same_color(self):
        from AssetsManager.core.color_utils import contrast_ratio
        ratio = contrast_ratio("#ffffff", "#ffffff")
        assert ratio == pytest.approx(1.0, abs=0.01)

    def test_black_white(self):
        from AssetsManager.core.color_utils import contrast_ratio
        ratio = contrast_ratio("#ffffff", "#000000")
        assert ratio == pytest.approx(21.0, abs=0.1)

    def test_ratio_range(self):
        from AssetsManager.core.color_utils import contrast_ratio
        ratio = contrast_ratio("#b0b0c8", "#1e1e2a")
        assert 1.0 < ratio < 21.0
