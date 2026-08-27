"""OpenGL capability probe.

Rendering fallback policy (design D-1/D-3): every GL capability is gated by
``gl_available()``; anything that cannot create a context makes the whole
background pipeline fall back to the CPU backend instead of failing hard.
"""
from __future__ import annotations

from PySide6.QtGui import QOpenGLContext, QOffscreenSurface

_CACHED: bool | None = None


def gl_available(force_refresh: bool = False) -> bool:
    """True when an OpenGL context can be created on this machine.

    The result is cached (the probe is only meaningful once per process);
    pass ``force_refresh=True`` in tests that swap the platform.
    """
    global _CACHED
    if _CACHED is not None and not force_refresh:
        return _CACHED
    ok = False
    try:
        surface = QOffscreenSurface()
        surface.create()
        if not surface.isValid():
            return False
        ctx = QOpenGLContext()
        if not ctx.create():
            return False
        ok = ctx.makeCurrent(surface)
        ctx.doneCurrent()
        ctx.deleteLater()
        surface.deleteLater()
    except Exception:
        ok = False
    _CACHED = ok
    return _CACHED


def reset_gl_available() -> None:
    """Forget the cached probe result (test hook)."""
    global _CACHED
    _CACHED = None