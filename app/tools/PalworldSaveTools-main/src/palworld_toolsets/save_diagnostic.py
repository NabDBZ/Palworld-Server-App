#!/usr/bin/env python3
"""
Save Diagnostic — scans a decoded Level.json for structural anomalies,
orphaned players, and other signs of a modded, corrupted, or otherwise
unusual save that is still technically parseable.

Usage:
    uv run python src/palworld_toolsets/save_diagnostic.py <path-to-Level.json>

Exit codes:
    0  — no anomalies found
    1  — warnings found (save likely modded / partially broken)
    2  — error (file not found, unparseable, etc.)
"""

import json
import os
import sys


# ── helpers ──────────────────────────────────────────────────────────────

def warn(label: str, message: str):
    """Print a structured warning line."""
    print(f"  ⚠  [{label}] {message}")


def good(label: str, message: str):
    """Print a positive finding."""
    print(f"  ✓  [{label}] {message}")


def err(label: str, message: str):
    """Print a non-fatal error finding."""
    print(f"  ✗  [{label}] {message}")


# ── checks ───────────────────────────────────────────────────────────────

def check_guild_data(wsd: dict) -> list:
    """Analyse GroupSaveDataMap for unusual guild states."""
    warnings = []
    guilds = wsd.get('GroupSaveDataMap', {}).get('value', [])
    good('Guilds', f'{len(guilds)} group entries total')

    guild_count = 0
    for i, g in enumerate(guilds):
        val = g.get('value', {})
        gtype = val.get('GroupType', {}).get('value', {}).get('value', 'UNKNOWN')
        if gtype != 'EPalGroupType::Guild':
            continue
        guild_count += 1
        raw = val.get('RawData', {}).get('value', {})
        name = raw.get('guild_name', '(unnamed)')
        admin = raw.get('admin_player_uid')
        players = raw.get('players', [])
        if not players:
            warn('Guild', f"Guild #{i} '{name}' has 0 players in its roster "
                          f"(admin_uid={admin}) — empty guild artifact")
            warnings.append(f"empty_guild:{i}:{name}")

    if guild_count == 0:
        warn('Guilds', 'No Guild-type groups found at all — save may have no '
                       'player guild structure')
        warnings.append('no_guilds')

    return warnings


def check_orphaned_players(wsd: dict) -> list:
    """
    Find player characters (IsPlayer=true) that exist in
    CharacterSaveParameterMap but have no entry in any guild's players[]
    array.  These are fully orphaned — their save data remains but they
    are not a member of any guild.
    """
    warnings = []

    # Collect all player UIDs from guild rosters
    guild_player_uids = set()
    guilds = wsd.get('GroupSaveDataMap', {}).get('value', [])
    for g in guilds:
        val = g.get('value', {})
        gtype = val.get('GroupType', {}).get('value', {}).get('value', '')
        if gtype != 'EPalGroupType::Guild':
            continue
        players = val.get('RawData', {}).get('value', {}).get('players', [])
        for p in players:
            uid = p.get('player_uid')
            if uid:
                guild_player_uids.add(str(uid).replace('-', '').lower())

    # Also gather admin_player_uids (they might own a guild but not
    # appear in its players[] if the roster is buggy)
    admin_player_uids = set()
    for g in guilds:
        val = g.get('value', {})
        gtype = val.get('GroupType', {}).get('value', {}).get('value', '')
        if gtype != 'EPalGroupType::Guild':
            continue
        admin = val.get('RawData', {}).get('value', {}).get('admin_player_uid')
        if admin:
            admin_player_uids.add(str(admin).replace('-', '').lower())

    # Scan character save parameters for players
    char_map = wsd.get('CharacterSaveParameterMap', {}).get('value', [])
    total_player_chars = 0
    orphaned = []
    for entry in char_map:
        try:
            sp = entry['value']['RawData']['value']['object']['SaveParameter']
            if sp['struct_type'] != 'PalIndividualCharacterSaveParameter':
                continue
            sp_val = sp['value']
            if not sp_val.get('IsPlayer', {}).get('value', False):
                continue
            total_player_chars += 1

            key = entry.get('key', {})
            uid_obj = key.get('PlayerUId', {})
            uid = str(uid_obj.get('value', '') if isinstance(uid_obj, dict) else uid_obj)
            if not uid:
                continue
            clean = uid.replace('-', '').lower()
            nick = sp_val.get('NickName', {}).get('value', '(no nickname)')
            level = sp_val.get('Level', {}).get('value', {}).get('value', 1)

            in_guild = clean in guild_player_uids
            is_admin = clean in admin_player_uids

            if not in_guild and not is_admin:
                orphaned.append((uid, nick, level))
            elif not in_guild and is_admin:
                warn(
                    'Player',
                    f"'{nick}' (UID {uid}) is an admin of a guild but is "
                    f"missing from its players[] roster — guild roster "
                    f"corruption"
                )
        except (KeyError, TypeError):
            continue

    good('Players', f'{total_player_chars} player character(s) in '
                    f'CharacterSaveParameterMap')

    for uid, nick, level in orphaned:
        warn(
            'Orphaned Player',
            f"'{nick}' (UID {uid}, Lv.{level}) has character data with "
            f"IsPlayer=true but is NOT a member of any guild — "
            f"likely a modded / broken save artifact. "
            f"The player's data is present and parseable but they will "
            f"not show up in the roster."
        )
        warnings.append(f'orphaned_player:{uid}:{nick}')

    return warnings


def check_character_integrity(wsd: dict) -> list:
    """Quick sanity checks on CharacterSaveParameterMap."""
    warnings = []
    char_map = wsd.get('CharacterSaveParameterMap', {}).get('value', [])
    total = len(char_map)
    if total == 0:
        err('Characters', 'CharacterSaveParameterMap is empty — no characters?')
        warnings.append('empty_character_map')
        return warnings
    good('Characters', f'{total} total entries in CharacterSaveParameterMap')

    # Check for entries that lack the expected structure
    broken = 0
    for entry in char_map:
        try:
            _ = entry['value']['RawData']['value']['object']['SaveParameter']
        except (KeyError, TypeError):
            broken += 1

    if broken:
        err('Characters', f'{broken}/{total} entries are structurally broken '
                          f'(missing SaveParameter path)')
        warnings.append(f'broken_character_entries:{broken}')
    else:
        good('Characters', 'All entries have valid structure')

    return warnings


def check_time_data(wsd: dict):
    """Check GameTimeSaveData for sanity."""
    try:
        tick = wsd['GameTimeSaveData']['value']['RealDateTimeTicks']['value']
        # .NET ticks: 100-nanosecond intervals since 1/1/0001
        # Rough sanity: Palworld launched ~2024, ticks ~638400000000000000
        if tick < 630000000000000000:
            warn('Time', f'GameTime ticks ({tick}) are unusually low — '
                         f'timestamps may be inaccurate')
            return ['unusual_game_time']
    except (KeyError, TypeError):
        err('Time', 'GameTimeSaveData missing or malformed')
        return ['missing_game_time']
    return []


# ── main ─────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(f'Usage: uv run python {sys.argv[0]} <path-to-Level.json>')
        sys.exit(2)

    path = sys.argv[1]
    if not os.path.isfile(path):
        print(f'Error: file not found — {path}')
        sys.exit(2)

    print(f'🔍 Save Diagnostic — {path}')
    print(f'   Scanning for structural anomalies...\n')

    # Load
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f'Error: could not parse JSON — {e}')
        sys.exit(2)

    wsd = data.get('properties', {}).get('worldSaveData', {}).get('value')
    if wsd is None:
        print('Error: worldSaveData not found in Level.json structure')
        sys.exit(2)

    header = data.get('header', {})
    print(f'   Save version: UE5.{header.get("engine_version_major", "?")}'
          f'.{header.get("engine_version_minor", "?")}'
          f'.{header.get("engine_version_patch", "?")}')
    print(f'   GameVersion: {header.get("package_file_version_ue5", "?")}')
    print()

    all_warnings = []
    all_warnings += check_guild_data(wsd)
    all_warnings += check_character_integrity(wsd)
    all_warnings += check_orphaned_players(wsd)
    all_warnings += check_time_data(wsd)

    print()
    if all_warnings:
        print(f'┄{"─" * 60}')
        print(f'📋 Summary: {len(all_warnings)} anomaly(ies) detected.')
        print(f'   The save is parseable, but the issues above suggest it')
        print(f'   may have been modified by external tools, corrupted, or')
        print(f'   left behind after a server/guild reset.')
        print(f'   Use the data with caution.')
        sys.exit(1)
    else:
        print(f'✅ No anomalies detected — save looks structurally sound.')
        sys.exit(0)


if __name__ == '__main__':
    main()
