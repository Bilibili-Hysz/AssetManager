"""Shared AI-tagging helpers for the desktop surfaces (H2-c v1).

Both the InfoPanel single-image button and the FileList batch action need
the same two things: the explicit-enable gate and the per-``kind`` user
copy. Nothing else about AI tagging lives in the presentation layer.
"""
from __future__ import annotations

from AssetsManager import i18n
from AssetsManager.application.ai_tagging.ollama_client import AiTaggingErrorKind

tr = i18n.tr

# Per-kind copy keys: auth/quota mean the daemon/model is missing or the
# compat layer is off; network/timeout get a retry hint; invalid_response
# means the model answered but not in the expected JSON shape.
_KIND_TEXT_KEYS: dict[str, str] = {
    AiTaggingErrorKind.AUTH: "ai.error_service",
    AiTaggingErrorKind.QUOTA: "ai.error_service",
    AiTaggingErrorKind.NETWORK: "ai.error_network",
    AiTaggingErrorKind.TIMEOUT: "ai.error_network",
    AiTaggingErrorKind.INVALID_RESPONSE: "ai.error_invalid",
}


def ai_tagging_enabled() -> bool:
    """True only when the user explicitly enabled AI tagging in settings.

    Tolerates minimal settings shims (test fakes) that only implement the
    generic ``get``: the feature fails closed (off) whenever the typed
    getter is unavailable or the stored value is not exactly ``True``.
    """
    from AssetsManager.core.settings import AppSettings
    settings = AppSettings.instance()
    getter = getattr(settings, "get_ai_tagging_enabled", None)
    if getter is not None:
        return bool(getter())
    return settings.get("ai_tagging_enabled", False) is True


def ai_tag_error_text(kind: str | None) -> str:
    """Map an ``AiTaggingError.kind`` to three-language user copy."""
    return tr(_KIND_TEXT_KEYS.get(kind or "", "ai.error_network"))
