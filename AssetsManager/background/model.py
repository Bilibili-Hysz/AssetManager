"""Background rendering layer — data model shared by the CPU and GL backends.

Design: ``docs/plans/bg-gpu-shader-architecture-2026-08-27.md``.
Settings only express intent (``bg_type`` / ``bg_effect`` / intensity / shader
preset); the BackgroundManager turns that intent into a rendered backend.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EffectKind = Literal["none", "blur", "mosaic", "kuwahara", "shader"]
SourceKind = Literal["image", "video", "shader"]
BackendName = Literal["none", "cpu", "gl"]

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


@dataclass(frozen=True)
class BackendPlan:
    """What the window should do, decided by BackgroundManager."""

    backend: BackendName = "none"
    source_kind: SourceKind = "image"
    chain: EffectChain = EffectChain()
    shader_preset: str = ""
    source_path: str = ""  # wallpaper file (video/shader source or image path)
    reason: str = ""