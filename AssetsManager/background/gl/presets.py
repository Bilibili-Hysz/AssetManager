"""Shadertoy-style preset registry for the GL background backend.

A preset is a ``mainImage(fragColor, fragCoord)`` GLSL snippet appended to the
Shadertoy-compatible wrapper in :mod:`shaders`.  ``iResolution`` / ``iTime`` /
``u_strength`` / ``iChannel0..1`` uniforms are provided by the renderer.
"""
from __future__ import annotations

from dataclasses import dataclass

from AssetsManager.background.gl import shaders


@dataclass(frozen=True)
class ShaderPreset:
    key: str
    display_name: str
    fragment: str  # mainImage body (appended after SHADERTOY_HEADER)


_BUILTIN: tuple[ShaderPreset, ...] = (
    ShaderPreset("plasma", "等离子体 (Plasma)", shaders.PRESET_FRAGMENT_SNIPPETS["plasma"]),
    ShaderPreset("grid-flow", "流动网格 (Grid Flow)", shaders.PRESET_FRAGMENT_SNIPPETS["grid-flow"]),
)

_REGISTRY: dict[str, ShaderPreset] = {p.key: p for p in _BUILTIN}


def preset_keys() -> list[str]:
    return list(_REGISTRY)


def get_preset(key: str) -> ShaderPreset | None:
    return _REGISTRY.get(key)


def display_name(key: str) -> str:
    preset = _REGISTRY.get(key)
    return preset.display_name if preset else key


def get_display_names() -> list[str]:
    return [display_name(k) for k in preset_keys()]


def resolve(key: str) -> str:
    """Validate a settings-stored preset key; unknown keys fall back to the
    first built-in preset (never render nothing)."""
    if key in _REGISTRY:
        return key
    return _BUILTIN[0].key if _BUILTIN else ""