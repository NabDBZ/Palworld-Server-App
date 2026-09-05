# -*- coding: utf-8 -*-
"""Active le crossplay (Steam, Xbox, PS5, Mac) proprement.

Procedure sure (le serveur reecrit son ini a l'arret avec ses valeurs en
memoire, donc toute ecriture doit se faire SERVEUR ARRETE) :
  1. sauvegarde monde + arret gracieux
  2. ecriture CrossplayPlatforms=(Steam,Xbox,PS5,Mac)
     + nettoyage des fragments orphelins ('Xbox', 'PS5', 'Mac),...')
  3. demarrage + verification
  4. TEST DE SURVIE : nouvel arret -> que dit le dump du serveur ?
     -> redemarrage final + verification
"""
import io
import re
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import palworld_control as pc  # noqa: E402

WANT = "(Steam,Xbox,PS5,Mac)"
KEY = "CrossplayPlatforms"


def clean_line_and_set():
    """Reecrit la ligne OptionSettings sans orphelins, avec la valeur cible."""
    txt = io.open(pc.INI_PATH, encoding="utf-8").read()
    m = re.search(r"^OptionSettings=\((.*)\)\s*$", txt, re.MULTILINE)
    if not m:
        raise SystemExit("ligne OptionSettings introuvable")
    entries = pc._split_entries(m.group(1))
    cleaned, dropped = [], []
    for e in entries:
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", e):
            if e.startswith(KEY + "="):
                e = KEY + "=" + WANT
            cleaned.append(e)
        else:
            # fragment orphelin ; on recupere bIsUseBackupSaveData si c'est lui
            if "bIsUseBackupSaveData=True" in e and not any(
                    x.startswith("bIsUseBackupSaveData=") for x in cleaned):
                cleaned.append("bIsUseBackupSaveData=True")
            dropped.append(e[:40])
    if not any(e.startswith(KEY + "=") for e in cleaned):
        cleaned.append(KEY + "=" + WANT)
    new_line = "OptionSettings=(" + ",".join(cleaned) + ")"
    new_txt = txt[:m.start()] + new_line + txt[m.end():]
    with open(pc.INI_PATH, "w", encoding="utf-8", newline="") as f:
        f.write(new_txt)
    return len(cleaned), dropped


def check(label):
    txt = io.open(pc.INI_PATH, encoding="utf-8").read()
    inner = re.search(r"^OptionSettings=\((.*)\)\s*$", txt,
                      re.MULTILINE).group(1)
    ents = pc._split_entries(inner)
    val = next((e.split("=", 1)[1] for e in ents
                if e.startswith(KEY + "=")), "?")
    orphans = [e[:25] for e in ents if not re.match(
        r"^[A-Za-z_][A-Za-z0-9_]*=", e)]
    print(f"[{label}] serveur={'ON' if pc.is_running() else 'OFF'} "
          f"{KEY}={val} orphelins={orphans if orphans else 'aucun'}")
    return val


def cycle(action):
    if action == "stop":
        try:
            pc.rcon_exec("Save", timeout=8)
        except Exception:
            pass
        pc.stop_server()
        for _ in range(40):
            time.sleep(1)
            if not pc.is_running():
                return True
        return False
    ok = pc.start_server()
    for _ in range(10):
        time.sleep(2)
        try:
            pc.rcon_exec("ShowPlayers", timeout=4)
            break
        except Exception:
            continue
    return ok


print("== etat initial ==")
check("depart")
print("== arret ==")
if not cycle("stop"):
    raise SystemExit("le serveur ne s'est pas arrete")
n, dropped = clean_line_and_set()
print(f"ligne nettoyee: {n} entrees valides, fragments retires: {dropped}")
check("apres ecriture (serveur arrete)")
print("== demarrage 1 ==")
print("demarre:", cycle("start"))
check("apres demarrage")
print("== TEST DE SURVIE: arret pour voir le dump du serveur ==")
if not cycle("stop"):
    raise SystemExit("le serveur ne s'est pas arrete (2)")
after_dump = check("apres dump d'arret")
print("== demarrage final ==")
print("demarre:", cycle("start"))
final = check("final")
print()
print("VERDICT SURVIE:", "OK - la valeur tient" if after_dump == WANT
      else f"ATTENTION - le dump du serveur l'a alteree -> {after_dump}")
