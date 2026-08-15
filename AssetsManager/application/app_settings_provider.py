"""Application settings provider seam.

Only ``ApplicationBootstrap`` may call the settings singleton in the
application layer.  Every other application module resolves the configured
settings object through this seam, which bootstrap installs during its
constructor; tests install an equivalent provider in the shared conftest.
"""
from __future__ import annotations

from typing import Any, Callable

_SettingsProvider = Callable[[], Any]
_provider: _SettingsProvider | None = None


def install_app_settings_provider(provider: _SettingsProvider) -> None:
    """Install the canonical application settings provider."""
    global _provider
    if not callable(provider):
        raise TypeError("app settings provider must be callable")
    _provider = provider


def get_app_settings() -> Any:
    """Return the settings object installed by the composition root."""
    if _provider is None:
        raise RuntimeError(
            "Application settings provider is not installed; "
            "ApplicationBootstrap installs the singleton once."
        )
    return _provider()
