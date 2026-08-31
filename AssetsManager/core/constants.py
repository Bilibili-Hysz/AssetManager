"""Shared constants across core and presentation layers."""
from __future__ import annotations

# Application version — the SINGLE SOURCE OF TRUTH for the app's identity.
# Every other consumer (About dialog, PyInstaller spec version resource,
# installer build script) must derive its version from this constant instead
# of declaring its own copy; a release bump touches only this line.
APP_VERSION = "0.1.0"

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

# ── Scale observation thresholds (H2) ────────────────────────────
# Derived from the 100k-asset extrapolation table (H2 scale plan): ~100k assets
# ≈ 4 GB of thumbnail artifacts, and the real bottleneck is undeclared
# constants, not SQLite. These two thresholds drive the maintenance tab's
# library-health card warning coloring — they are *observation* thresholds
# (surface a warning before the size ceiling becomes an incident), not
# enforcement caps; enforcement uses the user-configured thumbnail cache cap.
#: Thumbnail cache size at/above which the health card warns (2 GB ≈ half the
#: extrapolated 100k-asset footprint — an early, still-actionable signal).
THUMBNAIL_CACHE_WARNING_BYTES = 2 * 1024 * 1024 * 1024
#: WAL file size at/above which the health card warns. Sustained WAL growth at
#: this scale means automatic checkpointing is not keeping up with writes.
WAL_FILE_WARNING_BYTES = 256 * 1024 * 1024
#: Default thumbnail disk-cache capacity cap (H2-a2, ~2 GB for a default
#: install; the 100k-asset extrapolation puts the unbounded cache near 4 GB).
#: ``0`` means unlimited. The default matches THUMBNAIL_CACHE_WARNING_BYTES so
#: a stock install starts evicting the least-recently-viewed long tail before
#: the extrapolated footprint doubles.
THUMBNAIL_CACHE_DEFAULT_MAX_BYTES = 2 * 1024 * 1024 * 1024
