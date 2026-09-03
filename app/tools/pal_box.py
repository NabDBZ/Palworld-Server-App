"""Dump one player's Pal box: species, level, boss flag, passives.

Usage: py312\\python.exe pal_box.py <world_dir> <uid32>
Prints one JSON line: {"pals": [{"sp": .., "lv": .., "boss": .., "p": [..]}]}
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

world, uid = sys.argv[1], sys.argv[2].lower().replace("-", "")


def unwrap(x, depth=3):
    for _ in range(depth):
        if isinstance(x, dict):
            x = x.get("value")
        else:
            break
    return x


def clean_species(raw):
    s = str(raw or "?")
    boss = s.startswith("BOSS_")
    s = re.sub(r"^BOSS_", "", s)
    s = re.sub(r"Pal$", "", s).replace("_", " ").strip()
    return s, boss


def clean_passive(pid):
    s = str(pid or "")
    s = re.sub(r"^PAL_PASSIVE_", "", s)
    s = re.sub(r"^W_", "", s)
    return re.sub(r"(?<!^)(?=[A-Z])", " ", s).strip()


lvl = load_sav(os.path.join(world, "Level.sav"))
wsd = lvl.properties["worldSaveData"]["value"]
pals = []
for e in wsd.get("CharacterSaveParameterMap", {}).get("value", []):
    try:
        sp = e["value"]["RawData"]["value"]["object"]["SaveParameter"]
        if sp["struct_type"] != "PalIndividualCharacterSaveParameter":
            continue
        v = sp["value"]
        if v.get("IsPlayer", {}).get("value", False):
            continue
        owner = str(unwrap(v.get("OwnerPlayerUId")) or "").lower().replace("-", "")
        if owner != uid:
            continue
        name, boss = clean_species(unwrap(v.get("CharacterID")))
        try:
            lv = int(unwrap(v.get("Level")) or 1)
        except (TypeError, ValueError):
            lv = 1
        pl = v.get("PassiveSkillList", {}).get("value")
        if isinstance(pl, dict):
            pl = pl.get("values", [])
        passives = [clean_passive(p) for p in (pl or []) if p]
        pals.append({"sp": name, "lv": lv, "boss": boss,
                     "p": [x for x in passives if x][:4]})
    except Exception:
        continue

pals.sort(key=lambda x: (not x["boss"], -x["lv"]))
print(json.dumps({"pals": pals[:600]}))
