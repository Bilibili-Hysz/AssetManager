"""Shared constants across all panels."""
from AssetsManager.domain.asset import (
    IMAGE_EXTS as IMAGE_EXTS,  # noqa: F401
    VIDEO_EXTS as VIDEO_EXTS,  # noqa: F401
)

# Default accent color used for the LAN sharing page / QR theming. Kept in a
# single place so the desktop sharing settings, the tag style picker, and the
# LAN route fallback all agree without repeating the literal hex.
DEFAULT_LAN_THEME_COLOR = "#5b7ff5"
