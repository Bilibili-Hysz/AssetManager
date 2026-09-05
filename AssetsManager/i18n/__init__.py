"""I18n LocaleManager — JSON-based translation with live language switching.

Usage:
    from AssetsManager.i18n import tr, set_language, languages
    label.setText(tr("startup.hero_title"))
    label.setText(tr("filelist.status", sel=5, total=20, size="", mode="Grid"))
"""
import json
import logging
from pathlib import Path

from AssetsManager.core.settings import AppSettings
from AssetsManager.core.signal_bus import get as bus

_log = logging.getLogger(__name__)

_I18N_DIR = Path(__file__).resolve().parent
_FALLBACK_LANG = "en"
_current_lang: str = _FALLBACK_LANG
_translations: dict[str, dict] = {}  # {lang_code: data_dict}
_initialized = False


def init():
    """Load saved language and preload translations. Call once at startup."""
    global _current_lang, _initialized
    if _initialized:
        return
    _initialized = True
    saved = AppSettings.instance().get("language")
    if saved in _available_codes():
        _current_lang = saved
    _log.info("I18n initialized: lang=%s", _current_lang)


def tr(key: str, default: str | None = None, **kwargs) -> str:
    """Translate a dot-notation key to the current language.

    Falls back to English if key or language is missing. When both miss and
    ``default`` is given, returns ``default`` instead of the raw key; without
    ``default`` the raw key is returned (historical contract, and callers
    such as ``_sharing_helpers`` previously relied on a nonexistent kwarg
    silently vanishing into ``str.format``).
    Supports {placeholder} substitution via str.format().
    """
    text = _lookup(_current_lang, key)
    if text is None and _current_lang != _FALLBACK_LANG:
        text = _lookup(_FALLBACK_LANG, key)
    if text is None:
        if default is not None:
            return default
        _log.warning("Missing i18n key: %s", key)
        return key
    if kwargs:
        return text.format(**kwargs)
    return text


def set_language(code: str) -> None:
    """Switch language, save preference, and broadcast via signal bus."""
    global _current_lang
    if code not in _available_codes():
        _log.warning("Unknown language code: %s", code)
        return
    _current_lang = code
    AppSettings.instance().set("language", code)
    AppSettings.instance().save()
    bus().language_changed.emit(code)
    _log.info("Language switched to: %s", code)


def languages() -> dict[str, str]:
    """Return {code: native_name} for all available languages."""
    result = {}
    for code in _available_codes():
        data = _load_lang(code)
        result[code] = data.get("_meta", {}).get("native_name", code)
    return result


def current_language() -> str:
    return _current_lang


# ── Internal ──────────────────────────────────────────────────

def _available_codes() -> list[str]:
    codes = []
    for f in _I18N_DIR.glob("*.json"):
        name = f.stem
        if not name.startswith("_"):
            codes.append(name)
    return sorted(codes)


def _load_lang(code: str) -> dict:
    if code not in _translations:
        path = _I18N_DIR / f"{code}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        _translations[code] = data
    return _translations[code]


def _lookup(code: str, key: str) -> str | None:
    data = _load_lang(code)
    return data.get(key)
