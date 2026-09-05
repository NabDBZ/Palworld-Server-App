# -*- coding: utf-8 -*-
"""Verification LECTURE SEULE des reglages du serveur.
Compare l'ini live avec DefaultPalWorldSettings.ini (defauts officiels de
cette version), valide syntaxe, doublons, types et bornes de l'appli.
N'ecrit JAMAIS dans les fichiers."""
import io
import os
import re

import palworld_control as pc

INI = pc.INI_PATH
DEFAULT = r"E:\PalworldServer\server\DefaultPalWorldSettings.ini"

print("=== 1. Syntaxe du fichier ===")
txt = io.open(INI, encoding="utf-8").read()
m = re.search(r"^OptionSettings=\((.*)\)\s*$", txt, re.MULTILINE)
assert m, "ligne OptionSettings introuvable"
inner = m.group(1)
# bilan des parentheses a l'interieur de la ligne (hors chaines quotees)
no_str = re.sub(r'"[^"]*"', '""', inner)
opens, closes = no_str.count("("), no_str.count(")")
print(f"parens: {opens} ouvrantes / {closes} fermantes ->",
      "EQUILIBREES" if opens == closes else "DESEQUILIBREES !")
entries = pc._split_entries(inner)
keys = [e.split("=", 1)[0].strip() for e in entries if "=" in e]
dups = sorted({k for k in keys if keys.count(k) > 1})
print(f"entrees: {len(keys)}, doublons:", dups if dups else "aucun")
bad = [e[:60] for e in entries if "=" not in e]
print("entrees sans '=' :", bad if bad else "aucune")
# ancienne corruption: valeur avec parenthese orpheline
corrupt = [k for k in keys if re.search(r"\)$", k)]
print("traces de l'ancienne corruption de parentheses:",
     corrupt if corrupt else "aucune")

print()
print("=== 2. Chargement par l'appli ===")
cur = pc.load_server_settings()
print(f"l'appli parse {len(cur)} cles sans erreur")

print()
print("=== 3. Valeurs personnalisees vs defauts officiels ===")
dtxt = io.open(DEFAULT, encoding="utf-8").read()
dm = re.search(r"^OptionSettings=\((.*)\)\s*$", dtxt, re.MULTILINE)
dcur = {}
if dm:
    for e in pc._split_entries(dm.group(1)):
        if "=" in e:
            k, v = e.split("=", 1)
            dcur[k.strip()] = v.strip()
    print(f"fichier defaut: {len(dcur)} cles")
else:
    print("!! DefaultPalWorldSettings.ini illisible")

MASK = ("ServerPassword", "AdminPassword")
custom = []
for k, v in sorted(cur.items()):
    d = dcur.get(k)
    if d is not None and d != v:
        shown = "****" if k in MASK else v
        custom.append((k, shown, d if k not in MASK else "****"))
print(f"{len(custom)} reglages different(s) des defauts :")
for k, v, d in custom:
    print(f"   {k} = {v}   (defaut: {d})")

print()
print("=== 4. Bornes de l'appli (PLAYFIELDS) ===")
pf = {f[1]: f for f in pc.PLAYFIELDS}
out_of_range, missing_in_ini = [], []
for key, (_sec, _k, _lab, _hint, kind, rng) in pf.items():
    if key not in cur:
        missing_in_ini.append(key)
        continue
    v = cur[key].strip('"')
    if kind == "int" and rng:
        if not v.lstrip("-").isdigit() or not (rng[0] <= int(v) <= rng[1]):
            out_of_range.append((key, v, rng))
    elif kind in ("float", "mins") and rng:
        try:
            x = float(v)
            lo, hi = rng
            if kind == "mins":  # ini en secondes, plage affichee en minutes
                lo, hi = lo * 60, hi * 60
            if not (lo <= x <= hi):
                out_of_range.append((key, v, rng))
        except ValueError:
            out_of_range.append((key, v, rng))
    elif kind == "bool" and v not in ("True", "False"):
        out_of_range.append((key, v, "True/False"))
print("hors bornes / invalides:", out_of_range if out_of_range else "aucun")
print("cles de l'appli absentes de l'ini:",
     missing_in_ini if missing_in_ini else "aucune")

print()
print("=== 5. File d'attente ini ===")
print("pending_ini.json present :",
      os.path.exists(pc.PENDING_INI_PATH),
      "(normal: absent quand tout est applique)")

print()
print("=== 6. Reglages cles du serveur ===")
def mask(k):
    v = cur.get(k, "?")
    return ("****" + v[-2:]) if k in MASK and v != "?" else v
for k in ("ServerName", "ServerPassword", "AdminPassword",
          "ServerPlayerMaxNum", "Difficulty", "BaseCampWorkerMaxNum",
          "BaseCampMaxNumInGuild", "bIsPvP", "DeathPenalty", "RCONEnabled",
          "AutoSaveSpan", "bIsBackup"):
    print(f"   {k} = {mask(k)}")
print()
print("VERIFICATION TERMINEE (aucune ecriture effectuee)")
