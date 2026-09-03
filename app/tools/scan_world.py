"""Scan the server world save: guild, Pal dex, bases, positions, game time,
per-player inventory (gold + top items).

Run with the portable py312 interpreter; prints one JSON line to stdout.
Output keys: guilds, all_players, bases, player_locs, game_time, facts,
inventory
"""
import json
import os
import re
import sys
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "PalworldSaveTools-main", "src"))
sys.path.insert(0, os.path.join(_HERE, "PST"))
sys.path.insert(0, os.path.join(_HERE, "PST", "lib"))

sys.path.insert(0, r"E:\PalworldServer\app\tools\PalworldSaveTools-main\src")
sys.path.insert(0, r"E:\PalworldServer\app\tools\PST\lib")
sys.path.insert(0, r"E:\PalworldServer\app\tools\PST")

from palsav.io import load_sav

world = sys.argv[1]
lvl = load_sav(os.path.join(world, "Level.sav"))
wsd = lvl.properties["worldSaveData"]["value"]


def unwrap(x, depth=3):
    for _ in range(depth):
        if isinstance(x, dict):
            x = x.get("value")
        else:
            break
    return x


def as_int(x):
    try:
        return int(unwrap(x))
    except (TypeError, ValueError):
        return 1


def clean_species(raw):
    s = str(raw or "?")
    boss = s.startswith("BOSS_")
    s = re.sub(r"^BOSS_", "", s)
    s = re.sub(r"Pal$", "", s).replace("_", " ").strip()
    return ("★ " if boss else "") + s


level_by_uid, pals_by_uid, name_by_uid, dex_by_uid, loc_by_uid = {}, {}, {}, {}, {}
species_catalog = set()
for e in wsd.get("CharacterSaveParameterMap", {}).get("value", []):
    try:
        sp = e["value"]["RawData"]["value"]["object"]["SaveParameter"]
        if sp["struct_type"] != "PalIndividualCharacterSaveParameter":
            continue
        v = sp["value"]
        uid = str(e["key"]["PlayerUId"]["value"]).lower().replace("-", "")
        if v.get("IsPlayer", {}).get("value", False):
            level_by_uid[uid] = as_int(v.get("Level", 1))
            name_by_uid[uid] = str(unwrap(v.get("NickName")) or "?")
            ljl = unwrap(v.get("LastJumpedLocation"))
            if isinstance(ljl, dict):
                loc_by_uid[uid] = (ljl.get("x"), ljl.get("y"))
        else:
            raw_id = str(unwrap(v.get("CharacterID")) or "")
            if raw_id and "?" not in raw_id:
                species_catalog.add(raw_id)
            owner = str(unwrap(v.get("OwnerPlayerUId")) or "").lower().replace("-", "")
            if owner:
                pals_by_uid[owner] = pals_by_uid.get(owner, 0) + 1
                sp_name = clean_species(unwrap(v.get("CharacterID")))
                dex = dex_by_uid.setdefault(owner, {})
                dex[sp_name] = dex.get(sp_name, 0) + 1
    except Exception:
        continue


def top_pals(uid):
    dex = dex_by_uid.get(uid, {})
    return sorted(dex.items(), key=lambda kv: -kv[1])[:5]


real_tick = 0
try:
    real_tick = int(unwrap(wsd["GameTimeSaveData"]["value"]["RealDateTimeTicks"]) or 0)
except Exception:
    pass


def fmt_seen(last):
    if not last or not real_tick:
        return "unknown"
    diff = max(0, (real_tick - last) / 1e7)
    if diff >= 86400:
        return f"{int(diff // 86400)}d {int(diff % 86400 // 3600)}h ago"
    if diff >= 3600:
        return f"{int(diff // 3600)}h {int(diff % 3600 // 60)}m ago"
    return f"{int(diff // 60)}m ago"


def player_entry(uid):
    return {
        "uid": uid,
        "name": name_by_uid.get(uid, "?"),
        "level": level_by_uid.get(uid, 1),
        "pals": pals_by_uid.get(uid, 0),
        "top_pals": [[n, c] for n, c in top_pals(uid)],
    }


guilds = []
for g in wsd.get("GroupSaveDataMap", {}).get("value", []):
    if g["value"]["GroupType"]["value"]["value"] != "EPalGroupType::Guild":
        continue
    raw = g["value"]["RawData"]["value"]
    admin = str(raw.get("admin_player_uid", "")).lower().replace("-", "")
    members = []
    for p in raw.get("players", []):
        uid = str(p.get("player_uid", "")).lower().replace("-", "")
        info = p.get("player_info", {})
        entry = player_entry(uid)
        entry["name"] = info.get("player_name", entry["name"])
        entry["last_seen"] = fmt_seen(info.get("last_online_real_time", 0))
        entry["admin"] = uid == admin
        members.append(entry)
    members.sort(key=lambda m: (not m["admin"], -(m["level"] or 0)))
    guilds.append({"name": raw.get("guild_name", ""), "players": members})

all_players = []
players_dir = os.path.join(world, "Players")
if os.path.isdir(players_dir):
    for fn in os.listdir(players_dir):
        if fn.endswith(".sav") and not fn.endswith("_dps.sav"):
            uid = fn[:-4].lower().replace("-", "")
            if uid == "00000000000000000000000000000001":
                continue
            entry = player_entry(uid)
            entry["has_dps"] = os.path.isfile(
                os.path.join(players_dir, fn[:-4] + "_dps.sav"))
            all_players.append(entry)

bases = []
for bc in wsd.get("BaseCampSaveData", {}).get("value", []):
    try:
        raw = bc["value"]["RawData"]["value"]
        tr = raw["transform"]["translation"]
        bases.append({"name": str(raw.get("name") or "base"),
                      "x": round(float(tr["x"])), "y": round(float(tr["y"]))})
    except Exception:
        continue

player_locs = []
for uid, (x, y) in loc_by_uid.items():
    if x is None or y is None:
        continue
    player_locs.append({"name": name_by_uid.get(uid, "?"),
                        "x": round(float(x)), "y": round(float(y))})

game_time = {}
try:
    ticks = int(unwrap(wsd["GameTimeSaveData"]["value"]["GameDateTimeTicks"]))
    secs = ticks / 1e7
    game_time = {"day": int(secs // 86400) + 1,
                 "clock": f"{int(secs % 86400 // 3600):02d}:{int(secs % 3600 // 60):02d}"}
except Exception:
    pass

facts = {
    "pals_total": sum(pals_by_uid.values()),
    "containers": len(wsd.get("ItemContainerSaveData", {}).get("value", [])),
    "bases": len(bases),
}

# ---- per-player inventory: gold ("Money" item) + top stacked items -------
items_by_container = {}
item_totals = {}
for c in wsd.get("ItemContainerSaveData", {}).get("value", []):
    try:
        cid = str(c["key"]["ID"]["value"])
        agg = items_by_container.setdefault(cid, {})
        for el in (c["value"]["Slots"]["value"]["values"] or []):
            slot = ((el or {}).get("RawData") or {}).get("value") or {}
            sid = ((slot.get("item") or {}).get("static_id")) or ""
            if not sid:
                continue
            try:
                cnt = int(slot.get("count") or 0)
            except (TypeError, ValueError):
                cnt = 0
            agg[sid] = agg.get(sid, 0) + cnt
            if sid != "Money":
                item_totals[sid] = item_totals.get(sid, 0) + cnt
    except Exception:
        continue

item_catalog = [sid for sid, _n in sorted(item_totals.items(),
                                          key=lambda kv: -kv[1])[:40]]


def clean_item(sid):
    s = re.sub(r"^Item_", "", str(sid or "?"))
    s = re.sub(r"(?<!^)(?=[A-Z0-9])", " ", s) if "_" not in s else s.replace("_", " ")
    return s.strip()


def containers_of(sd):
    out = []
    inv = (sd.get("InventoryInfo") or {}).get("value") or {}
    for k, v in inv.items():
        if k.endswith("ContainerId"):
            try:
                out.append(str(v["value"]["ID"]["value"]))
            except Exception:
                continue
    return out


inventory = []
for p in all_players:
    entry = {"uid": p["uid"], "name": p["name"], "gold": 0,
             "top_items": []}
    try:
        psav = load_sav(os.path.join(players_dir, p["uid"] + ".sav"))
        sd = psav.properties["SaveData"]["value"]
        mine = {}
        for cid in containers_of(sd):
            for sid, cnt in items_by_container.get(cid, {}).items():
                mine[sid] = mine.get(sid, 0) + cnt
        entry["gold"] = mine.get("Money", 0)
        top = sorted(((k, v) for k, v in mine.items() if k != "Money"),
                     key=lambda kv: -kv[1])[:5]
        entry["top_items"] = [[clean_item(k), v] for k, v in top]
    except Exception:
        pass
    inventory.append(entry)

print(json.dumps({"guilds": guilds, "all_players": all_players,
                  "bases": bases, "player_locs": player_locs,
                  "game_time": game_time, "facts": facts,
                  "inventory": inventory,
                  "pal_catalog": sorted(species_catalog),
                  "item_catalog": item_catalog}))
