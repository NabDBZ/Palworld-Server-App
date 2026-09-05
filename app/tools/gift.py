"""Apply gifts (gold, items, Pals) to a world save — no mods needed.

Usage: py312\\python.exe gift.py <world_dir> <payload_json_path>
Payload: {"gifts": [{
    "uid": "<32 hex player uid>",
    "gold": 0,
    "items": [["PalSphere", 10], ...],
    "pals": [{"id": "BOSS_CaptainPenguin", "lv": 40}, ...]
}]}
The server MUST be stopped. A .bak copy of Level.sav is made first.
Prints GIFT_OK <json summary> or GIFT_FAIL <message>.
"""
import copy
import json
import os
import shutil
import sys
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "PalworldSaveTools-main", "src"))
sys.path.insert(0, os.path.join(_HERE, "PST"))
sys.path.insert(0, os.path.join(_HERE, "PST", "lib"))
import uuid

# PST\lib must win for `palsav`: its compiled version writes Oodle (oozlib)
# like the proven migration path; the -main copy would write zlib.
sys.path.insert(0, r"E:\PalworldServer\app\tools\PalworldSaveTools-main\src")
sys.path.insert(0, r"E:\PalworldServer\app\tools\PST")
sys.path.insert(0, r"E:\PalworldServer\app\tools\PST\lib")

from palsav.io import load_sav, save_sav


def fmt_guid(uid32):
    u = uid32.lower().replace("-", "")
    return "{}-{}-{}-{}-{}".format(u[:8], u[8:12], u[12:16], u[16:20], u[20:])


def get_leaf(prop):
    node = prop
    while isinstance(node, dict) and isinstance(node.get("value"), dict):
        node = node["value"]
    return node.get("value") if isinstance(node, dict) else node


def set_leaf(prop, val):
    node = prop
    while isinstance(node, dict) and isinstance(node.get("value"), dict):
        node = node["value"]
    node["value"] = val


def slot_raw(el):
    return ((el or {}).get("RawData") or {}).get("value") or {}


def main():
    world, payload_path = sys.argv[1], sys.argv[2]
    with open(payload_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    level_path = os.path.join(world, "Level.sav")
    lvl = load_sav(level_path)
    wsd = lvl.properties["worldSaveData"]["value"]

    item_containers = {}
    for c in wsd.get("ItemContainerSaveData", {}).get("value", []):
        item_containers[str(c["key"]["ID"]["value"])] = c
    char_containers = {}
    for c in wsd.get("CharacterContainerSaveData", {}).get("value", []):
        char_containers[str(c["key"]["ID"]["value"])] = c

    summary = []

    for gift in payload.get("gifts", []):
        uid = gift.get("uid", "").lower().replace("-", "")
        pguid = fmt_guid(uid)
        psav = load_sav(os.path.join(world, "Players", uid + ".sav"))
        psd = psav.properties["SaveData"]["value"]
        inv = (psd.get("InventoryInfo") or {}).get("value") or {}
        my_item_ids = []
        for k, v in inv.items():
            if k.endswith("ContainerId"):
                my_item_ids.append(str(v["value"]["ID"]["value"]))
        storage_cid = str(psd["PalStorageContainerId"]["value"]["ID"]["value"])

        # --- gold: stack onto the existing Money slot, or append one ---
        gold = int(gift.get("gold") or 0)
        if gold:
            done = False
            for cid in my_item_ids:
                c = item_containers.get(cid)
                if not c:
                    continue
                vals = c["value"]["Slots"]["value"]["values"]
                for el in vals or []:
                    s = slot_raw(el)
                    if ((s.get("item") or {}).get("static_id")) == "Money":
                        s["count"] = s.get("count", 0) + gold
                        done = True
                        break
                if done:
                    break
            if not done:
                # append a fresh Money slot to the essentials container
                ess = None
                for cid in my_item_ids:
                    c = item_containers.get(cid)
                    if c and (c["value"]["Slots"]["value"]["values"] or []):
                        ess = c  # any usable container as donor/template
                        break
                if ess is None:
                    print("GIFT_FAIL no container to place gold for " + uid)
                    sys.exit(1)
                vals = ess["value"]["Slots"]["value"]["values"]
                donor = copy.deepcopy(vals[0])
                s = slot_raw(donor)
                s["slot_index"] = max(
                    (slot_raw(e).get("slot_index", -1) for e in vals),
                    default=-1) + 1
                s["count"] = gold
                s["item"]["static_id"] = "Money"
                s["item"]["dynamic_id"]["created_world_id"] = \
                    "00000000-0000-0000-0000-000000000000"
                s["item"]["dynamic_id"]["local_id_in_created_world"] = \
                    "00000000-0000-0000-0000-000000000000"
                s["trailing_bytes"] = [0] * 20
                vals.append(donor)

        # --- items: stack or append in the common (inventory) container ---
        common_cid = str(inv.get("CommonContainerId", {})
                         .get("value", {}).get("ID", {}).get("value", ""))
        for static_id, count in gift.get("items") or []:
            c = item_containers.get(common_cid)
            if not c:
                print("GIFT_FAIL no inventory container for " + uid)
                sys.exit(1)
            vals = c["value"]["Slots"]["value"]["values"]
            stacked = False
            for el in vals or []:
                s = slot_raw(el)
                if ((s.get("item") or {}).get("static_id")) == static_id:
                    s["count"] = s.get("count", 0) + int(count)
                    stacked = True
                    break
            if not stacked and vals:
                donor = copy.deepcopy(vals[0])
                s = slot_raw(donor)
                s["slot_index"] = max(
                    (slot_raw(e).get("slot_index", -1) for e in vals),
                    default=-1) + 1
                s["count"] = int(count)
                s["item"]["static_id"] = static_id
                s["item"]["dynamic_id"]["created_world_id"] = \
                    "00000000-0000-0000-0000-000000000000"
                s["item"]["dynamic_id"]["local_id_in_created_world"] = \
                    "00000000-0000-0000-0000-000000000000"
                s["trailing_bytes"] = [0] * 20
                vals.append(donor)

        # --- pals: clone one of the player's own pals, retarget species/level.
        # Box membership = a slot in the player's PalStorage CharacterContainer
        # referencing the pal's InstanceId (SlotId inside SaveParameter is
        # empty in 1.0 saves and slot player_uid is always the template GUID).
        for spec in gift.get("pals") or []:
            sc = char_containers.get(storage_cid)
            if sc is None:
                print("GIFT_FAIL no pal storage container for " + uid)
                sys.exit(1)
            svals = sc["value"]["Slots"]["value"]["values"] or []
            donor_entry = None
            for e in wsd["CharacterSaveParameterMap"]["value"]:
                try:
                    sp = e["value"]["RawData"]["value"]["object"]["SaveParameter"]
                    if sp["struct_type"] != "PalIndividualCharacterSaveParameter":
                        continue
                    v = sp["value"]
                    if v.get("IsPlayer", {}).get("value", False):
                        continue
                    if str(get_leaf(v.get("OwnerPlayerUId")) or "").lower() \
                            .replace("-", "") != uid:
                        continue
                    donor_entry = e
                    break
                except Exception:
                    continue
            if donor_entry is None or not svals:
                print("GIFT_FAIL no donor pal / storage slots for " + uid)
                sys.exit(1)

            new_slot = copy.deepcopy(svals[-1])
            inst = str(uuid.uuid4())
            new_slot["RawData"]["value"]["instance_id"] = inst
            svals.append(new_slot)

            entry = copy.deepcopy(donor_entry)
            entry["key"]["InstanceId"]["value"] = inst
            v = entry["value"]["RawData"]["value"]["object"]["SaveParameter"]["value"]
            if isinstance(v.get("CharacterID"), dict):
                set_leaf(v["CharacterID"], spec.get("id", "PalLamball"))
            else:
                v["CharacterID"] = spec.get("id", "PalLamball")
            if spec.get("lv"):
                set_leaf(v["Level"], int(spec["lv"]))
            wsd["CharacterSaveParameterMap"]["value"].append(entry)

            # extra copies of the same species ("n" > 1): each gets its own
            # fresh InstanceId + storage slot — never share identities
            for _n in range(int(spec.get("n") or 1) - 1):
                inst2 = str(uuid.uuid4())
                slot2 = copy.deepcopy(new_slot)
                slot2["RawData"]["value"]["instance_id"] = inst2
                svals.append(slot2)
                entry2 = copy.deepcopy(entry)
                entry2["key"]["InstanceId"]["value"] = inst2
                wsd["CharacterSaveParameterMap"]["value"].append(entry2)

        summary.append({"uid": uid, "gold": gold,
                        "items": gift.get("items") or [],
                        "pals": ["%s x%d" % (p.get("id"), int(p.get("n") or 1))
                                 for p in gift.get("pals") or []]})

    # safety copy, then write
    shutil.copy2(level_path, level_path + ".giftbak")
    # PST palsav SaveType enum: CNK=0x30, PLM(palooz/Oodle)=0x31, PLZ(zlib)=0x32
    # — the world save MUST be written Oodle (0x31), matching the original.
    save_sav(lvl, level_path, save_type=0x31)

    # post-write verification: the new file must still parse
    check = load_sav(level_path)
    n = len(check.properties["worldSaveData"]["value"]
            ["CharacterSaveParameterMap"]["value"])
    print("GIFT_OK " + json.dumps({"summary": summary,
                                   "characters": n}))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print("GIFT_FAIL " + str(e)[:200])
        sys.exit(1)
