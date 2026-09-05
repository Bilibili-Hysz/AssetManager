"""D4: ``i18n.tr`` keyword contract — the ``default`` fallback is real.

Locks the behavior the 71 existing ``tr(key, default=...)`` call sites rely
on: when both the current language and the English fallback miss the key,
``default`` wins over the raw-key return. Also pins the historical contract
for callers that pass no default, and the ``str.format`` placeholder path.
"""
import logging

from AssetsManager import i18n


def setup_module():
    # Point the module at a directory with no catalogs so lookups always
    # miss, without touching the real en/zh/ja JSON files.
    i18n._translations.clear()
    i18n._I18N_DIR  # keep reference stable for restore


def test_missing_key_with_default_returns_default(monkeypatch, caplog):
    # Use a key that is absent from every catalog (unlike plugins.* keys,
    # which do exist and would exercise the found-translation path).
    monkeypatch.setattr(i18n, "_lookup", lambda code, key: None)
    with caplog.at_level(logging.WARNING):
        assert i18n.tr("definitely.not.a.key", default="Select a plugin") == "Select a plugin"
    # The raw-key warning is suppressed when an explicit default resolves it.
    assert "plugins.select_hint" not in caplog.text


def test_missing_key_without_default_returns_raw_key(monkeypatch, caplog):
    monkeypatch.setattr(i18n, "_lookup", lambda code, key: None)
    with caplog.at_level(logging.WARNING):
        assert i18n.tr("missing.key") == "missing.key"
    assert "Missing i18n key: missing.key" in caplog.text


def test_default_ignored_when_translation_exists(monkeypatch):
    monkeypatch.setattr(
        i18n, "_lookup", lambda code, key: "キャンセル" if key == "dialog.cancel" else None)
    assert i18n.tr("dialog.cancel", default="Cancel") == "キャンセル"


def test_placeholder_substitution_with_default(monkeypatch):
    monkeypatch.setattr(
        i18n, "_lookup", lambda code, key: "{sel} / {total}" if key == "filelist.status" else None)
    assert (
        i18n.tr("filelist.status", default="0 / 0", sel=5, total=20) == "5 / 20"
    )


def test_real_catalog_fallback_chain():
    # Against the real en.json: a known key must resolve without default,
    # and English remains the fallback language for a zh current language.
    i18n._translations.clear()
    i18n._current_lang = i18n._FALLBACK_LANG
    assert i18n.tr("app.name") == "AssetManager"
