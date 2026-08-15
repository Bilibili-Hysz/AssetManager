"""Shared constants across core and presentation layers."""
from __future__ import annotations

# Image extensions eligible for gallery projection and thumbnailing.
# Kept in core so both the domain asset model and the presentation layers
# consume one definition without a core -> domain dependency.
IMAGE_EXTS: frozenset[str] = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".ico", ".svg",
})

# Video container extensions eligible for first-frame thumbnail extraction.
VIDEO_EXTS: frozenset[str] = frozenset({
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv",
})

# Default accent color used for the LAN sharing page / QR theming. Kept in a
# single place so the desktop sharing settings, the tag style picker, and the
# LAN route fallback all agree without repeating the literal hex.
DEFAULT_LAN_THEME_COLOR = "#5b7ff5"
