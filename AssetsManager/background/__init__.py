"""Background rendering layer — image source, shader-ized effect chain.

See ``docs/plans/bg-simplify-image-only-2026-08-27.md``.  The wallpaper source
is always a static image; effects (blur/mosaic/kuwahara/shader) are rendered
by the GLSL pipeline with a CPU fallback and painted full-window by the plain
``MainWindow.paintEvent``.
"""
from AssetsManager.background.model import EffectChain, EffectSpec
from AssetsManager.background.pipeline import ImageEffectRenderer

__all__ = ["EffectChain", "EffectSpec", "ImageEffectRenderer"]