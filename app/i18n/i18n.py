from typing import Optional
from contextvars import ContextVar
from pathlib import Path

from babel.support import Translations

current_locale = ContextVar("current_locale", default="zh_CN")

_translations_cache: dict[str, Translations] = {}

def _get_translations(locale: str) -> Translations:
    if locale in _translations_cache:
        return _translations_cache[locale]
    
    locales_dir = Path(__file__).parent / "locales"
    try:
        translations = Translations.load(
            dirname=str(locales_dir),
            locales=[locale],
            domain="messages"
        )
    except Exception:
        translations = Translations()
    
    _translations_cache[locale] = translations
    return translations

def t(key: str, **kwargs) -> str:
    locale = current_locale.get()
    translations = _get_translations(locale)
    text = translations.gettext(key)
    if text == key:
        fallback_translations = _get_translations("zh_CN")
        text = fallback_translations.gettext(key)
    
    if kwargs:
        try:
            return text % kwargs
        except (TypeError, KeyError):
            return text
    return text

def set_locale(locale: str):
    if locale not in ["zh_CN", "en_US"]:
        locale = "zh_CN"
    current_locale.set(locale)

def get_current_locale() -> str:
    return current_locale.get()