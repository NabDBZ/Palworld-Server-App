"""One-time asset pipeline: extract Palworld-Pal-Editor icons + build slim metas.

Outputs (LOCALAPPDATA\PalworldControl):
  icons\items\<IconKey>.png (+ .64.png thumbs)
  icons\pals_editor\<CharacterID>.png (+ .64.png thumbs)
  item_meta.json  {id: {fr,en,icon,group,rarity,sort}}
  pal_meta.json   {id: {fr,en,icon,deck}}
"""
import json
import os
import sys
import zipfile

APPDATA = os.path.join(os.environ["LOCALAPPDATA"], "PalworldControl")
IC_ITEMS = os.path.join(APPDATA, "icons", "items")
IC_PALS = os.path.join(APPDATA, "icons", "pals_editor")

z = zipfile.ZipFile(os.path.join(os.path.dirname(__file__), "paledit_assets.zip"))
names = z.namelist()
data_dir = [n for n in names if "/assets/data/" in n and n.endswith("/")][0]
item_data = json.loads(z.read(data_dir + "item_data.json").decode())
pal_data = json.loads(z.read(data_dir + "pal_data.json").decode())


def extract(subdir, dest):
    os.makedirs(dest, exist_ok=True)
    n = 0
    for name in names:
        if ("/assets/icons/%s/" % subdir) in name and name.endswith(".png"):
            base = os.path.basename(name)
            with z.open(name) as src, \
                    open(os.path.join(dest, base), "wb") as out:
                out.write(src.read())
            n += 1
    return n


n_items = extract("items", IC_ITEMS)
n_pals = extract("pals", IC_PALS)
print("extracted: %d item icons, %d pal icons" % (n_items, n_pals))

item_icons = {os.path.splitext(f)[0] for f in os.listdir(IC_ITEMS)}
pal_icons = {os.path.splitext(f)[0] for f in os.listdir(IC_PALS)}

# ---- item meta: giftable static stackables with an icon ----
item_meta = {}
for iid, v in item_data.items():
    if v.get("Disabled") or v.get("MonsterOnly"):
        continue
    if not v.get("MaxStackCount") or v["MaxStackCount"] <= 1:
        continue
    icon = v.get("IconKey") or iid
    if icon not in item_icons:
        continue
    i18n = v.get("I18n") or {}
    fr = (i18n.get("fr") or {}).get("Name") or (i18n.get("en") or {}).get("Name") or iid
    en = (i18n.get("en") or {}).get("Name") or fr
    item_meta[iid] = {"fr": fr, "en": en, "icon": icon,
                      "group": v.get("Group") or "Common",
                      "rarity": v.get("Rarity") or 0,
                      "sort": v.get("SortId") or 999999}
print("item_meta entries (giftable, with icon):", len(item_meta))
print("  rarity values:", sorted({m["rarity"] for m in item_meta.values()}))
print("  groups:", sorted({m["group"] for m in item_meta.values()}))

# ---- pal meta: every CharacterID with an icon ----
pal_meta = {}
for pid, v in pal_data.items():
    if v.get("Invalid"):
        continue
    icon = pid if pid in pal_icons else (v.get("IconKey") or "")
    if icon not in pal_icons:
        continue
    i18n = v.get("I18n") or {}
    fr = i18n.get("fr") or i18n.get("en") or pid
    en = i18n.get("en") or fr
    if isinstance(fr, dict):
        fr = fr.get("Name") or pid
    if isinstance(en, dict):
        en = en.get("Name") or fr
    st = v.get("Stats") or {}
    pal_meta[pid] = {"fr": fr, "en": en, "icon": icon,
                     "deck": v.get("PaldeckIndex") or 0,
                     "dsuf": str(v.get("PaldeckSuffix") or ""),
                     "fam": str(v.get("FamilyID") or ""),
                     "el": v.get("Elements") or [],
                     "hp": st.get("HP") or 0, "atk": st.get("ATK") or 0,
                     "def": st.get("DEF") or 0}
print("pal_meta entries (with icon):", len(pal_meta))

# recettes speciales d'elevage (UniqueRecipes du jeu, famille->famille)
recipes = []
fam_members = {}
for pid, v in pal_data.items():
    fam_members.setdefault(str(v.get("FamilyID") or ""), []).append(pid)
for pid, v in pal_data.items():
    if v.get("Invalid"):
        continue
    for r in (v.get("Breeding") or {}).get("UniqueRecipes") or []:
        fa = str(r.get("ParentTribeA") or "").split("::")[-1]
        fb = str(r.get("ParentTribeB") or "").split("::")[-1]
        if fa and fb and fa in fam_members and fb in fam_members:
            recipes.append([fa, fb, pid])
with open(os.path.join(APPDATA, "breeding_recipes.json"), "w",
          encoding="utf-8") as f:
    json.dump({"recipes": recipes, "fam_members": fam_members}, f,
              ensure_ascii=False)
print("breeding_recipes.json:", len(recipes), "recettes")

for name, meta in (("item_meta.json", item_meta), ("pal_meta.json", pal_meta)):
    with open(os.path.join(APPDATA, name), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
print("metas written")

# ---- thumbnails (PIL, offline — the UI thread never resizes) ----
try:
    from PIL import Image
except ImportError:
    sys.exit("PIL missing")
done = 0
for d in (IC_ITEMS, IC_PALS):
    for f in os.listdir(d):
        if not f.endswith(".png") or f.endswith(".64.png"):
            continue
        p = os.path.join(d, f)
        thumb = p + ".64.png"
        if os.path.exists(thumb):
            continue
        try:
            im = Image.open(p).convert("RGBA")
            im.thumbnail((64, 64), Image.LANCZOS)
            im.save(thumb)
            done += 1
        except Exception as e:
            print("thumb fail", f, e)
print("thumbnails written:", done)
