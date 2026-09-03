"""Verify a backup contains a parseable Level.sav. Prints VERIFY_OK/VERIFY_FAIL.

Accepts either a backup folder or a .zip backup (Level.sav is extracted to a
temp dir first).
"""
import glob
import os
import shutil
import sys
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "PalworldSaveTools-main", "src"))
sys.path.insert(0, os.path.join(_HERE, "PST"))
sys.path.insert(0, os.path.join(_HERE, "PST", "lib"))
import tempfile
import zipfile

sys.path.insert(0, r"E:\PalworldServer\app\tools\PalworldSaveTools-main\src")
sys.path.insert(0, r"E:\PalworldServer\app\tools\PST\lib")
sys.path.insert(0, r"E:\PalworldServer\app\tools\PST")

from palsav.io import load_sav

bak = sys.argv[1]
tmp = None
if bak.lower().endswith(".zip"):
    tmp = tempfile.mkdtemp(prefix="pwverify_")
    try:
        with zipfile.ZipFile(bak) as z:
            names = [n for n in z.namelist()
                     if os.path.basename(n).lower() == "level.sav"]
            if not names:
                print("VERIFY_FAIL no Level.sav found in backup zip")
                sys.exit(1)
            z.extract(names[0], tmp)
            bak = os.path.dirname(os.path.join(tmp, names[0])) or tmp
    except (OSError, zipfile.BadZipFile) as e:
        print("VERIFY_FAIL bad zip: " + str(e)[:120])
        sys.exit(1)

try:
    cands = glob.glob(os.path.join(bak, "**", "Level.sav"), recursive=True)
    if not cands:
        print("VERIFY_FAIL no Level.sav found in backup")
        sys.exit(1)
    try:
        load_sav(cands[0])
        print("VERIFY_OK")
    except Exception as e:  # noqa: BLE001
        print("VERIFY_FAIL " + str(e)[:150])
        sys.exit(1)
finally:
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)
