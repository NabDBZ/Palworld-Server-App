from __future__ import annotations
import os
import sys
from typing import Dict, Any
from palsav import json_tools

from resource_resolver import get_base_dir, get_resources_dir, get_user_config_dir
base_dir = get_base_dir()
_CFG: str = os.path.join(get_user_config_dir(), 'config.json')
_BUNDLED_CFG: str = os.path.join(base_dir, 'src', 'data', 'configs', 'config.json')
_RESOURCES_BASE: str = get_resources_dir()
if _RESOURCES_BASE not in sys.path:
    sys.path.insert(0, _RESOURCES_BASE)
_SUPPORTED_LANGS = ['en_US', 'zh_CN', 'ru_RU', 'fr_FR', 'es_ES', 'de_DE', 'ja_JP', 'ko_KR', 'pt_BR']
_cfg_path = _CFG if os.path.exists(_CFG) else _BUNDLED_CFG
try:
    _LANG: str = json_tools.load(_cfg_path).get('lang', 'en_US') if os.path.exists(_cfg_path) else 'en_US'
except Exception:
    _LANG: str = 'en_US'
_RES: Dict[str, Dict[str, str]] = {}
_loaded_langs: set = set()
def _load_json(path: str) -> Dict[str, Any]:
    try:
        return json_tools.load(path)
    except Exception:
        return {}
def _ensure_lang(lang: str) -> None:
    if lang not in _loaded_langs:
        _RES[lang] = _load_json(os.path.join(_RESOURCES_BASE, 'i18n', f'{lang}.json'))
        _loaded_langs.add(lang)
def load_resources(lang: str | None=None) -> None:
    global _RES, _LANG, _loaded_langs
    _loaded_langs.clear()
    for l in _SUPPORTED_LANGS:
        _RES[l] = _load_json(os.path.join(_RESOURCES_BASE, 'i18n', f'{l}.json'))
        _loaded_langs.add(l)
    if lang:
        _LANG = lang
def get_language() -> str:
    return _LANG
def set_language(lang: str) -> None:
    global _LANG
    if lang not in _SUPPORTED_LANGS:
        return
    _ensure_lang(lang)
    _LANG = lang
    try:
        os.makedirs(os.path.dirname(_CFG), exist_ok=True)
        cfg = _load_json(_CFG) if os.path.exists(_CFG) else {}
        cfg['lang'] = lang
        json_tools.dump(cfg, _CFG)
    except Exception:
        pass
def get_config_value(key: str, default: Any=None) -> Any:
    cfg_path = _CFG if os.path.exists(_CFG) else _BUNDLED_CFG
    if os.path.exists(cfg_path):
        cfg = _load_json(cfg_path)
        return cfg.get(key, default)
    return default


def set_config_value(key: str, value: Any) -> None:
    try:
        os.makedirs(os.path.dirname(_CFG), exist_ok=True)
        cfg = _load_json(_CFG) if os.path.exists(_CFG) else {}
        cfg[key] = value
        json_tools.dump(cfg, _CFG)
    except Exception:
        pass
def init_language(default_lang: str='zh_CN') -> None:
    global _RES, _LANG, _loaded_langs
    lang = default_lang
    cfg_path = _CFG if os.path.exists(_CFG) else _BUNDLED_CFG
    if os.path.exists(cfg_path):
        cfg = _load_json(cfg_path)
        lang = cfg.get('lang', default_lang)
    _ensure_lang(lang)
    _ensure_lang('en_US')
    _LANG = lang
_DEF = object()
def get_native_lang_name(code: str) -> str:
    _ensure_lang('en_US')
    return _RES.get('en_US', {}).get(f'lang.{code}', code)

def t(key: str, default: str | object=_DEF, **fmt) -> str:
    src = _RES.get(_LANG, {})
    fallback = _RES.get('en_US', {})
    text = src.get(key) or fallback.get(key)
    if text is None:
        text = key if default is _DEF else default
    try:
        return text.format(**fmt) if fmt else text
    except Exception:
        return text
__all__ = ['init_language', 't', 'set_language', 'get_language', 'load_resources', 'get_native_lang_name']