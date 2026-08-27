"""Background rendering layer — settings intent -> CPU/GL backend plans.

See ``docs/plans/bg-gpu-shader-architecture-2026-08-27.md`` for the
architecture this package implements (background sources, effect chain,
GL surface, backend manager).
"""
from AssetsManager.background.manager import BackgroundManager
from AssetsManager.background.model import BackendPlan, EffectChain, EffectSpec

__all__ = ["BackgroundManager", "BackendPlan", "EffectChain", "EffectSpec"]