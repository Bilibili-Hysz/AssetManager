"""Shared constants across core and presentation layers."""
from __future__ import annotations

# Image extensions eligible for gallery projection and thumbnailing.
# Kept in core so both the domain asset model and the presentation layers
# consume one definition without a core -> domain dependency.
IMAGE_EXTS: frozenset[str] = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".ico", ".svg",
})

# Professional-format image extensions (port batch N-B): RAW camera files,
# Photoshop documents, and OpenEXR. Deliberately NOT part of IMAGE_EXTS —
# QImageReader/Pillow cannot decode them, so adding them there would route
# them into decode paths that always fail. They are merged into the image
# *category* (format_utils CATEGORY_MAP + asset_filters FILTER_CATEGORY_EXTS)
# so badges, filters and include_types agree across desktop and LAN; actual
# decoding goes through application/media/decoders.py when the optional
# requirements-media.txt extras are installed (.exr is category-only for now).
MEDIA_IMAGE_EXTS: frozenset[str] = frozenset({
    ".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".raf", ".rw2",
    ".psd", ".psb",
    ".exr",
})

# Video container extensions eligible for first-frame thumbnail extraction.
VIDEO_EXTS: frozenset[str] = frozenset({
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv",
})

# Audio container extensions eligible for waveform thumbnail generation
# (port batch N-B2, application/media/analysis.py). Deliberately NOT part of
# any filter category yet — audio files keep their category/badge behavior
# and only gain the waveform thumbnail pipeline.
AUDIO_EXTS: frozenset[str] = frozenset({
    ".mp3", ".wav", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".aac",
    ".wma", ".aif", ".aiff",
})

# Default accent color used for the LAN sharing page / QR theming. Kept in a
# single place so the desktop sharing settings, the tag style picker, and the
# LAN route fallback all agree without repeating the literal hex.
DEFAULT_LAN_THEME_COLOR = "#5b7ff5"
