"""Swap a friend's old co-op character onto their new server character.

Usage: py312\\python.exe migrate_friend.py <world_dir> <old_uid32> <new_uid32>
Reuses the PalworldSaveTools fix_save() with the Qt UI mocked out.
Prints MIGRATE_OK / MIGRATE_FAIL + exit code.
"""
import os
import sys
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "PalworldSaveTools-main", "src"))
sys.path.insert(0, os.path.join(_HERE, "PST"))
sys.path.insert(0, os.path.join(_HERE, "PST", "lib"))

sys.path.insert(0, r"E:\PalworldServer\app\tools\PalworldSaveTools-main\src")
sys.path.insert(0, r"E:\PalworldServer\app\tools\PST\lib")
sys.path.insert(0, r"E:\PalworldServer\app\tools\PST")

world, old_guid, new_guid = sys.argv[1], sys.argv[2], sys.argv[3]
assert len(old_guid) == 32 and len(new_guid) == 32, "uids must be 32 hex chars"

import palworld_toolsets.fix_host_save as fhs

fhs.show_information = lambda *a, **k: print("[ui] info suppressed")
fhs.show_warning = lambda *a, **k: print("[ui] warning suppressed")
fhs.run_with_loading = lambda on_finished, task_func: on_finished(task_func())

print(f"swap: {old_guid} -> {new_guid} in {world}")
try:
    fhs.fix_save(world, new_guid, old_guid)  # guild_fix=True default
except Exception as e:
    import traceback
    traceback.print_exc()
    print("MIGRATE_FAIL")
    sys.exit(1)
print("MIGRATE_OK")
