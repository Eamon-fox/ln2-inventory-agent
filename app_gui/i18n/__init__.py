"""Internationalization (i18n) module for LN2 Inventory Agent.

Usage:
    from app_gui.i18n import tr, set_language, get_language

    label = QLabel(tr("settings.title"))
    set_language("zh-CN")
"""

import json
import os
from functools import lru_cache

_LOCALE_DIR = os.path.join(os.path.dirname(__file__), "translations")
_CURRENT_LANG = "en"
_TRANSLATIONS = {}

SUPPORTED_LANGUAGES = {
    "en": "English",
    "zh-CN": "简体中文",
}


def _load_translations(lang: str) -> dict:
    """Load translation file for given language."""
    path = os.path.join(_LOCALE_DIR, f"{lang}.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def set_language(lang: str) -> bool:
    """Set current language. Returns True if successful."""
    global _CURRENT_LANG, _TRANSLATIONS
    if lang not in SUPPORTED_LANGUAGES:
        return False
    _CURRENT_LANG = lang
    _TRANSLATIONS = _load_translations(lang)
    return True


def get_language() -> str:
    """Get current language code."""
    return _CURRENT_LANG


def tr(key: str, default: str = None) -> str:
    """Translate a key to current language.

    Args:
        key: Translation key (dot-separated, e.g., "settings.title")
        default: Default text if key not found (defaults to key itself)

    Returns:
        Translated string or default/key
    """
    if default is None:
        default = key

    parts = key.split(".")
    value = _TRANSLATIONS
    for part in parts:
        if not isinstance(value, dict):
            return default
        value = value.get(part)
    if value is None or isinstance(value, dict):
        return default
    return str(value)


def t(key: str, **kwargs) -> str:
    """Translate with string formatting.

    Args:
        key: Translation key
        **kwargs: Format arguments

    Returns:
        Formatted translated string
    """
    text = tr(key)
    try:
        return text.format(**kwargs)
    except (KeyError, ValueError):
        return text
