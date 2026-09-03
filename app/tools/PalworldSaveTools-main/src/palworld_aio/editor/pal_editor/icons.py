import os
import re
import threading
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QPainter, QColor

from palsav import json_tools
from palworld_aio import constants
from resource_resolver import resource_path
from palworld_aio.utils import extract_value, safe_nested_get

from . import data as _data
from .data import (
    _ensure_element_data,
    _ensure_passive_data,
    _ensure_append_text_data,
    _ensure_ui_icons_data,
    get_pal_base_data,
    _PREFIX_LABELS,
)

_ICON_CACHE = {}
_PIXMAP_CACHE = {}
_CACHE_LOCK = threading.Lock()
_PAL_ICON_LOOKUP = None
_PAL_ICON_LOOKUP_NPC = None

def _ensure_pal_icon_lookup():
    global _PAL_ICON_LOOKUP, _PAL_ICON_LOOKUP_NPC
    if _PAL_ICON_LOOKUP is not None:
        return
    _PAL_ICON_LOOKUP = {}
    _PAL_ICON_LOOKUP_NPC = {}
    base_dir = constants.get_base_path()
    try:
        paldata_path = resource_path(base_dir, 'game_data', 'characters.json')
        paldata = json_tools.load(paldata_path)
        for pal in paldata.get('pals', []):
            asset = pal.get('asset', '').lower()
            icon = pal.get('icon', '')
            if asset and icon:
                _PAL_ICON_LOOKUP[asset] = resource_path(base_dir, 'game_data', icon.lstrip('/'))
    except Exception:
        pass
    try:
        npcdata_path = resource_path(base_dir, 'game_data', 'characters.json')
        npcdata = json_tools.load(npcdata_path)
        for npc in npcdata.get('npcs', []):
            asset = npc.get('asset', '').lower()
            icon = npc.get('icon', '')
            if asset and icon:
                _PAL_ICON_LOOKUP_NPC[asset] = resource_path(base_dir, 'game_data', icon.lstrip('/'))
    except Exception:
        pass

def _lookup_icon_in_data(asset_name: str, base_dir: str) -> str | None:
    _ensure_pal_icon_lookup()
    path = _PAL_ICON_LOOKUP.get(asset_name.lower())
    if path and os.path.exists(path):
        return path
    path = _PAL_ICON_LOOKUP_NPC.get(asset_name.lower())
    if path and os.path.exists(path):
        return path
    return None

def _get_pal_icon_path(character_id):
    base_dir = constants.get_base_path()
    cid_lower = character_id.lower()
    with _CACHE_LOCK:
        if cid_lower in _ICON_CACHE:
            return _ICON_CACHE[cid_lower]
    icon_path = _lookup_icon_in_data(cid_lower, base_dir)
    if not icon_path or not os.path.exists(icon_path):
        cid_stripped = cid_lower.replace('boss_', '').replace('b_o_s_s_', '')
        if cid_stripped != cid_lower:
            icon_path = _lookup_icon_in_data(cid_stripped, base_dir)
    if not icon_path or not os.path.exists(icon_path):
        cid_for_guess = cid_lower.replace('boss_', '').replace('b_o_s_s_', '')
        icon_path = resource_path(base_dir, 'game_data', 'icons', 'pals', f'{cid_for_guess}.webp')
        if not os.path.exists(icon_path):
            icon_path = resource_path(base_dir, 'game_data', 'icons', 'T_icon_unknown.webp')
    with _CACHE_LOCK:
        _ICON_CACHE[cid_lower] = icon_path
    return icon_path

def _get_cached_pixmap(icon_path, size=64):
    if not icon_path or not os.path.exists(icon_path):
        return None
    pixmap_key = f'{icon_path}_{size}x{size}'
    with _CACHE_LOCK:
        cached = _PIXMAP_CACHE.get(pixmap_key)
        if cached is not None:
            return cached
    pixmap = QPixmap(icon_path)
    if pixmap.isNull():
        return None
    scaled = pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    if scaled.isNull():
        return None
    with _CACHE_LOCK:
        _PIXMAP_CACHE[pixmap_key] = scaled
    return scaled

def _get_element_pixmap(element_name, variant='small', size=16):
    if not element_name:
        return None
    data = _ensure_element_data()
    entry = data.get(element_name.lower(), {})
    icons = entry.get('icons', {})
    icon_rel = icons.get(variant, '')
    if not icon_rel:
        return None
    base_dir = constants.get_base_path()
    full_path = resource_path(base_dir, 'game_data', icon_rel.lstrip('/'))
    if not os.path.exists(full_path):
        webp_path = os.path.splitext(full_path)[0] + '.webp'
        if os.path.exists(webp_path):
            full_path = webp_path
    return _get_cached_pixmap(full_path, size)

def _resolve_partner_desc(desc_raw, p_list, condenser_rank=0, active_main_values=None, active_overwrite_effect=None, default_passives=None, reference_passives=None):
    if not desc_raw:
        return ''
    _ensure_passive_data()
    star_count = max(0, condenser_rank - 1)
    def _make_effect_resolver(p_src, use_default=False):
        def _resolve(m):
            prefix_num = m.group(1)
            eff_num = m.group(2)
            idx = int(prefix_num) - 1
            p_val = None
            if use_default and default_passives and idx < len(default_passives):
                p_val = default_passives[idx]
            elif p_src and idx < len(p_src) and p_src[idx]:
                p_val = p_src[idx]
                if isinstance(p_val, dict):
                    p_val = p_val.get('value', '')
            if p_val:
                p_clean = str(p_val).lower()
                if p_clean:
                    p_info = _data._PASSIVE_DATA.get(p_clean, {})
                    rank_variant = min(star_count + 1, 5)
                    if rank_variant > 1:
                        variant_key = re.sub(r'\d+', str(rank_variant), p_clean, count=1)
                        variant_info = _data._PASSIVE_DATA.get(variant_key.lower(), {})
                        if isinstance(variant_info, dict) and variant_info.get(f'effect{eff_num}', None) is not None:
                            p_info = variant_info
                    if isinstance(p_info, dict):
                        ev = p_info.get(f'effect{eff_num}', None)
                        if ev is not None:
                            if isinstance(ev, float) and ev == int(ev):
                                return str(int(ev))
                            return str(ev)
            return '?'
        return _resolve
    def _resolve_ranked_value(values):
        if values:
            idx = min(star_count, len(values) - 1)
            if idx >= 0:
                v = values[idx]
                if isinstance(v, float) and v == int(v):
                    return str(int(v))
                return f'{v:.1f}'
        return '?'
    def _resolve_main_value(m):
        return _resolve_ranked_value(active_main_values)
    def _resolve_overwrite_effect(m):
        return _resolve_ranked_value(active_overwrite_effect)
    def _resolve_refmsgid(m):
        msg_id = m.group(1)
        rank = min(star_count + 1, 5)
        key = f'{msg_id}_Rank_{rank}'
        append_data = _ensure_append_text_data()
        text = append_data.get(key.lower(), '')
        if text:
            text = re.sub('<Status_Up>([^<]*)</>', '\\1', text)
            text = re.sub('<[^>]+>', '', text)
            return text
        return ''
    ref_src = reference_passives if reference_passives else p_list
    desc = re.sub('\\{Passive(\\d+)_EffectValue(\\d+)\\}', _make_effect_resolver(p_list, use_default=True), desc_raw)
    desc = re.sub('\\{ReferencePassive(\\d+)_EffectValue(\\d+)\\}', _make_effect_resolver(ref_src, use_default=False), desc)
    desc = re.sub('\\{ActiveSkillMainValueByRank\\}', _resolve_main_value, desc)
    desc = re.sub('\\{ActiveSkillOverWriteEffectTime\\}', _resolve_overwrite_effect, desc)
    desc = re.sub('\\{ReferenceMsgId_(\\w+)\\}', _resolve_refmsgid, desc)
    return desc

def _partner_desc_to_html(desc, elem_colors_map, tooltip=False):
    if not desc:
        return ''
    def _elem_icon_html(m):
        full_id = m.group(1)
        elem_name = full_id.replace('ElemIcon_', '')
        _ELEM_ICON_TO_NAME = {'ground': 'earth', 'electric': 'electricity', 'neutral': 'normal', 'grass': 'leaf'}
        lookup_name = _ELEM_ICON_TO_NAME.get(elem_name.lower(), elem_name.lower())
        data = _ensure_element_data()
        entry = data.get(lookup_name, {})
        icons = entry.get('icons', {})
        icon_rel = icons.get('small', '')
        if icon_rel:
            base_dir = constants.get_base_path()
            full_path = resource_path(base_dir, 'game_data', icon_rel.lstrip('/'))
            if not os.path.exists(full_path):
                webp_path = os.path.splitext(full_path)[0] + '.webp'
                if os.path.exists(webp_path):
                    full_path = webp_path
            file_url = 'file:///' + full_path.replace('\\', '/')
            return f'<img src="{file_url}" width="16" height="16" style="vertical-align:middle; margin:0 1px;">'
        return ''
    def _elem_name_html(m):
        elem = m.group(1)
        color = elem_colors_map.get(elem, '#9CA3AF')
        return f'<span style="color:{color};font-weight:600;">{elem}</span>'
    def _effect_name_html(m):
        effect = m.group(1)
        return f'<span style="color:#FBBF24;font-weight:600;">{effect}</span>'
    desc = re.sub('\\[ICON:([^\\]]+)\\]', _elem_icon_html, desc)
    desc = re.sub('\\[ELEM:([^\\]]+)\\]', _elem_name_html, desc)
    desc = re.sub('\\[EFFECT:([^\\]]+)\\]', _effect_name_html, desc)
    if tooltip:
        return desc
    return f'<div style="color:#9CA3AF;font-size:8px;line-height:1.4;">{desc}</div>'

def _clean_desc_for_tooltip(desc, passives=None, reference_passives=None):
    if not desc:
        return desc
    if passives is not None:
        _ensure_passive_data()
        def _make_effect_resolver(p_src):
            def _resolve(m):
                prefix_num = m.group(1)
                eff_num = m.group(2)
                idx = int(prefix_num) - 1
                if p_src and idx < len(p_src) and p_src[idx]:
                    p_val = p_src[idx]
                    p_clean = str(p_val).lower() if p_val else ''
                    if p_clean:
                        p_info = _data._PASSIVE_DATA.get(p_clean, {})
                        if isinstance(p_info, dict):
                            ev = p_info.get(f'effect{eff_num}', None)
                            if ev is not None:
                                if isinstance(ev, float) and ev == int(ev):
                                    return str(int(ev))
                                return str(ev)
                return '?'
            return _resolve
        ref_src = reference_passives if reference_passives else passives
        desc = re.sub('\\{Passive(\\d+)_EffectValue(\\d+)\\}', _make_effect_resolver(passives), desc)
        desc = re.sub('\\{ReferencePassive(\\d+)_EffectValue(\\d+)\\}', _make_effect_resolver(ref_src), desc)
        desc = re.sub('\\{ActiveSkillMainValueByRank\\}', '?', desc)
        desc = re.sub('\\{ActiveSkillOverWriteEffectTime\\}', '?', desc)
    else:
        desc = re.sub('\\{Passive\\d+_EffectValue\\d+\\}', '?', desc)
        desc = re.sub('\\{ReferencePassive\\d+_EffectValue\\d+\\}', '?', desc)
        desc = re.sub('\\{ActiveSkillMainValueByRank\\}', '?', desc)
        desc = re.sub('\\{ActiveSkillOverWriteEffectTime\\}', '?', desc)
    def _resolve_refmsgid_clean(m):
        msg_id = m.group(1)
        append_data = _ensure_append_text_data()
        text = append_data.get(f'{msg_id.lower()}_rank_1', '')
        if text:
            text = re.sub('<Status_Up>([^<]*)</>', '\\1', text)
            text = re.sub('<[^>]+>', '', text)
            return text
        return ''
    desc = re.sub('\\{ReferenceMsgId_(\\w+)\\}', _resolve_refmsgid_clean, desc)
    desc = re.sub('\\s+', ' ', desc).strip()
    desc = re.sub('\\[ICON:[^\\]]+\\]', '', desc)
    desc = re.sub('\\[ELEM:([^\\]]+)\\]', '\\1', desc)
    desc = re.sub('\\[EFFECT:([^\\]]+)\\]', '\\1', desc)
    return desc

def _get_boss_alpha_pixmap(size=14):
    base_dir = constants.get_base_path()
    path = resource_path(base_dir, 'boss_alpha.webp')
    return _get_cached_pixmap(path, size)

def _get_boss_shiny_pixmap(size=14):
    base_dir = constants.get_base_path()
    path = resource_path(base_dir, 'boss_shiny.webp')
    return _get_cached_pixmap(path, size)

def _get_awake_pixmap(size=14):
    base_dir = constants.get_base_path()
    path = resource_path(base_dir, 'UI', 'pst_flame_icon.webp')
    return _get_cached_pixmap(path, size)

def _strip_prefix_label(name: str) -> str:
    for label in _PREFIX_LABELS:
        if name.endswith(label):
            return name[:-len(label)]
    return name

def _composite_badge(pixmap, badge_pixmap, icon_size):
    result = QPixmap(pixmap)
    painter = QPainter(result)
    bw = badge_pixmap.width()
    bh = badge_pixmap.height()
    painter.drawPixmap(2, 2, badge_pixmap)
    painter.end()
    return result

def _get_ui_icon_pixmap(icon_key, size=16):
    data = _ensure_ui_icons_data()
    icon_path = data.get(icon_key, '')
    if not icon_path:
        return None
    return _get_cached_pixmap(icon_path, size)
