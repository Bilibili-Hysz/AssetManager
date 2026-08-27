"""Background rendering layer — the effect-chain data model.

Design: ``docs/plans/bg-simplify-image-only-2026-08-27.md``.

Settings express *intent* for the image background: ``bg_effect`` (plus an
intensity knob and an optional shader preset).  The effect chain is rendered
by either the GLSL pipeline (GPU) or the CPU fallback in
``AssetsManager.background.pipeline``; the whole-window composition stays the
plain CPU ``paintEvent`` so the wallpaper always covers the full window.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EffectKind = Literal["none", "blur", "mosaic", "kuwahara", "shader"]

# Effects the CPU backend (existing bg_effects pipeline) can carry.
CPU_EFFECT_KINDS: frozenset[str] = frozenset({"none", "blur", "mosaic", "kuwahara"})


@dataclass(frozen=True)
class EffectSpec:
    """One effect stage: kind + a single intensity knob (1-50) + optional preset."""

    kind: EffectKind = "none"
    intensity: int = 0
    shader_key: str = ""  # preset name when kind == "shader"

    @property
    def active(self) -> bool:
        if self.kind == "blur":
            return self.intensity > 0
        if self.kind == "mosaic":
            return self.intensity > 1
        return self.intensity >= 1  # kuwahara / shader


@dataclass(frozen=True)
class EffectChain:
    """Ordered effect stages (single-stage today, chain-ready by design)."""

    effects: tuple[EffectSpec, ...] = ()

    @staticmethod
    def single(kind: EffectKind, intensity: int = 0, shader_key: str = "") -> "EffectChain":
        return EffectChain((EffectSpec(kind=kind, intensity=intensity, shader_key=shader_key),))

    @property
    def is_empty(self) -> bool:
        return not any(e.active for e in self.effects)

    def requires_gl(self) -> bool:
        return any(e.kind == "shader" and e.active for e in self.effects)

    def cpu_supported(self) -> bool:
        return all(e.kind in CPU_EFFECT_KINDS for e in self.effects)