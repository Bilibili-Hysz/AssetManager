"""CPU backend for the background pipeline — the default and fallback path.

Reuses the validated ``AssetsManager.core.bg_effects`` functions inside the
effect-chain model, so CPU and GL cooperate on the same EffectChain intent.
"""
from __future__ import annotations

from PySide6.QtGui import QImage, QPixmap

from AssetsManager.background.model import EffectChain


def render_chain(image: QImage, chain: EffectChain) -> QImage:
    """Apply a CPU-supported effect chain to an image (dims preserved).

    ``shader`` stages are unsupported on the CPU backend by design; the
    manager never selects ``cpu`` for a chain that requires GL.
    """
    from AssetsManager.core.bg_effects import apply_blur, apply_kuwahara, apply_mosaic

    pm = QPixmap.fromImage(image)
    for effect in chain.effects:
        if not effect.active:
            continue
        if effect.kind == "blur":
            pm = apply_blur(pm, effect.intensity)
        elif effect.kind == "mosaic":
            pm = apply_mosaic(pm, effect.intensity)
        elif effect.kind == "kuwahara":
            pm = apply_kuwahara(pm, effect.intensity)
    return pm.toImage()