"""Tests for the image background effect renderer (GPU shader + CPU fallback).

Runs without a display; on offscreen platforms the GL pipeline is unavailable
so these exercise the CPU fallback path and the graceful shader degradation.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor, QImage

from AssetsManager.background import ImageEffectRenderer


def _solid_image(w: int = 64, h: int = 48, color=(90, 140, 200)) -> QImage:
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(*color))
    return img


def test_renderer_none_returns_valid_image():
    out = ImageEffectRenderer().render(_solid_image(), "none", 0)
    assert out is not None and not out.isNull()
    assert (out.width(), out.height()) == (64, 48)


@pytest.mark.parametrize("effect,intensity", [("blur", 5), ("mosaic", 6), ("kuwahara", 4)])
def test_renderer_cpu_effects_return_valid_image(effect, intensity):
    out = ImageEffectRenderer().render(_solid_image(), effect, intensity)
    assert out is not None and not out.isNull()
    assert (out.width(), out.height()) == (64, 48)


def test_renderer_shader_without_gl_degrades_to_image():
    """Without GL, the shader effect shows the unmodified image (never black).
    Force the unavailable state so the assertion holds on any machine."""
    renderer = ImageEffectRenderer()
    renderer._gl_ready = False  # simulate GL unavailable (tri-state: None=unknown)
    src = _solid_image()
    out = renderer.render(src, "shader", 30, "plasma")
    assert out is not None and not out.isNull()
    assert (out.width(), out.height()) == (64, 48)
    # solid-colour input: the degraded output stays the same colour
    px = out.pixelColor(32, 24)
    assert (px.red(), px.green(), px.blue()) == (90, 140, 200)


def test_renderer_unknown_effect_falls_back_to_none():
    out = ImageEffectRenderer().render(_solid_image(), "not-a-thing", 1)
    assert out is not None and not out.isNull()


def test_renderer_shader_gpu_renders_preset():
    """On GL machines the shader effect really runs the GLSL preset.

    (Skips offscreen, where the pipeline degrades to the CPU path covered by
    the test above.)  A plasma preset over a solid-colour image must produce
    a non-uniform result, proving the fragment shader executed.
    """
    renderer = ImageEffectRenderer()
    if not renderer._ensure_gl():
        pytest.skip("no OpenGL context available on this machine")
    src = _solid_image(64, 48, color=(90, 140, 200))
    out = renderer._render_shader(src, 30, "plasma")
    assert out is not None and not out.isNull()
    a = out.pixelColor(8, 8)
    b = out.pixelColor(40, 32)
    assert (a.red(), a.green(), a.blue()) != (b.red(), b.green(), b.blue())