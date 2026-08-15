"""G3 application provider seam tests."""
import pytest


def test_app_settings_provider_fails_closed_when_uninstalled(monkeypatch):
    from AssetsManager.application import app_settings_provider

    monkeypatch.setattr(app_settings_provider, "_provider", None)
    with pytest.raises(RuntimeError, match="not installed"):
        app_settings_provider.get_app_settings()


def test_tag_canonicalizer_fails_closed_when_uninstalled(monkeypatch):
    from AssetsManager.application import tag_canonicalizer

    monkeypatch.setattr(tag_canonicalizer, "_provider", None)
    with pytest.raises(RuntimeError, match="not installed"):
        tag_canonicalizer.canonical_tag("Texture")


def test_app_settings_provider_rejects_non_callable():
    from AssetsManager.application.app_settings_provider import install_app_settings_provider

    with pytest.raises(TypeError, match="callable"):
        install_app_settings_provider(object())  # type: ignore[arg-type]


def test_tag_canonicalizer_rejects_non_callable():
    from AssetsManager.application.tag_canonicalizer import install_tag_canonicalizer

    with pytest.raises(TypeError, match="callable"):
        install_tag_canonicalizer(object())  # type: ignore[arg-type]
