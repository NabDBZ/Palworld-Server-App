import unittest
import json
import os
import sys
import tempfile
from pathlib import Path

from palsav.commands.convert import convert_sav_to_json, convert_json_to_sav


def get_save_dir():
    env = os.environ.get("PST_SAVE_DIR")
    if env:
        return Path(env)
    return Path(__file__).parent.parent.parent.parent.parent / "pal-save" / "EntUpdated"


class TestPalworldSaveRoundTrip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = get_save_dir()
        cls.level_sav = cls.workspace / "Level.sav"
        cls.localdata_sav = cls.workspace / "LocalData.sav"
        cls.player_dir = cls.workspace / "Players"

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def _roundtrip(self, sav_path):
        json_path = os.path.join(self.tmpdir, "output.json")
        convert_sav_to_json(str(sav_path), json_path, force=True, minify=False)
        with open(json_path) as f:
            json_data = json.load(f)
        roundtrip_path = os.path.join(self.tmpdir, "output.sav")
        convert_json_to_sav(json_path, roundtrip_path, force=True)
        with open(roundtrip_path, "rb") as f:
            recompressed = f.read()
        return json_data, recompressed

    def test_001_source_files_exist(self):
        self.assertTrue(self.level_sav.exists(), f"Missing: {self.level_sav}")
        self.assertTrue(self.localdata_sav.exists(), f"Missing: {self.localdata_sav}")
        player_savs = list(self.player_dir.glob("*.sav"))
        self.assertGreater(len(player_savs), 0, f"No player .sav files in {self.player_dir}")

    def test_002_level_sav_roundtrip(self):
        if not self.level_sav.exists():
            self.skipTest("Level.sav not available")
        json_data, _ = self._roundtrip(self.level_sav)
        world = json_data.get("properties", {}).get("worldSaveData", {}).get("value", {})
        self.assertIn("CharacterSaveParameterMap", world)
        self.assertIn("GroupSaveDataMap", world)
        self.assertIn("ItemContainerSaveData", world)
        self.assertIn("BaseCampSaveData", world)
        self.assertGreater(len(world.get("CharacterSaveParameterMap", {}).get("value", [])), 0)

    def test_003_localdata_sav_roundtrip(self):
        if not self.localdata_sav.exists():
            self.skipTest("LocalData.sav not available")
        json_data, _ = self._roundtrip(self.localdata_sav)
        self.assertIn("properties", json_data)
        self.assertIn("header", json_data)

    def test_004_property_types_preserved(self):
        if not self.level_sav.exists():
            self.skipTest("Level.sav not available")
        json_path = os.path.join(self.tmpdir, "level.json")
        convert_sav_to_json(str(self.level_sav), json_path, force=True, minify=False)
        with open(json_path) as f:
            json_data = json.load(f)
        world = json_data.get("properties", {}).get("worldSaveData", {}).get("value", {})

        group_map = world.get("GroupSaveDataMap", {})
        self.assertEqual(
            group_map.get("type"),
            "MapProperty",
            f"GroupSaveDataMap type mutated: {group_map.get('type')}",
        )

        char_map = world.get("CharacterSaveParameterMap", {})
        self.assertEqual(
            char_map.get("type"),
            "MapProperty",
            f"CharacterSaveParameterMap type mutated: {char_map.get('type')}",
        )

        container_map = world.get("ItemContainerSaveData", {})
        self.assertEqual(
            container_map.get("type"),
            "MapProperty",
            f"ItemContainerSaveData type mutated: {container_map.get('type')}",
        )

    def test_005_reference_graph_continuity(self):
        if not self.level_sav.exists():
            self.skipTest("Level.sav not available")
        json_path = os.path.join(self.tmpdir, "level.json")
        convert_sav_to_json(str(self.level_sav), json_path, force=True, minify=False)
        with open(json_path) as f:
            json_data = json.load(f)
        world = json_data.get("properties", {}).get("worldSaveData", {}).get("value", {})

        charmap = world.get("CharacterSaveParameterMap", {}).get("value", [])
        containers = world.get("ItemContainerSaveData", {}).get("value", [])
        container_guids = {
            c.get("key", {}).get("ID", {}).get("value", "") for c in containers
        }

        dangling = []
        for entry in charmap:
            sv = (
                entry.get("value", {})
                .get("RawData", {})
                .get("value", {})
                .get("object", {})
                .get("SaveParameter", {})
                .get("value", {})
            )
            is_player = sv.get("IsPlayer", {}).get("value", False)
            if not is_player:
                continue
            uid = entry.get("key", {}).get("PlayerUId", {}).get("value", "")
            inv = sv.get("InventoryData", {})
            for slot_key in ["CommonContainerId", "EssentialContainerId", "WeaponLoadOutContainerId"]:
                c_id = inv.get(slot_key, {}).get("value", {}).get("ID", {}).get("value", "")
                if c_id and c_id not in container_guids:
                    dangling.append((uid, slot_key, c_id))

        if dangling:
            for uid, key, cid in dangling[:5]:
                print(f"  Player {uid[:8]} -> {key} -> missing container {cid[:8]}")
        self.assertEqual(
            len(dangling), 0,
            f"{len(dangling)} player inventory container reference(s) missing from ItemContainerSaveData"
        )

    def test_006_character_container_links(self):
        if not self.level_sav.exists():
            self.skipTest("Level.sav not available")
        json_path = os.path.join(self.tmpdir, "level.json")
        convert_sav_to_json(str(self.level_sav), json_path, force=True, minify=False)
        with open(json_path) as f:
            json_data = json.load(f)
        world = json_data.get("properties", {}).get("worldSaveData", {}).get("value", {})

        charmap = world.get("CharacterSaveParameterMap", {}).get("value", [])
        charcontainers = world.get("CharacterContainerSaveData", {}).get("value", [])

        all_instance_ids = {e.get("key", {}).get("InstanceId", {}).get("value", "") for e in charmap}

        dangling = []
        for cc in charcontainers:
            container_id = cc.get("key", {}).get("ID", {}).get("value", "")
            slots = cc.get("value", {}).get("Slots", {}).get("value", {}).get("values", [])
            for slot in slots:
                inst_id = slot.get("RawData", {}).get("value", {}).get("instance_id", "")
                if inst_id and inst_id not in all_instance_ids:
                    dangling.append((container_id, inst_id))

        if dangling:
            for cid, iid in dangling[:5]:
                print(f"  Dangling: container {cid[:8]} references missing instance {iid[:8]}")
        self.assertEqual(
            len(dangling), 0, f"{len(dangling)} character container slot(s) reference missing character instances"
        )

    def test_007_guild_player_membership(self):
        if not self.level_sav.exists():
            self.skipTest("Level.sav not available")
        json_path = os.path.join(self.tmpdir, "level.json")
        convert_sav_to_json(str(self.level_sav), json_path, force=True, minify=False)
        with open(json_path) as f:
            json_data = json.load(f)
        world = json_data.get("properties", {}).get("worldSaveData", {}).get("value", {})

        charmap = world.get("CharacterSaveParameterMap", {}).get("value", [])
        groupmap = world.get("GroupSaveDataMap", {}).get("value", [])

        all_player_uids = set()
        for e in charmap:
            sv = (
                e.get("value", {})
                .get("RawData", {})
                .get("value", {})
                .get("object", {})
                .get("SaveParameter", {})
                .get("value", {})
            )
            if sv.get("IsPlayer", {}).get("value", False):
                uid = e.get("key", {}).get("PlayerUId", {}).get("value", "")
                if uid:
                    all_player_uids.add(uid)

        orphans = []
        for g in groupmap:
            gv = g.get("value", {}).get("RawData", {}).get("value", {})
            gtype = gv.get("group_type", "")
            if gtype != "EPalGroupType::Guild":
                continue
            for p in gv.get("players", []):
                puid = p.get("player_uid", "")
                if puid and puid not in all_player_uids:
                    orphans.append(puid)

        if orphans:
            for uid in orphans[:5]:
                print(f"  Orphaned guild member: {uid}")
        self.assertEqual(
            len(orphans), 0, f"{len(orphans)} guild member(s) not found in character map"
        )


if __name__ == "__main__":
    unittest.main()


def main():
    import argparse
    parser = argparse.ArgumentParser(prog="palsav validate", description="Run roundtrip integrity validation tests on a save directory.", add_help=False)
    parser.add_argument("--save-dir", default=None, help="Path to save directory (default: pal-save/EntUpdated)")
    args, remaining = parser.parse_known_args()
    if args.save_dir:
        os.environ["PST_SAVE_DIR"] = args.save_dir
    sys.argv[:] = [sys.argv[0]] + remaining
    result = unittest.main(module=__name__, exit=False, verbosity=2)
    sys.exit(0 if result.result.wasSuccessful() else 1)
