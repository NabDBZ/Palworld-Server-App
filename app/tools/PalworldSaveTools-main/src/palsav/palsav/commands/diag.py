import argparse
import sys
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _load_sav(path):
    from palsav.io import load_sav
    return load_sav(path).dump()


def main():
    parser = argparse.ArgumentParser(
        prog="palsav diag",
        description="Read-only save file diagnostics.",
    )
    parser.add_argument("save_path", help="Path to Level.sav[.json] or Player .sav[.json]")
    parser.add_argument("--player-uid", default=None, help="Target player GUID for deep metrics")
    parser.add_argument(
        "--mode", choices=["summary", "players", "containers", "pals"], default="summary"
    )
    parser.add_argument("--raw", action="store_true", help="Show raw GVAS property paths")
    args = parser.parse_args()

    path = Path(args.save_path)
    if not path.exists():
        logger.error(f"File not found: {path}")
        sys.exit(1)

    if path.suffix == ".sav":
        data = _load_sav(path)
    else:
        import json
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

    world = data.get("properties", {}).get("worldSaveData", {}).get("value", {})
    header = data.get("header", {})

    if args.mode == "summary":
        _summary(header, world)
    elif args.mode == "players":
        _players(world, args.player_uid)
    elif args.mode == "containers":
        _containers(world)
    elif args.mode == "pals":
        if not args.player_uid:
            logger.error("Mode 'pals' requires --player-uid")
            sys.exit(1)
        _pals(world, args.player_uid)


def _get_val(prop, default=None):
    if not isinstance(prop, dict):
        if hasattr(prop, "hex") and hasattr(prop, "version"):  # UUID
            return str(prop)
        return default if prop is None else prop
    v = prop.get("value")
    if v is None:
        return default
    if isinstance(v, dict):
        return _get_val(v, v)
    if hasattr(v, "hex") and hasattr(v, "version"):  # UUID
        return str(v)
    return v


def _get_charmap(world):
    return world.get("CharacterSaveParameterMap", {}).get("value", [])


def _get_groupmap(world):
    return world.get("GroupSaveDataMap", {}).get("value", [])


def _get_containermap(world):
    return world.get("ItemContainerSaveData", {}).get("value", [])


def _get_charcontainer_map(world):
    return world.get("CharacterContainerSaveData", {}).get("value", [])


def _player_name(entry):
    sv = entry.get("value", {}).get("RawData", {}).get("value", {}).get("object", {}).get("SaveParameter", {}).get("value", {})
    return _get_val(sv.get("NickName"), "?")


def _is_player(entry):
    sv = entry.get("value", {}).get("RawData", {}).get("value", {}).get("object", {}).get("SaveParameter", {}).get("value", {})
    return _get_val(sv.get("IsPlayer"), False)


def _character_save_param(entry):
    return entry.get("value", {}).get("RawData", {}).get("value", {}).get("object", {}).get("SaveParameter", {}).get("value", {})


def _player_uid_from_key(entry):
    v = entry.get("key", {}).get("PlayerUId", {}).get("value", "")
    return str(v) if not isinstance(v, str) else v


def _instance_id_from_key(entry):
    v = entry.get("key", {}).get("InstanceId", {}).get("value", "")
    return str(v) if not isinstance(v, str) else v


def _find_player_entry(charmap, player_uid):
    for e in charmap:
        uid = _player_uid_from_key(e)
        if uid == player_uid and _is_player(e):
            return e
    return None


def _find_char_entry(charmap, instance_id):
    for e in charmap:
        if _instance_id_from_key(e) == instance_id:
            return e
    return None


def _summary(header, world):
    charmap = _get_charmap(world)
    groupmap = _get_groupmap(world)
    containermap = _get_containermap(world)
    charcontainermap = _get_charcontainer_map(world)

    players = sum(1 for e in charmap if _is_player(e))
    pals = len(charmap) - players
    guilds = sum(1 for e in groupmap if e.get("value", {}).get("GroupType", {}).get("value", {}).get("value") == "EPalGroupType::Guild")
    containers = len(containermap)
    char_containers = len(charcontainermap)
    total_slots = 0
    for c in containermap:
        slots = c.get("value", {}).get("SlotNum", {}).get("value", 0)
        total_slots += slots

    class_name = header.get("save_game_class_name", "?")

    print(f"Save Game Class    : {class_name}")
    print(f"Engine Version     : {header.get('engine_version_major', '?')}.{header.get('engine_version_minor', '?')}.{header.get('engine_version_patch', '?')}")
    print(f"Timestamp          : {header.get('Timestamp', {}).get('value', '?') if isinstance(header.get('Timestamp'), dict) else '?'}")
    print()
    print(f"Registered Players : {players}")
    print(f"Registered Pals    : {pals}")
    print(f"Total Characters   : {len(charmap)}")
    print(f"Guilds             : {guilds}")
    print(f"Organizations      : {len(groupmap) - guilds}")
    print(f"Item Containers    : {containers} ({total_slots} total slots)")
    print(f"Char Containers    : {char_containers}")


def _players(world, target_uid=None):
    charmap = _get_charmap(world)
    groupmap = _get_groupmap(world)

    uid_to_guild = {}
    for g in groupmap:
        group_val = g.get("value", {}).get("RawData", {}).get("value", {})
        gtype = group_val.get("group_type", "")
        if gtype != "EPalGroupType::Guild":
            continue
        guild_name = group_val.get("guild_name", "?")
        for p in group_val.get("players", []):
            puid = p.get("player_uid", "")
            if puid:
                uid_to_guild[puid] = guild_name

    rows = []
    for e in charmap:
        if not _is_player(e):
            continue
        sv = _character_save_param(e)
        uid = _player_uid_from_key(e)
        name = _get_val(sv.get("NickName"), "?")
        lv = _get_val(sv.get("Level"), "?")
        guild = uid_to_guild.get(uid, "")
        rows.append((name, uid, lv, guild))

    rows.sort(key=lambda r: r[0].lower())

    if not rows:
        print("No players found.")
        return

    print(f"{'Player Name':<22} {'UID':<36} {'Lv':<4} {'Guild':<22}")
    print("-" * 88)
    for name, uid, lv, guild in rows:
        if target_uid and uid != target_uid:
            continue
        print(f"{name:<22} {uid:<36} {lv:<4} {guild:<22}")
    print(f"\nTotal players: {len(rows) if not target_uid else 1}")


def _containers(world):
    containermap = _get_containermap(world)
    charmap = _get_charmap(world)
    charcontainermap = _get_charcontainer_map(world)

    if not containermap:
        print("No item containers found.")
        return

    print(f"{'Container ID (GUID)':<36} {'Type':<18} {'Slots':<6} {'Sample Items'}")
    print("-" * 96)

    for c in containermap:
        cid = str(c.get("key", {}).get("ID", {}).get("value", "?") or "?")
        slot_num = _get_val(c.get("value", {}).get("SlotNum"), 0)
        slots = c.get("value", {}).get("Slots", {}).get("value", {}).get("values", [])

        item_sample = ""
        seen = set()
        for s in slots:
            item_id = s.get("RawData", {}).get("value", {}).get("item", {}).get("static_id", "")
            if item_id and item_id not in seen:
                seen.add(item_id)
                if item_sample:
                    item_sample += ", "
                item_sample += item_id
                if len(seen) >= 3:
                    break
        if not item_sample:
            item_sample = "(empty)"

        print(f"{cid:<36} {'ItemContainer':<18} {slot_num:<6} {item_sample}")

    print()

    player_uid_to_name = {}
    for e in charmap:
        if _is_player(e):
            sv = _character_save_param(e)
            uid = _player_uid_from_key(e)
            name = sv.get("NickName", {}).get("value", "?")
            player_uid_to_name[uid] = name

    print(f"{'Container ID (GUID)':<36} {'Type':<18} {'Slots':<6} {'Owner'}")
    print("-" * 96)
    for cc in charcontainermap:
        cid = str(cc.get("key", {}).get("ID", {}).get("value", "?") or "?")
        slot_num = _get_val(cc.get("value", {}).get("SlotNum"), 0)
        print(f"{cid:<36} {'CharContainer':<18} {slot_num:<6} ") 
    print(f"\nTotal item containers: {len(containermap)}")
    print(f"Total char containers: {len(charcontainermap)}")


def _pals(world, player_uid):
    charmap = _get_charmap(world)
    groupmap = _get_groupmap(world)

    player_entry = _find_player_entry(charmap, player_uid)
    if not player_entry:
        logger.error(f"No player found with UID: {player_uid}")
        return

    instance_id = _instance_id_from_key(player_entry)
    player_name = _player_name(player_entry)

    groupmap_lookup = {}
    for g in groupmap:
        gv = g.get("value", {}).get("RawData", {}).get("value", {})
        gtype = gv.get("group_type", "")
        if gtype != "EPalGroupType::Guild":
            continue
        for p in gv.get("players", []):
            puid = p.get("player_uid", "")
            if puid:
                groupmap_lookup[puid] = gv

    guild_info = groupmap_lookup.get(player_uid, {})
    guild_name = guild_info.get("guild_name", "")

    print(f"Player: {player_name}  ({player_uid})")
    print(f"Guild : {guild_name}")
    print()

    party_container_id = None
    palbox_container_id = None

    player_json_dir = Path(__file__).parent.parent.parent / "pal-save" / "EntUpdated" / "Players"
    player_sav_path = player_json_dir / f"{player_uid}.sav"
    if player_sav_path.exists():
        pdata = _load_sav(player_sav_path)
        sd = pdata.get("properties", {}).get("SaveData", {}).get("value", {})
        party_container_id = str(sd.get("OtomoCharacterContainerId", {}).get("value", {}).get("ID", {}).get("value", "") or "")
        palbox_container_id = str(sd.get("PalStorageContainerId", {}).get("value", {}).get("ID", {}).get("value", "") or "")
    else:
        for e in charmap:
            if _is_player(e) and _player_uid_from_key(e) == player_uid:
                instance_id = _instance_id_from_key(e)
                break

    owner_uids = {player_uid, "00000000-0000-0000-0000-000000000000"}
    owned_pals = []
    for e in charmap:
        if _is_player(e):
            continue
        sv = _character_save_param(e)
        owner = str(sv.get("OwnerPlayerUId", {}).get("value", "") or "")
        if owner in owner_uids:
            owned_pals.append(e)

    owned_pals.sort(key=lambda e: int(_get_val(_character_save_param(e).get("Level"), 0) or 0), reverse=True)

    print(f"{'#':<3} {'Species':<16} {'NickName':<20} {'Lv':<4} {'Gender':<8} {'Container'}")
    print("-" * 80)
    for idx, pal in enumerate(owned_pals, 1):
        sv = _character_save_param(pal)
        species = _get_val(sv.get("CharacterID"), "?")
        nick = _get_val(sv.get("NickName"), "")
        lv = _get_val(sv.get("Level"), "?")
        gender = (_get_val(sv.get("Gender"), "?") or "?").replace("EPalGenderType::", "")
        container_id = sv.get("SlotId", {}).get("value", {}).get("ContainerId", {}).get("value", {}).get("ID", {}).get("value", "")
        container_label = "?"
        if container_id:
            container_id = str(container_id)
            if container_id == party_container_id:
                container_label = "Party"
            elif container_id == palbox_container_id:
                container_label = "PalBox"
            elif container_id:
                container_label = container_id[:8]
        print(f"{idx:<3} {species:<16} {nick:<20} {lv:<4} {gender:<8} {container_label}")

    print(f"\nTotal Pals owned: {len(owned_pals)}")


if __name__ == "__main__":
    main()
