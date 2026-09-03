#!/usr/bin/env python3
"""Palworld Server Manager - desktop control panel for the local dedicated server.

Core logic (ini editing, RCON, process control, scheduling, backups) is kept
importable without the GUI so it can be tested headlessly.
"""
import json
import os
import queue
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
import zipfile
from collections import deque
from datetime import datetime, time as dtime, timedelta

import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

try:
    import psutil
except ImportError:  # pragma: no cover - psutil ships with the frozen build
    psutil = None

try:
    import winsound
except ImportError:
    winsound = None

APP_TITLE = "Palworld Server Manager"
APP_NAME = "PalworldControl"


# --------------------------------------------------------------------------
# Paths (everything lives under the folder containing this exe/script)
# --------------------------------------------------------------------------
def _base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    d = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(d)
    if os.path.exists(os.path.join(parent, "server", "PalServer.exe")):
        return parent
    return d


BASE = _base_dir()
SERVER_DIR = os.path.join(BASE, "server")
INI_PATH = os.path.join(
    SERVER_DIR, "Pal", "Saved", "Config", "WindowsServer", "PalWorldSettings.ini"
)
STEAMCMD = os.path.join(BASE, "steamcmd", "steamcmd.exe")
BACKUP_DIR = os.path.join(BASE, "backups")
SAVES_DIR = os.path.join(SERVER_DIR, "Pal", "Saved", "SaveGames")
CONSOLE_LOG = os.path.join(BASE, "server_console.log")
GAME_PORT = 8211
RCON_PORT = 25575
PROC_NAMES = {
    "palserver.exe",
    "palserver-win64-shipping-cmd.exe",
    "palserver-win64-shipping.exe",
}
_APPDATA = os.path.join(os.environ.get("LOCALAPPDATA", BASE), APP_NAME)
CONFIG_JSON = os.path.join(_APPDATA, "settings.json")
EVENTS_JSON = os.path.join(_APPDATA, "events.json")
UPTIME_JSON = os.path.join(_APPDATA, "uptime.json")
PLAYERS_JSON = os.path.join(_APPDATA, "players.json")
GUILD_CACHE_JSON = os.path.join(_APPDATA, "guild_cache.json")
VERIFIED_JSON = os.path.join(_APPDATA, "verified_backups.json")
WORLDS_STORE = os.path.join(BASE, "worlds")
ADMIN_FIX_BAT = os.path.join(BASE, "admin_fix.bat")
TOOLS_PY312 = os.path.join(BASE, "app", "tools", "py312", "python.exe")
TOOLS_SCAN = os.path.join(BASE, "app", "tools", "scan_world.py")
TOOLS_MIGRATE = os.path.join(BASE, "app", "tools", "migrate_friend.py")
TOOLS_VERIFY = os.path.join(BASE, "app", "tools", "verify_backup.py")
TOOLS_GIFT = os.path.join(BASE, "app", "tools", "gift.py")

DEFAULT_CFG = {
    "mode": "always",          # "always" or "scheduled"
    "on_time": "18:00",
    "off_time": "23:00",
    "daily_restart": "05:00",  # "" disables
    "watchdog": True,          # restart if it crashes
    "autostart_app": True,     # app starts with Windows
    "appearance": "Dark",
    "accent": "sky",
    "lang": "en",
    "tray_notifications": True,
    "backup_interval_h": 4,    # 0 disables auto backups
    "backup_keep": 20,
    "duck_domain": "",
    "duck_token": "",
    "router_done": False,
    "geometry": "",
    "motd": "Welcome to my Palworld server! 🐑",
    "motd_enabled": True,
    "auto_update_enabled": False,
    "auto_update_time": "05:30",
    "bouncer_enabled": False,
    "bouncer_approved": [],
    "announcements": [],       # [{time, text, enabled}]
    "join_sound": True,
    "last_public_ip": "",
    "profiles": [],            # [{name, sd, st, ed, et, exp, cap}]
    "profile_state": {},       # {"name":..., "backup":{k:v}}
    "offsite_enabled": False,
    "offsite_dir": "",
    "offsite_keep": 5,
    "last_verify_week": "",
    "worlds": {},              # label -> world folder guid
    "active_label": "main",
    "zombie_check": True,      # restart when process is alive but RCON is dead
    "discord_webhook": "",
    "rotate_password": False,  # weekly server password rotation
    "rotate_day": "Mon",
    "rotate_hour": "09:00",
    "steam_api_key": "",       # for real player avatars
    "player_ids": {},          # player name -> steam id (learned from joins)
    "trophies": {},            # trophy id -> date awarded
    "nicknames": {},           # steam id -> display name you chose
    "recap_enabled": True,     # Sunday Discord recap
    "recap_time": "20:00",
    "gift_events": [],         # [{time, gold, items, pal, pal_lv, enabled}]
}


# --------------------------------------------------------------------------
# App config / events / uptime / guild cache / verified backups
# --------------------------------------------------------------------------
def load_cfg():
    cfg = dict(DEFAULT_CFG)
    try:
        with open(CONFIG_JSON, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def save_cfg(cfg):
    os.makedirs(os.path.dirname(CONFIG_JSON), exist_ok=True)
    with open(CONFIG_JSON, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def load_events():
    try:
        with open(EVENTS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def save_events(events):
    os.makedirs(os.path.dirname(EVENTS_JSON), exist_ok=True)
    with open(EVENTS_JSON, "w", encoding="utf-8") as f:
        json.dump(events[-200:], f)


def load_uptime():
    try:
        with open(UPTIME_JSON, "r", encoding="utf-8") as f:
            return json.load(f)[-10080:]
    except (OSError, ValueError):
        return []


def save_uptime(samples):
    os.makedirs(os.path.dirname(UPTIME_JSON), exist_ok=True)
    with open(UPTIME_JSON, "w", encoding="utf-8") as f:
        json.dump(samples, f)


def load_players_hist():
    try:
        with open(PLAYERS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)[-10080:]
    except (OSError, ValueError):
        return []


def save_players_hist(samples):
    os.makedirs(os.path.dirname(PLAYERS_JSON), exist_ok=True)
    with open(PLAYERS_JSON, "w", encoding="utf-8") as f:
        json.dump(samples, f)


def load_guild_cache():
    try:
        with open(GUILD_CACHE_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_guild_cache(data):
    os.makedirs(os.path.dirname(GUILD_CACHE_JSON), exist_ok=True)
    with open(GUILD_CACHE_JSON, "w", encoding="utf-8") as f:
        json.dump({"ts": time.time(), "data": data}, f)


def load_verified():
    try:
        with open(VERIFIED_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_verified(v):
    os.makedirs(os.path.dirname(VERIFIED_JSON), exist_ok=True)
    with open(VERIFIED_JSON, "w", encoding="utf-8") as f:
        json.dump(v, f)


# --------------------------------------------------------------------------
# PalWorldSettings.ini editing
# --------------------------------------------------------------------------
def _split_entries(s):
    """Split 'K=V,K=V,...' on commas that are outside quotes and parens."""
    out, buf, depth, in_q = [], "", 0, False
    for ch in s:
        if in_q:
            buf += ch
            if ch == '"':
                in_q = False
            continue
        if ch == '"':
            in_q = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append(buf.strip())
            buf = ""
            continue
        buf += ch
    if buf.strip():
        out.append(buf.strip())
    return out


def load_server_settings(path=INI_PATH):
    """Return {key: value-string} from the OptionSettings line."""
    if not os.path.exists(path):
        return {}  # server not installed yet — defaults everywhere
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"^OptionSettings=\((.*)\)\s*$", text, re.MULTILINE)
    if not m:
        raise ValueError("OptionSettings line not found in " + path)
    entries = {}
    for e in _split_entries(m.group(1)):
        if "=" in e:
            k, v = e.split("=", 1)
            entries[k.strip()] = v.strip()
    return entries


def write_server_settings(updates, path=INI_PATH):
    """Patch keys into the ini atomically (quote strings yourself, e.g. '\"x\"')."""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"^OptionSettings=\((.*)\)\s*$", text, re.MULTILINE)
    if not m:
        raise ValueError("OptionSettings line not found in " + path)
    entries = _split_entries(m.group(1))
    keys = [e.split("=", 1)[0].strip() for e in entries if "=" in e]
    for key, val in updates.items():
        entry = f"{key}={val}"
        if key in keys:
            idx = keys.index(key)
            entries[idx] = entry
        else:
            entries.append(entry)
    new_line = "OptionSettings=(" + ",".join(entries) + ")"
    new_text = text[:m.start()] + new_line + text[m.end():]
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new_text)
    os.replace(tmp, path)


PENDING_INI_PATH = os.path.join(_APPDATA, "pending_ini.json")


def apply_ini_updates(updates):
    """Write ini changes the safe way. The Palworld server REWRITES
    PalWorldSettings.ini with its in-memory settings when it exits, so an
    edit made while it runs is silently reverted at the next stop. While
    running, changes are stashed and flushed by start_server() before the
    next boot. Returns True when written to the ini right now."""
    if not is_running():
        write_server_settings(updates)
        return True
    try:
        pending = {}
        if os.path.exists(PENDING_INI_PATH):
            with open(PENDING_INI_PATH, "r", encoding="utf-8") as f:
                pending = json.load(f)
        pending.update(updates)
        with open(PENDING_INI_PATH, "w", encoding="utf-8") as f:
            json.dump(pending, f)
    except (OSError, ValueError):
        pass
    return False


def flush_pending_ini():
    """Apply ini edits deferred while the server was running (called from
    start_server, which always runs after the exit-dump)."""
    try:
        if os.path.exists(PENDING_INI_PATH):
            with open(PENDING_INI_PATH, "r", encoding="utf-8") as f:
                pending = json.load(f)
            os.remove(PENDING_INI_PATH)
            if pending:
                write_server_settings(pending)
    except (OSError, ValueError):
        pass


# --------------------------------------------------------------------------
# RCON (Source RCON protocol, pure stdlib)
# --------------------------------------------------------------------------
class RconError(Exception):
    pass


def _rcon_pack(pid, ptype, body):
    data = struct.pack("<ii", pid, ptype) + body.encode("utf-8") + b"\x00\x00"
    return struct.pack("<i", len(data)) + data


def _rcon_recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise RconError("connection closed")
        buf += chunk
    return buf


class Rcon:
    """Minimal Source RCON client. Use as a context manager."""

    def __init__(self, host="127.0.0.1", port=RCON_PORT, password="", timeout=5):
        self.password = password
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self._id = 1

    def __enter__(self):
        self.sock.sendall(_rcon_pack(self._id, 3, self.password))  # SERVERDATA_AUTH
        while True:  # some servers send an empty value packet first
            (size,) = struct.unpack("<i", _rcon_recv_exact(self.sock, 4))
            pid, ptype = struct.unpack("<ii", _rcon_recv_exact(self.sock, 8))
            _rcon_recv_exact(self.sock, max(0, size - 8))
            if ptype == 2:  # SERVERDATA_AUTH_RESPONSE
                if pid == -1:
                    raise RconError("RCON authentication failed (wrong admin password?)")
                return self

    def __exit__(self, *exc):
        self.sock.close()
        return False

    def exec(self, cmd):
        self._id += 1
        self.sock.sendall(_rcon_pack(self._id, 2, cmd))  # SERVERDATA_EXECCOMMAND
        size = struct.unpack("<i", _rcon_recv_exact(self.sock, 4))[0]
        _pid, ptype = struct.unpack("<ii", _rcon_recv_exact(self.sock, 8))
        body = _rcon_recv_exact(self.sock, size - 8)[:-2].decode("utf-8", "replace")
        if ptype != 0:  # SERVERDATA_RESPONSE_VALUE
            raise RconError(f"unexpected RCON packet type {ptype}")
        return body


def rcon_exec(cmd, timeout=5):
    """Run one RCON command using the AdminPassword from the ini."""
    pw = load_server_settings().get("AdminPassword", "").strip('"')
    with Rcon(password=pw, timeout=timeout) as r:
        return r.exec(cmd)


# --------------------------------------------------------------------------
# Process control
# --------------------------------------------------------------------------
_ctrl_lock = threading.Lock()
_stopping = False
_console_fh = None


def find_procs():
    if not psutil:
        return []
    out = []
    for p in psutil.process_iter(["name"]):
        if (p.info["name"] or "").lower() in PROC_NAMES:
            out.append(p)
    return out


def is_running():
    return bool(find_procs())


def _main_proc():
    for p in find_procs():
        if (p.info["name"] or "").lower() == "palserver-win64-shipping-cmd.exe":
            return p
    procs = find_procs()
    return procs[0] if procs else None


def start_server(wait_secs=150):
    """Start the dedicated server. Returns True if it came up."""
    global _console_fh
    with _ctrl_lock:
        if is_running():
            return True
        flush_pending_ini()
        players = load_server_settings().get("ServerPlayerMaxNum", "16")
        args = [f"-port={GAME_PORT}", f"-players={players}"]
        # Prefer the console binary: it actually writes to a redirected
        # stdout (the PalServer.exe launcher stub swallows output).
        cmd_exe = os.path.join(SERVER_DIR, "Pal", "Binaries", "Win64",
                               "PalServer-Win64-Shipping-Cmd.exe")
        exe = cmd_exe if os.path.isfile(cmd_exe) \
            else os.path.join(SERVER_DIR, "PalServer.exe")
        try:
            if _console_fh:
                _console_fh.close()
        except OSError:
            pass
        try:
            _console_fh = open(CONSOLE_LOG, "wb")
            popen_kw = {"stdout": _console_fh, "stderr": subprocess.STDOUT}
        except OSError:
            _console_fh = None
            popen_kw = {}
        subprocess.Popen(
            [exe, *args],
            cwd=SERVER_DIR,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
            **popen_kw,
        )
        deadline = time.time() + wait_secs
        while time.time() < deadline:
            time.sleep(3)
            if is_running():
                time.sleep(5)  # give it a moment to finish booting
                return True
        return False


def stop_server(force_after=25):
    """Graceful stop (RCON Save + DoExit), escalating to kill()."""
    global _stopping
    with _ctrl_lock:
        _stopping = True
        try:
            try:
                rcon_exec("Save", timeout=4)
                rcon_exec("DoExit", timeout=4)
            except (RconError, OSError, ValueError):
                pass  # server down or RCON disabled - fall through to kill
            deadline = time.time() + force_after
            while time.time() < deadline and is_running():
                time.sleep(2)
            for p in find_procs():
                try:
                    p.kill()
                except psutil.Error:
                    pass
            _, alive = psutil.wait_procs(find_procs(), timeout=10)
            return not alive
        finally:
            _stopping = False


def server_stats():
    """Snapshot for the UI. Safe to call from any thread."""
    p = _main_proc()
    if p is None:
        return {"running": False}
    try:
        ram = sum(pr.memory_info().rss for pr in find_procs())
        uptime_s = max(0, int(time.time() - p.create_time()))
        cpu = sum(pr.cpu_percent(interval=None) for pr in find_procs())
    except psutil.Error:
        return {"running": False}
    return {"running": True, "ram_gb": round(ram / 1024**3, 2),
            "uptime_s": uptime_s, "cpu": round(cpu, 1)}


def list_players():
    """Parse RCON ShowPlayers -> [(name, playeruid, steamid)]."""
    try:
        out = rcon_exec("ShowPlayers", timeout=4)
    except (RconError, OSError, ValueError):
        return []
    players = []
    for line in out.splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) == 3 and parts[0] and parts[0].lower() != "name":
            players.append(tuple(parts))
    return players


# --------------------------------------------------------------------------
# Schedule
# --------------------------------------------------------------------------
def desired_on(now, mode, on_time, off_time):
    """True if the server should be running at `now` (datetime.time)."""
    if mode != "scheduled":
        return True
    if on_time == off_time:
        return True
    if on_time < off_time:
        return on_time <= now < off_time
    return now >= on_time or now < off_time  # window wraps past midnight


def next_event_text(cfg, now=None):
    now = now or datetime.now()
    if cfg["mode"] != "scheduled":
        txt = "Always on (24/7)" if LANG != "fr" else "Toujours actif (24/7)"
    else:
        on_t = _parse_hm(cfg["on_time"])
        off_t = _parse_hm(cfg["off_time"])
        nxt = []
        for label, t in (("on", on_t), ("off", off_t)):
            candidate = datetime.combine(now.date(), t)
            if candidate <= now:
                candidate += timedelta(days=1)
            nxt.append((candidate, label))
        nxt.sort()
        when, what = nxt[0]
        txt = (f"Scheduled — next event: turns {what} at {when.strftime('%H:%M')}"
               if LANG != "fr"
               else f"Horaire — prochain événement : {what} à {when.strftime('%H:%M')}")
    if cfg.get("daily_restart"):
        txt += f"  ·  {T('daily restart')} {cfg['daily_restart']}"
    return txt


def _parse_hm(s):
    h, m = s.split(":")
    return dtime(int(h), int(m))


# --------------------------------------------------------------------------
# Backups / restore / update / duckdns / world scan / friend migration
# --------------------------------------------------------------------------
def backup_now():
    """Zip the whole SaveGames folder into backups/<timestamp>.zip — far
    smaller than the old folder copies (old folder backups still work)."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(BACKUP_DIR, exist_ok=True)
    if not os.path.isdir(SAVES_DIR):
        raise FileNotFoundError("Save folder not found: " + SAVES_DIR)
    dst = os.path.join(BACKUP_DIR, ts + ".zip")
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, _dirs, files in os.walk(SAVES_DIR):
            for f in files:
                full = os.path.join(root, f)
                try:
                    z.write(full, os.path.relpath(full, SAVES_DIR))
                except OSError:
                    # the server rotates its internal backup\world folder
                    # while we zip — files can vanish mid-walk; skip them
                    continue
    return dst


def list_backups():
    try:
        names = []
        for d in os.listdir(BACKUP_DIR):
            full = os.path.join(BACKUP_DIR, d)
            if os.path.isdir(full) or d.lower().endswith(".zip"):
                names.append(d)
        return sorted(names, reverse=True)
    except OSError:
        return []


def dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def backup_size(name):
    p = os.path.join(BACKUP_DIR, name)
    if p.lower().endswith(".zip"):
        try:
            return os.path.getsize(p)
        except OSError:
            return 0
    return dir_size(p)


def clean_old_backups(keep):
    """Delete all but the newest `keep` backups. Returns number removed."""
    bks = list_backups()
    removed = 0
    for name in bks[max(0, int(keep)):]:
        p = os.path.join(BACKUP_DIR, name)
        if p.lower().endswith(".zip"):
            try:
                os.remove(p)
            except OSError:
                pass
        else:
            shutil.rmtree(p, ignore_errors=True)
        removed += 1
    return removed


def delete_backup(name):
    p = os.path.join(BACKUP_DIR, name)
    if p.lower().endswith(".zip"):
        try:
            os.remove(p)
        except OSError:
            pass
    else:
        shutil.rmtree(p, ignore_errors=True)


def restore_backup(name, was_running):
    if was_running:
        stop_server()
    src = os.path.join(BACKUP_DIR, name)
    tmp = None
    if src.lower().endswith(".zip"):
        tmp = os.path.join(BACKUP_DIR, "_restore_tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        with zipfile.ZipFile(src) as z:
            z.extractall(tmp)
        src = tmp
    subprocess.run(
        ["robocopy", src, SAVES_DIR, "/MIR", "/NFL", "/NDL", "/NJH", "/NJS"],
        capture_output=True,
    )
    if tmp:
        shutil.rmtree(tmp, ignore_errors=True)


def verify_backup(name):
    """Parse-check a backup's Level.sav with the py312 toolchain."""
    if not (os.path.isfile(TOOLS_PY312) and os.path.isfile(TOOLS_VERIFY)):
        return False, "verify tools missing"
    try:
        r = subprocess.run(
            [TOOLS_PY312, TOOLS_VERIFY, os.path.join(BACKUP_DIR, name)],
            capture_output=True, text=True, timeout=900, encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    out = (r.stdout or "")
    return "VERIFY_OK" in out, out.strip().splitlines()[-1] if out else ""


# --- Steam news (public API, no key needed) -------------------------------
GAME_APPID = 1623730   # the game's page carries the news; the dedicated
                       # server app (2394010) has an empty feed


def fetch_steam_news(count=5):
    """Latest Palworld news / patch notes. [{title, url, date, text}]"""
    url = ("https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
           f"?appid={GAME_APPID}&count={count}&maxlength=420")
    try:
        with urllib.request.urlopen(url, timeout=12) as r:
            data = json.loads(r.read().decode())
    except (OSError, ValueError):
        return []
    items = []
    for n in (data.get("appnews", {}).get("newsitems") or [])[:count]:
        txt = re.sub(r"\[[^\]]+\]", "", n.get("contents") or "")  # strip bbcode
        txt = re.sub(r"\s+", " ", txt).strip()
        items.append({"title": n.get("title") or "", "url": n.get("url") or "",
                      "date": n.get("date") or 0, "text": txt[:300]})
    return items


# --- Discord webhook -------------------------------------------------------
def discord_send(webhook, content):
    """Post one message to a Discord webhook. True on success."""
    if not webhook or not webhook.startswith("http"):
        return False
    body = json.dumps({"content": str(content)[:1900]}).encode()
    req = urllib.request.Request(
        webhook, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": "PalworldControl"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return 200 <= r.status < 300
    except OSError:
        return False


# --- Steam profile avatars -------------------------------------------------
AVATAR_DIR = os.path.join(_APPDATA, "avatars")


def fetch_steam_avatars(api_key, steam_ids):
    """Download medium avatar images; returns {steamid: file_path}."""
    out = {}
    if not api_key:
        return out
    ids = ",".join(s for s in steam_ids if s)[:800]
    if not ids:
        return out
    url = ("https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
           f"?key={api_key}&steamids={ids}")
    try:
        with urllib.request.urlopen(url, timeout=12) as r:
            data = json.loads(r.read().decode())
    except (OSError, ValueError):
        return out
    os.makedirs(AVATAR_DIR, exist_ok=True)
    for p in data.get("response", {}).get("players") or []:
        sid, av = p.get("steamid"), p.get("avatarmedium") or p.get("avatar")
        if not (sid and av):
            continue
        path = os.path.join(AVATAR_DIR, sid + ".jpg")
        try:
            with urllib.request.urlopen(av, timeout=10) as r, \
                    open(path, "wb") as f:
                f.write(r.read())
            out[sid] = path
        except OSError:
            continue
    return out


# --- password rotation scheduling (pure helper, unit-tested) ---------------
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def rotation_due(cfg, now):
    """True if the weekly password rotation should fire for `now`."""
    if not cfg.get("rotate_password"):
        return False
    day = cfg.get("rotate_day", "Mon")
    hour = cfg.get("rotate_hour", "09:00")
    if WEEKDAYS[now.weekday()] != day or not re.fullmatch(
            r"[01]?\d:[0-5]\d", hour):
        return False
    if cfg.get("rotate_fired") == "rot" + now.strftime("%Y-%m-%d"):
        return False
    st = datetime.combine(now.date(), _parse_hm(hour))
    return st <= now <= st + timedelta(minutes=11)


def generate_password():
    import secrets
    import string
    return ("Pal-" +
            "".join(secrets.choice(string.ascii_letters + string.digits)
                    for _ in range(4)) + "!")


# --- crash diagnosis -------------------------------------------------------
CRASH_CAUSES = {
    "ram":   ("out of memory (RAM)", "à court de mémoire (RAM)"),
    "save":  ("save file problem", "problème de sauvegarde"),
    "game":  ("internal game bug", "bug interne du jeu"),
    "unknown": ("unknown cause", "cause inconnue"),
}


def diagnose_crash():
    """Guess why the server died from the tail of the console log."""
    try:
        with open(CONSOLE_LOG, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 20000))
            tail = f.read().decode("utf-8", "replace").lower()
    except OSError:
        tail = ""
    if not tail:
        return "unknown"
    if ("out of memory" in tail or "oom" in tail
            or "allocation" in tail and "fail" in tail):
        return "ram"
    if "corrupt" in tail or ("failed to load" in tail
                             or ("save" in tail and "fail" in tail)):
        return "save"
    if "assert" in tail or "fatal" in tail or "signal" in tail:
        return "game"
    return "unknown"


# --- trophies --------------------------------------------------------------
TROPHIES = [
    {"id": "first_friend", "icon": "🤝",
     "en": "First friend aboard", "fr": "Premier ami à bord",
     "d_en": "Someone joined the server.", "d_fr": "Quelqu'un a rejoint le serveur."},
    {"id": "uptime_7", "icon": "📅",
     "en": "Iron uptime", "fr": "Uptime de fer",
     "d_en": "7 days running without a stop.",
     "d_fr": "7 jours d'affilée sans arrêt."},
    {"id": "hours_100", "icon": "💯",
     "en": "Hundred-hour guild", "fr": "Guilde des cent heures",
     "d_en": "100h of playtime combined.", "d_fr": "100 h de jeu cumulées."},
    {"id": "night_owl", "icon": "🦉",
     "en": "Night owl", "fr": "Chouette de nuit",
     "d_en": "Used the app between 2 and 5 AM.",
     "d_fr": "A utilisé l'appli entre 2h et 5h du matin."},
    {"id": "verified_10", "icon": "💾",
     "en": "Vault keeper", "fr": "Gardien du coffre",
     "d_en": "10 backups verified OK.", "d_fr": "10 sauvegardes vérifiées OK."},
    {"id": "pals_1000", "icon": "🐑",
     "en": "Pal menagerie", "fr": "Ménagerie de Pals",
     "d_en": "1000+ Pals in the world.", "d_fr": "Plus de 1000 Pals dans le monde."},
    {"id": "cartographer", "icon": "🗺",
     "en": "Cartographer", "fr": "Cartographe",
     "d_en": "Scanned the world for the first time.",
     "d_fr": "Premier scan du monde effectué."},
    {"id": "crash_survivor", "icon": "💪",
     "en": "Crash survivor", "fr": "Survivant de crash",
     "d_en": "The server crashed and came back on its own.",
     "d_fr": "Le serveur a crashé et est revenu tout seul."},
    {"id": "gold_rush", "icon": "🪙",
     "en": "Gold rush", "fr": "Ruée vers l'or",
     "d_en": "The guild hoards 1,000,000 gold.",
     "d_fr": "La guilde thésaurise 1 000 000 d'or."},
    {"id": "santa", "icon": "🎅",
     "en": "Santa Claus", "fr": "Père Noël",
     "d_en": "Gave a first gift of gold, items or a Pal.",
     "d_fr": "A offert un premier cadeau : or, objets ou un Pal."},
]


def longest_up_run(uptime):
    """Longest streak of consecutive up-minutes in the samples."""
    best = run = 0
    for _ts, up in uptime:
        run = run + 1 if up else 0
        best = max(best, run)
    return best


# --- pal images (community paldex: github.com/mlg404/palworld-paldex-api) --
PALDEX_JSON = os.path.join(_APPDATA, "paldex.json")
ICON_DIR = os.path.join(_APPDATA, "icons", "pals")
PALDEX_SRC = ("https://raw.githubusercontent.com/mlg404/"
              "palworld-paldex-api/main")
_norm_key = lambda s: re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def load_paldex(force=False):
    """[{name, asset, image(abs url)}] — cached locally, refreshed weekly."""
    if not force and os.path.exists(PALDEX_JSON):
        try:
            if time.time() - os.path.getmtime(PALDEX_JSON) < 7 * 86400:
                with open(PALDEX_JSON, "r", encoding="utf-8") as f:
                    return json.load(f)
        except (OSError, ValueError):
            pass
    try:
        with urllib.request.urlopen(PALDEX_SRC + "/src/pals.json",
                                    timeout=20) as r:
            raw = json.loads(r.read().decode())
    except (OSError, ValueError):
        return []
    slim = [{"name": p.get("name", ""), "asset": p.get("asset", ""),
             "image": PALDEX_SRC + (p.get("image") or "")}
            for p in raw if p.get("image")]
    try:
        os.makedirs(os.path.dirname(PALDEX_JSON), exist_ok=True)
        with open(PALDEX_JSON, "w", encoding="utf-8") as f:
            json.dump(slim, f)
    except OSError:
        pass
    return slim


def pal_image_for(raw_id, paldex=None):
    """Local icon path for a save CharacterID ('BOSS_Anubis', 'Kitsun'…),
    downloading it once. Returns None when the pal isn't in the paldex."""
    paldex = paldex if paldex is not None else load_paldex()
    if not paldex:
        return None
    base = re.sub(r"^BOSS_", "", str(raw_id or ""))
    stem = base.split("_")[0] if "_" in base else base
    by_asset = {_norm_key(p.get("asset")): p for p in paldex}
    by_name = {_norm_key(p.get("name")): p for p in paldex}
    p = (by_asset.get(_norm_key(base)) or by_asset.get(_norm_key(stem))
         or by_name.get(_norm_key(base)) or by_name.get(_norm_key(stem)))
    if not p:
        return None
    os.makedirs(ICON_DIR, exist_ok=True)
    path = os.path.join(ICON_DIR, _norm_key(p.get("asset")) + ".png")
    if os.path.exists(path):
        return path
    try:
        with urllib.request.urlopen(p["image"], timeout=20) as r:
            data = r.read()
        if data[:4] != b"\x89PNG":
            return None
        with open(path, "wb") as f:
            f.write(data)
        # pre-scale a thumbnail so the UI thread never runs PIL resizes
        try:
            from PIL import Image
            im = Image.open(path).convert("RGBA")
            im.thumbnail((64, 64), Image.LANCZOS)
            im.save(path + ".64.png")
        except Exception:
            pass
        return path
    except OSError:
        return None


_CTK_IMG_CACHE = {}


def ctimg(path, size):
    """Cached CTkImage per (path, size) — PIL resizes once, not per render.
    Prefers the pre-scaled .64.png thumbnail written by the downloader."""
    key = (path, size)
    if key not in _CTK_IMG_CACHE:
        try:
            from PIL import Image
            best = path + ".64.png" if os.path.exists(path + ".64.png")                 else path
            _CTK_IMG_CACHE[key] = ctk.CTkImage(
                Image.open(best), size=size)
        except Exception:
            return None
    return _CTK_IMG_CACHE[key]


def cached_pal_image(raw_id, paldex=None):
    """Disk-cache lookup only — NEVER downloads (UI-thread safe)."""
    paldex = paldex if paldex is not None else load_paldex()
    if not paldex:
        return None
    base = re.sub(r"^BOSS_", "", str(raw_id or ""))
    stem = base.split("_")[0] if "_" in base else base
    by_asset = {_norm_key(p.get("asset")): p for p in paldex}
    by_name = {_norm_key(p.get("name")): p for p in paldex}
    p = (by_asset.get(_norm_key(base)) or by_asset.get(_norm_key(stem))
         or by_name.get(_norm_key(base)) or by_name.get(_norm_key(stem)))
    if not p:
        return None
    path = os.path.join(ICON_DIR, _norm_key(p.get("asset")) + ".png")
    return path if os.path.exists(path) else None


# ---- full gift catalogs (icons + FR names from the Palworld-Pal-Editor
# community asset set, extracted into LOCALAPPDATA by tools/build_asset_meta.py)
ITEM_ICON_DIR = os.path.join(_APPDATA, "icons", "items")
PAL_ICON2_DIR = os.path.join(_APPDATA, "icons", "pals_editor")
_ITEM_META = None
_PAL_META = None
_ITEM_META_NORM = {}


def load_item_meta():
    """{id: {fr,en,icon,group,rarity,sort}} for giftable stackable items."""
    global _ITEM_META, _ITEM_META_NORM
    if _ITEM_META is None:
        try:
            with open(os.path.join(_APPDATA, "item_meta.json"),
                      encoding="utf-8") as f:
                _ITEM_META = json.load(f)
        except (OSError, ValueError):
            _ITEM_META = {}
        # the save sometimes stores legacy lowercase ids ('bone') — alias
        # them to the CamelCase data keys for icon/name lookups
        _ITEM_META_NORM = {_norm_key(k): m for k, m in _ITEM_META.items()}
    return _ITEM_META


def _item_meta_of(iid):
    m = load_item_meta()
    return m.get(iid) or _ITEM_META_NORM.get(_norm_key(iid))


def load_pal_meta():
    """{CharacterId: {fr,en,icon,deck}} — exact save ids incl. BOSS_/variants."""
    global _PAL_META
    if _PAL_META is None:
        try:
            with open(os.path.join(_APPDATA, "pal_meta.json"),
                      encoding="utf-8") as f:
                _PAL_META = json.load(f)
        except (OSError, ValueError):
            _PAL_META = {}
    return _PAL_META


def item_icon_path(iid):
    m = _item_meta_of(iid)
    if not m:
        return None
    p = os.path.join(ITEM_ICON_DIR, m.get("icon", "") + ".png")
    return p if os.path.exists(p) else None


def _pal_meta_of(raw_id):
    pm = load_pal_meta()
    return pm.get(raw_id) or pm.get(re.sub(r"^BOSS_", "", str(raw_id)))


def pal_icon2_path(raw_id):
    """Exact CharacterID icon (disk-only lookup, UI-thread safe)."""
    m = _pal_meta_of(raw_id)
    if not m:
        return None
    p = os.path.join(PAL_ICON2_DIR, m.get("icon", "") + ".png")
    return p if os.path.exists(p) else None


def item_disp(iid):
    m = _item_meta_of(iid)
    if m:
        return m.get("fr") or m.get("en") or str(iid)
    return str(iid)


def pal_disp(raw_id):
    m = _pal_meta_of(raw_id)
    if m:
        base = m.get("fr") or m.get("en") or str(raw_id)
    else:
        base = re.sub(r"^BOSS_", "", str(raw_id))
    return ("\u2605 " if str(raw_id).startswith("BOSS_") else "") + base



GIFT_ASSETS_ZIP = ("https://codeload.github.com/KrisCris/"
                   "Palworld-Pal-Editor/zip/refs/heads/develop")


def bootstrap_gift_assets():
    """First-run download of the community gift artwork (game icons + FR/EN
    names for ~1 200 items and ~600 Pals). ~90 MB, once; offline after."""
    import zipfile as _zf
    try:
        req = urllib.request.Request(GIFT_ASSETS_ZIP,
                                     headers={"User-Agent": "pc"})
        with urllib.request.urlopen(req, timeout=600) as r:
            data = r.read()
        ztmp = os.path.join(_APPDATA, "paledit_assets.zip")
        with open(ztmp, "wb") as f:
            f.write(data)
        z = _zf.ZipFile(ztmp)
        names = z.namelist()
        for sub, dest in (("items", ITEM_ICON_DIR), ("pals", PAL_ICON2_DIR)):
            os.makedirs(dest, exist_ok=True)
            for n in names:
                if ("/assets/icons/%s/" % sub) in n and n.endswith(".png"):
                    with z.open(n) as s, \
                            open(os.path.join(dest, os.path.basename(n)),
                                 "wb") as o:
                        o.write(s.read())
        dj = [n for n in names if n.endswith("item_data.json")][0]
        pj = [n for n in names if n.endswith("pal_data.json")][0]
        item_data = json.loads(z.read(dj).decode())
        pal_data = json.loads(z.read(pj).decode())
        item_icons = {os.path.splitext(f)[0]
                      for f in os.listdir(ITEM_ICON_DIR)}
        pal_icons = {os.path.splitext(f)[0]
                     for f in os.listdir(PAL_ICON2_DIR)}
        item_meta, pal_meta = {}, {}
        for iid, v in item_data.items():
            if v.get("Disabled") or v.get("MonsterOnly"):
                continue
            if not v.get("MaxStackCount") or v["MaxStackCount"] <= 1:
                continue
            icon = v.get("IconKey") or iid
            if icon not in item_icons:
                continue
            i18n = v.get("I18n") or {}
            fr = (i18n.get("fr") or {}).get("Name") or \
                (i18n.get("en") or {}).get("Name") or iid
            en = (i18n.get("en") or {}).get("Name") or fr
            item_meta[iid] = {"fr": fr, "en": en, "icon": icon,
                              "group": v.get("Group") or "Common",
                              "rarity": v.get("Rarity") or 0,
                              "sort": v.get("SortId") or 999999}
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
            pal_meta[pid] = {"fr": fr, "en": en, "icon": icon,
                             "deck": v.get("PaldeckIndex") or 0}
        for name, meta in (("item_meta.json", item_meta),
                           ("pal_meta.json", pal_meta)):
            with open(os.path.join(_APPDATA, name), "w",
                      encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False)
        try:
            from PIL import Image
            for d in (ITEM_ICON_DIR, PAL_ICON2_DIR):
                for fn in os.listdir(d):
                    if fn.endswith(".png") and not fn.endswith(".64.png"):
                        p = os.path.join(d, fn)
                        try:
                            im = Image.open(p).convert("RGBA")
                            im.thumbnail((64, 64), Image.LANCZOS)
                            im.save(p + ".64.png")
                        except Exception:
                            pass
        except ImportError:
            pass
        try:
            os.remove(ztmp)
        except OSError:
            pass
        return True
    except Exception:
        return False

# emoji tiles for the items most often gifted (fallback when no icon exists)
ITEM_EMOJI = {
    "palsphere": "🔵", "palsphere_mega": "🟣", "palsphere_giga": "🟠",
    "arrow": "🏹", "riflebullet": "🔩", "shotgunbullet": "🔫",
    "cannonball": "⚫", "rocketammo": "🚀", "firearrow": "🔥",
    "poisonarrow": "☠", "money": "🪙", "wood": "🪵", "stone": "🪨",
    "coal": "⚫", "ingot": "⛓", "copperingot": "🥉", "quartz": "💎",
    "sulfur": "🟡", "polymer": "🧴", "carbonfiber": "🕸", "cement": "🧱",
    "leather": "🟤", "cloth": "🧵", "wool": "🧶", "egg": "🥚",
    "cake": "🎂", "berry": "🍓", "lettuce": "🥬", "tomato": "🍅",
    "milk": "🥛", "wheat": "🌾", "healingspray": "💊", "revivespray": "🧪",
    "repairkit": "🔧", "grenade": "💣", "firebomb": "🧨", "bait": "🪱",
    "dogcoin": "🪙", "ancientcivilizationparts": "🛠",
    "palamplifier": "🔊", "skillfruit": "🍏",
}


def item_emoji(static_id):
    k = _norm_key(static_id)
    for key, em in ITEM_EMOJI.items():
        if k == key or k.startswith(key):
            return em
    return "🎒"


def steamcmd_update(line_cb):
    """Stop, update via SteamCMD, backup, restart. line_cb(str) for the log."""
    line_cb("Stopping server (if running)...")
    was_running = is_running()
    if was_running:
        stop_server()
    line_cb("Downloading update via SteamCMD...")
    proc = subprocess.Popen(
        [STEAMCMD, "+force_install_dir", SERVER_DIR, "+login", "anonymous",
         "+app_update", "2394010", "validate", "+quit"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    for raw in proc.stdout:
        line = raw.rstrip()
        if line:
            line_cb(line)
    proc.wait()
    line_cb(f"SteamCMD finished (exit {proc.returncode}).")
    line_cb("Backing up saves...")
    backup_now()
    line_cb("Starting server...")
    ok = start_server()
    line_cb("Server is back UP." if ok else "WARNING: server did not come back up!")
    return ok


def local_buildid():
    try:
        acf = os.path.join(SERVER_DIR, "steamapps", "appmanifest_2394010.acf")
        with open(acf, encoding="utf-8") as f:
            m = re.search(r'"buildid"\s+"(\d+)"', f.read())
        return m.group(1) if m else None
    except OSError:
        return None


def remote_buildid(timeout=120):
    """Best-effort: query Steam for the current public build of the server."""
    try:
        out = subprocess.run(
            [STEAMCMD, "+login", "anonymous", "+app_info_print", "2394010",
             "+quit"],
            capture_output=True, text=True, timeout=timeout,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r'"public"\s*\{[^}]*?"buildid"\s+"(\d+)"', out, re.S)
    return m.group(1) if m else None


def duckdns_update(domain, token, timeout=10):
    url = (f"https://www.duckdns.org/update?domains={domain}"
           f"&token={token}&ip=")
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read().decode().strip() == "OK"
    except OSError:
        return False


def world_dir():
    """Folder of the active world (contains Level.sav)."""
    try:
        root = os.path.join(SAVES_DIR, "0")
        return next(
            os.path.join(root, d) for d in os.listdir(root)
            if os.path.isfile(os.path.join(root, d, "Level.sav"))
        )
    except (OSError, StopIteration):
        return None


def run_world_scan():
    """Scan guild data via the portable py312 toolchain. Returns dict or None."""
    if not (os.path.isfile(TOOLS_PY312) and os.path.isfile(TOOLS_SCAN)):
        return None
    world = world_dir()
    if not world:
        return None
    try:
        r = subprocess.run([TOOLS_PY312, TOOLS_SCAN, world], capture_output=True,
                           text=True, timeout=600, encoding="utf-8",
                           errors="replace")
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def run_friend_migration(old_uid, new_uid):
    """Swap a friend's old co-op character onto their server character."""
    if not (os.path.isfile(TOOLS_PY312) and os.path.isfile(TOOLS_MIGRATE)):
        return False, "migration tools missing"
    world = world_dir()
    if not world:
        return False, "world folder not found"
    try:
        r = subprocess.run(
            [TOOLS_PY312, TOOLS_MIGRATE, world, old_uid, new_uid],
            capture_output=True, text=True, timeout=1200, encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    return ("MIGRATE_OK" in (r.stdout or "")), (r.stdout or "")[-400:]


def run_pal_box(uid):
    """Dump a player's Pal box via the py312 toolchain."""
    script = os.path.join(BASE, "app", "tools", "pal_box.py")
    world = world_dir()
    if not (os.path.isfile(TOOLS_PY312) and os.path.isfile(script) and world):
        return None
    try:
        r = subprocess.run([TOOLS_PY312, script, world, uid],
                           capture_output=True, text=True, timeout=900,
                           encoding="utf-8", errors="replace")
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def offsite_copy(name, dest, keep):
    """Mirror one backup to a second location, pruning old copies."""
    if not dest:
        return False
    os.makedirs(dest, exist_ok=True)
    src = os.path.join(BACKUP_DIR, name)
    if src.lower().endswith(".zip"):
        try:
            shutil.copy2(src, os.path.join(dest, name))
        except OSError:
            return False
        zips = sorted(f for f in os.listdir(dest) if f.lower().endswith(".zip"))
        for f in zips[:max(0, len(zips) - int(keep))]:
            try:
                os.remove(os.path.join(dest, f))
            except OSError:
                pass
        return True
    subprocess.run(
        ["robocopy", src, os.path.join(dest, name),
         "/MIR", "/NFL", "/NDL", "/NJH", "/NJS"],
        capture_output=True,
    )
    try:
        dirs = sorted(d for d in os.listdir(dest)
                      if os.path.isdir(os.path.join(dest, d)))
        for d in dirs[:max(0, len(dirs) - int(keep))]:
            shutil.rmtree(os.path.join(dest, d), ignore_errors=True)
    except OSError:
        pass
    return True


def stored_worlds():
    try:
        return {d: os.path.join(WORLDS_STORE, d)
                for d in os.listdir(WORLDS_STORE)
                if os.path.isdir(os.path.join(WORLDS_STORE, d))}
    except OSError:
        return {}


DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _mins_of_week(day, hhmm):
    h, m = hhmm.split(":")
    return DAY_NAMES.index(day) * 1440 + int(h) * 60 + int(m)


def profile_active(prof, now):
    """Is a weekly profile window active at `now`? Handles midnight wrap."""
    try:
        s = _mins_of_week(prof["sd"], prof["st"])
        e = _mins_of_week(prof["ed"], prof["et"])
    except (KeyError, ValueError):
        return False
    if e <= s:
        e += 7 * 1440
    cur = now.weekday() * 1440 + now.hour * 60 + now.minute
    return s <= cur < e


# --------------------------------------------------------------------------
# Windows integration
# --------------------------------------------------------------------------
def set_app_autostart(enabled):
    try:
        import winreg
    except ImportError:
        return False
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        if enabled:
            exe = sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__)
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{exe}"')
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except OSError:
        return False


OLD_TASKS = ["PalworldServerWatchdog", "PalworldServerBoot", "PalworldServerDailyRestart"]


def old_tasks_present():
    out = []
    for tn in OLD_TASKS:
        r = subprocess.run(
            ["schtasks", "/query", "/tn", tn], capture_output=True
        )
        if r.returncode == 0:
            out.append(tn)
    return out


def firewall_rule_present():
    r = subprocess.run(
        ["netsh", "advfirewall", "firewall", "show", "rule",
         "name=Palworld Server UDP 8211"],
        capture_output=True, text=True,
    )
    return r.returncode == 0 and "8211" in (r.stdout or "")


def delete_own_task(tn):
    r = subprocess.run(["schtasks", "/delete", "/tn", tn, "/f"], capture_output=True)
    return r.returncode == 0


ADMIN_FIX_CONTENT = """@echo off
REM One-time admin fixes for the Palworld Server Manager
netsh advfirewall firewall delete rule name="Palworld Server UDP 8211" >nul 2>&1
netsh advfirewall firewall add rule name="Palworld Server UDP 8211" dir=in action=allow protocol=UDP localport=8211 profile=any
schtasks /delete /tn PalworldServerWatchdog /f >nul 2>&1
schtasks /delete /tn PalworldServerBoot /f >nul 2>&1
schtasks /delete /tn PalworldServerDailyRestart /f >nul 2>&1
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
echo.
echo Done: firewall open, sleep disabled, old auto-start tasks removed.
pause
"""


def ensure_admin_fix_bat():
    if not os.path.exists(ADMIN_FIX_BAT):
        with open(ADMIN_FIX_BAT, "w", encoding="ascii") as f:
            f.write(ADMIN_FIX_CONTENT)
    return ADMIN_FIX_BAT


def run_admin_fix():  # raises OSError if UAC declined
    bat = ensure_admin_fix_bat()
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Start-Process -Verb RunAs -FilePath '{bat}' -Wait"],
        capture_output=True,
    )
    return r.returncode == 0


# --------------------------------------------------------------------------
# Visual prefs: accent colors + language (applied before the UI is built)
# --------------------------------------------------------------------------
BG = ("#edf4fa", "#0b1220")            # app background (artwork: ice-blue / night navy)
SURFACE = ("#ffffff", "#111a2c")        # cards / sidebar
SURFACE_2 = ("#e5edf6", "#192438")      # inputs, hover, nested surfaces
BORDER = ("#d7e2ef", "#223252")         # hairline card borders
TEXT = ("#0e1622", "#e9eef7")
TEXT_DIM = ("#59667a", "#8da1bd")
RED = ("#dc2626", "#ef4444")
RED_HOVER = ("#b91c1c", "#dc2626")
BLUE = ("#1a7fd4", "#3ba7ee")
BLUE_HOVER = ("#15699f", "#2c8fd8")
NEUTRAL = ("#6b7280", "#39434f")
NEUTRAL_HOVER = ("#5b6270", "#4a5662")
GRAY_TXT = TEXT_DIM

ACCENTS = {  # name -> (main, hover, soft)
    "sky":   (("#0384c8", "#38b6f0"), ("#026aa5", "#2c9eed"), ("#e0f3fc", "#0d2439")),
    "green":  (("#15a34a", "#22c55e"), ("#12813c", "#16a34a"), ("#e5f6ec", "#152a1c")),
    "blue":   (("#2563eb", "#3b82f6"), ("#1d4ed8", "#2563eb"), ("#e3ecfd", "#14233f")),
    "purple": (("#7c3aed", "#a78bfa"), ("#6d28d9", "#8b5cf6"), ("#eee9fd", "#1d1830")),
    "amber":  (("#d97706", "#f59e0b"), ("#b45309", "#d97706"), ("#fdf1df", "#2a1f0e")),
}
ACCENT = ACCENTS["green"][0]
ACCENT_HOVER = ACCENTS["green"][1]
ACCENT_SOFT = ACCENTS["green"][2]
SEL_BG = ACCENT_SOFT
LANG = "en"

F_DISPLAY = "Segoe UI Variable Display"
F_H1 = (F_DISPLAY, 22, "bold")
F_H2 = ("Segoe UI", 14, "bold")
F_BODY = ("Segoe UI", 12)
F_BODY_B = ("Segoe UI", 12, "bold")
F_SMALL = ("Segoe UI", 11)
F_STATUS = (F_DISPLAY, 22, "bold")
F_MONO = ("Consolas", 12)

AVATAR_COLORS = ["#ef4444", "#f97316", "#eab308", "#22c55e", "#14b8a6",
                 "#3b82f6", "#8b5cf6", "#ec4899"]


def apply_visual_prefs(cfg):
    global ACCENT, ACCENT_HOVER, ACCENT_SOFT, SEL_BG, LANG
    a = ACCENTS.get(cfg.get("accent", "sky"), ACCENTS["sky"])
    ACCENT, ACCENT_HOVER, ACCENT_SOFT = a
    SEL_BG = ACCENT_SOFT
    LANG = cfg.get("lang", "en")


# ---- translations ---------------------------------------------------------
STR_FR = {
    "Server": "Serveur", "Settings": "Réglages", "Schedule": "Planification",
    "Maintenance": "Maintenance", "Preferences": "Préférences",
    "Console": "Console",
    "Start, stop and watch your world": "Démarrez, arrêtez et surveillez votre monde",
    "Every gameplay option, in plain language": "Toutes les options de jeu, en langage clair",
    "When the server runs and restarts": "Quand le serveur tourne et redémarre",
    "Updates, backups and Windows setup": "Mises à jour, sauvegardes et réglages Windows",
    "Appearance, language and extras": "Apparence, langue et extras",
    "Live server output — errors, connections, warnings.":
        "Sortie live du serveur — erreurs, connexions, avertissements.",
    "Identity & access": "Identité & accès",
    "Who can join and how.": "Qui peut rejoindre et comment.",
    "World & time": "Monde & temps",
    "Overall difficulty and how fast time passes.": "Difficulté globale et vitesse du temps.",
    "Player": "Joueur",
    "Your own combat and survival rates.": "Vos taux de combat et de survie.",
    "Pals": "Pals",
    "Catching, spawning, upkeep and eggs.": "Capture, apparitions, entretien et œufs.",
    "Base & building": "Base & construction",
    "Bases, structures and Pal workers.": "Bases, structures et Pals travailleurs.",
    "Items & resources": "Objets & ressources",
    "Loot, gathering, durability and drops.": "Butin, récolte, durabilité et objets.",
    "Death & penalties": "Mort & pénalités",
    "What happens when you die.": "Ce qui se passe quand vous mourez.",
    "PvP & hardcore": "PvP & hardcore",
    "Player fighting and hardcore rules.": "Combats entre joueurs et règles hardcore.",
    "Guild": "Guilde",
    "Guild size and behaviour.": "Taille et comportement de la guilde.",
    "Convenience & extras": "Confort & extras",
    "Quality-of-life toggles.": "Options de confort.",
    "Players online": "Joueurs en ligne",
    "Click a player to select them, then use the buttons below.":
        "Cliquez sur un joueur pour le sélectionner, puis utilisez les boutons ci-dessous.",
    "Recent activity": "Activité récente",
    "Joins, leaves, restarts and maintenance — kept between app restarts.":
        "Connexions, départs, redémarrages et maintenance — conservés entre les lancements.",
    "Invite your friends": "Invitez vos amis",
    "One click copies everything they need — no explaining needed.":
        "Un clic copie tout ce qu'il leur faut — aucune explication nécessaire.",
    "🌍   Public address": "🌍   Adresse publique",
    "🏠   Same Wi-Fi address": "🏠   Adresse même Wi-Fi",
    "🔑   Password": "🔑   Mot de passe",
    "Copy invite message": "Copier l'invitation",
    "Copy address only": "Copier l'adresse",
    "▶   Start": "▶   Démarrer", "⏹   Stop": "⏹   Arrêter",
    "↻   Restart": "↻   Redémarrer",
    "Stop always saves the world first, so nothing is lost.":
        "Arrêter sauvegarde toujours le monde d'abord — rien n'est perdu.",
    "UPTIME": "EN LIGNE", "MEMORY": "MÉMOIRE", "PLAYERS ONLINE": "JOUEURS",
    "Save world now": "Sauvegarder le monde", "Send": "Envoyer",
    "Kick": "Expulser", "Ban": "Bannir",
    "Setup checklist": "Checklist d'installation",
    "Everything your friends need to connect, in one place.":
        "Tout ce qu'il faut pour que vos amis se connectent, au même endroit.",
    "Server running": "Serveur allumé",
    "Firewall port open (UDP 8211)": "Pare-feu ouvert (UDP 8211)",
    "Router port-forward done": "Redirection routeur faite",
    "Public address known": "Adresse publique connue",
    "Invite ready to send": "Invitation prête à envoyer",
    "Open router page": "Ouvrir la page du routeur",
    "Mark done": "C'est fait ✓", "Undo": "Annuler",
    "🚀  Finish setup": "🚀  Terminer l'installation",
    "This week": "Cette semaine",
    "Server up this week:": "Serveur en ligne cette semaine :",
    "World & guild": "Monde & guilde",
    "From the world save — levels, Pals and last seen per member.":
        "Depuis la sauvegarde — niveaux, Pals et dernière activité par membre.",
    "Scan world": "Analyser le monde",
    "Top:": "Top :",
    "Playtime this week": "Temps de jeu cette semaine",
    "Base map": "Carte des bases",
    "Positions of the bases found in the world save.":
        "Positions des bases trouvées dans la sauvegarde.",
    "Import a friend's character": "Importer le personnage d'un ami",
    "Server files": "Fichiers du serveur",
    "Storage": "Stockage",
    "Windows setup (one time)": "Réglages Windows (une fois)",
    "Needed once so friends can connect from outside your home.":
        "Nécessaire une fois pour que vos amis puissent se connecter depuis l'extérieur.",
    "Update server": "Mettre à jour le serveur",
    "Backup now": "Sauvegarder maintenant",
    "Open saves / backups folders": "Ouvrir les dossiers de sauvegardes",
    "Apply Windows fixes": "Appliquer les correctifs Windows",
    "Check for Palworld update now": "Vérifier les mises à jour maintenant",
    "Resources": "Ressources",
    "Palworld Wiki": "Wiki Palworld", "Guides & interactive map": "Guides & carte interactive",
    "Search breeding calculator": "Chercher un calculateur d'élevage",
    "When should the server run?": "Quand le serveur doit-il tourner ?",
    "The app turns the server on and off by itself at these times.":
        "L'appli allume et éteint le serveur toute seule à ces heures.",
    "Always on (24/7)": "Toujours actif (24/7)",
    "On a schedule": "Selon un horaire",
    "Turn ON at": "Allumage à", "Turn OFF at": "Extinction à",
    "Automation": "Automatisation",
    "Daily automatic restart at": "Redémarrage quotidien à",
    "Restart automatically if the server crashes":
        "Redémarrer automatiquement en cas de crash",
    "Open this app when Windows starts (recommended for 24/7)":
        "Ouvrir cette appli au démarrage de Windows (recommandé pour du 24/7)",
    "Save schedule": "Enregistrer la planification",
    "Save settings": "Enregistrer les réglages",
    "Search the settings… (name, effect or keyword)":
        "Rechercher dans les réglages… (nom, effet ou mot-clé)",
    "Appearance": "Apparence",
    "Accent color": "Couleur d'accent",
    "Language": "Langue",
    "Takes effect after the app restarts.": "Prend effet au redémarrage de l'appli.",
    "Notifications": "Notifications",
    "Show a popup when players join or leave":
        "Afficher une alerte quand des joueurs arrivent ou partent",
    "Play a chime when someone joins": "Jouer un son quand quelqu'un arrive",
    "Automatic backups": "Sauvegardes automatiques",
    "Every (hours)": "Toutes les (heures)", "Keep last": "Garder les",
    "0 disables automatic backups.": "0 désactive les sauvegardes automatiques.",
    "Save": "Enregistrer",
    "Automatic updates": "Mises à jour automatiques",
    "Update time": "Heure de mise à jour",
    "When an update is available, apply it automatically at this time "
    "(players get a 2-minute warning first).":
        "Quand une mise à jour est disponible, l'appliquer automatiquement à cette heure "
        "(les joueurs sont prévenus 2 minutes avant).",
    "Welcome message": "Message d'accueil",
    "Sent in-game every time someone joins.":
        "Envoyé en jeu à chaque fois que quelqu'un arrive.",
    "Friends-only lock": "Verrou amis uniquement",
    "Anyone who joins but isn't on the approved list is kicked automatically "
    "(on top of the password).":
        "Toute personne qui rejoint sans être sur la liste approuvée est expulsée "
        "automatiquement (en plus du mot de passe).",
    "Approved players (one Steam ID per line)": "Joueurs approuvés (un ID Steam par ligne)",
    "Approve everyone online now": "Approuver tout le monde en ligne",
    "Announcements": "Annonces",
    "Broadcast these messages in-game at the given times.":
        "Diffuse ces messages en jeu aux heures indiquées.",
    "Add announcement": "Ajouter une annonce",
    "Permanent address (DuckDNS)": "Adresse permanente (DuckDNS)",
    "A free yourname.duckdns.org address that always points to you — the invite never goes stale.":
        "Une adresse gratuite votrenom.duckdns.org qui pointe toujours vers vous — l'invitation ne périme jamais.",
    "Domain (without .duckdns.org)": "Domaine (sans .duckdns.org)",
    "Token": "Jeton",
    "Create a free account at duckdns.org, then paste your domain and token here.":
        "Créez un compte gratuit sur duckdns.org, puis collez votre domaine et jeton ici.",
    "Open duckdns.org": "Ouvrir duckdns.org",
    "About": "À propos",
    # --- v11 strings ---
    "Palworld news": "Actualité Palworld",
    "Official patch notes and announcements — click a headline to read it in your browser.":
        "Notes de patch officielles et annonces — cliquez un titre pour l'ouvrir "
        "dans le navigateur.",
    "Refresh": "Actualiser",
    "Loading…": "Chargement…",
    "Could not load the news — check the connection, or retry.":
        "Impossible de charger les actualités — vérifiez la connexion ou réessayez.",
    "Discord notifications": "Notifications Discord",
    "Get a message in your Discord channel when players join or leave, the server crashes, or an update is applied.":
        "Recevez un message dans votre salon Discord quand un joueur arrive ou "
        "part, quand le serveur crashe ou qu'une mise à jour est appliquée.",
    "Webhook URL": "URL du webhook",
    "Send test message": "Envoyer un message test",
    "In Discord: server settings → Integrations → Webhooks → New webhook → Copy URL.":
        "Dans Discord : réglages du serveur → Intégrations → Webhooks → "
        "Nouveau webhook → Copier l'URL.",
    "Sending…": "Envoi…",
    "Password rotation": "Rotation du mot de passe",
    "Change the server password automatically every week and copy the new invite to your clipboard.":
        "Change le mot de passe du serveur automatiquement chaque semaine et "
        "copie la nouvelle invitation dans le presse-papiers.",
    "Enable weekly rotation": "Activer la rotation hebdomadaire",
    "Rotate on": "Changer le",
    "at": "à",
    "Players get a 2-minute warning, then the server restarts with the new password.":
        "Les joueurs sont prévenus 2 minutes avant, puis le serveur redémarre "
        "avec le nouveau mot de passe.",
    "New password copied — invite ready to send!":
        "Nouveau mot de passe copié — invitation prête à envoyer !",
    "Password rotated": "Mot de passe changé",
    "Steam avatars": "Avatars Steam",
    "Show players' real Steam profile pictures instead of initials (free API key required).":
        "Affiche les vraies photos de profil Steam au lieu des initiales "
        "(clé API gratuite requise).",
    "Steam API key": "Clé API Steam",
    "Get a free key": "Obtenir une clé gratuite",
    "Peaceful": "Paisible",
    "Normal": "Normal",
    "Hardcore": "Hardcore",
    "PvP": "PvP",
    "No PvP, nothing lost on death — chill building with friends.":
        "Pas de PvP, rien perdu à la mort — construction tranquille entre amis.",
    "The vanilla experience — drop items on death.":
        "L'expérience vanilla — on perd ses objets à la mort.",
    "Drop EVERYTHING on death — for the brave.":
        "On TOUT perd à la mort — pour les braves.",
    "Guild wars: players can fight, equipment drops on death.":
        "Guerres de guildes : les joueurs peuvent se battre, l'équipement "
        "tombe à la mort.",
    "Applies the rules and offers a restart.":
        "Applique les règles et propose un redémarrage.",
    "This will change the game rules:": "Cela va modifier les règles du jeu :",
    "A safety backup is made first. Continue?":
        "Une sauvegarde de sécurité est faite d'abord. Continuer ?",
    "Apply preset": "Appliquer le préréglage",
    "Preset applied": "Préréglage appliqué",
    "Death penalty": "Pénalité de mort",
    "Guild card": "Carte de guilde",
    "Export a shareable image of the guild (members, levels, Pals) to share with friends.":
        "Exporte une image partageable de la guilde (membres, niveaux, Pals) "
        "à envoyer aux amis.",
    "Guild card saved": "Carte de guilde enregistrée",
    "Keyboard shortcuts": "Raccourcis clavier",
    "Switch pages (Server, Settings, …)": "Changer de page (Serveur, Réglages, …)",
    "Command palette — search everything": "Palette de commandes — tout chercher",
    "This shortcuts page": "Cette page de raccourcis",
    "Context menus: players, backups, guild rows":
        "Menus contextuels : joueurs, sauvegardes, lignes de guilde",
    "Close dialogs and the palette": "Fermer les fenêtres et la palette",
    "Press Esc or click to close": "Appuyez sur Échap ou cliquez pour fermer",
    "Server unresponsive": "Serveur sans réponse",
    "Restarting it automatically": "Redémarrage automatique en cours",
    "Invalid time": "Heure invalide",
    "Hmm…": "Hmm…",
    # --- v12 strings ---
    "Inventories": "Inventaires",
    "Gold and most-stocked items per player, from the world save — the friendly troll panel.":
        "Or et objets les plus stockés par joueur, depuis la sauvegarde — "
        "le panneau à trolls amicaux.",
    "Scan the world to see who hoards what.":
        "Scannez le monde pour voir qui thésaurise quoi.",
    "Sessions — last 7 days": "Sessions — 7 derniers jours",
    "When each player was online, day by day.":
        "Quand chaque joueur était en ligne, jour par jour.",
    "Sessions will appear once people have played.":
        "Les sessions apparaîtront dès que quelqu'un aura joué.",
    "Trophy shelf": "Étagère à trophées",
    "Little achievements earned by running the server. Some are hidden until you get them…":
        "Petits succès gagnés en faisant tourner le serveur. Certains sont "
        "cachés jusqu'à ce que tu les obtiennes…",
    "Trophy earned!": "Trophée gagné !",
    "Earned": "Gagnés",
    "Earned on": "Gagné le",
    "Not earned yet…": "Pas encore gagné…",
    "Invite card": "Carte d'invitation",
    "Include the password on the card?": "Inclure le mot de passe sur la carte ?",
    "(Choose “No” if you will send it in a private message.)":
        "(Choisissez « Non » si vous l'enverrez en message privé.)",
    "Join our Palworld server!": "Rejoignez notre serveur Palworld !",
    "Address": "Adresse",
    "Password": "Mot de passe",
    "Password: ask the host 😉": "Mot de passe : demande à l'hébergeur 😉",
    "In Palworld: Multiplayer → Join via IP → paste the address":
        "Dans Palworld : Multijoueur → Rejoindre via IP → collez l'adresse",
    "Invite card saved": "Carte d'invitation enregistrée",
    "Export a pretty invite image (address + optional password + QR code) to share in group chats.":
        "Exporte une jolie image d'invitation (adresse + mot de passe "
        "facultatif + QR code) à partager dans les groupes.",
    "Rename player": "Renommer le joueur",
    "Display name for": "Nom affiché pour",
    "Rename": "Renommer",
    "Repair game files": "Réparer les fichiers du jeu",
    "This stops the server, re-downloads any corrupted game files, then restarts. Takes 5-15 minutes. Continue?":
        "Cela arrête le serveur, re-télécharge les fichiers du jeu "
        "corrompus, puis redémarre. Prend 5-15 minutes. Continuer ?",
    "Repairing game files": "Réparation des fichiers du jeu",
    "Repair finished": "Réparation terminée",
    "Weekly recap": "Récap' hebdo",
    "Playtime": "Temps de jeu",
    "Uptime": "Uptime",
    "Backups verified": "Sauvegardes vérifiées",
    "Crashes": "Crashs",
    "Day": "Jour",
    # --- v13 strings (gifts) ---
    "Gifts & events": "Cadeaux & événements",
    "Give gold, items or Pals — written straight into the world save, no mods. Schedule recurring ones as events.":
        "Offre de l'or, des objets ou des Pals — écrit directement dans la "
        "sauvegarde, sans mods. Planifie des cadeaux récurrents en "
        "événements.",
    "Give a gift now": "Offrir un cadeau",
    "Gold, items and Pals for one player or the whole guild. A safety backup is made first.":
        "Or, objets et Pals pour un joueur ou toute la guilde. Une "
        "sauvegarde de sécurité est faite avant.",
    "No scheduled gift events yet.": "Pas encore d'événements cadeaux planifiés.",
    "Add gift event": "Ajouter un événement cadeau",
    "Give a gift": "Offrir un cadeau",
    "To": "Pour",
    "Everyone (guild)": "Tout le monde (guilde)",
    "Gold": "Or",
    "Items": "Objets",
    "Add item": "Ajouter un objet",
    "Pals": "Pals",
    "Add Pal": "Ajouter un Pal",
    "Lv": "Nv",
    "The server restarts for a minute while the gift is written into the save (players get a warning). A backup is made first — worst case, one click restores.":
        "Le serveur redémarre une minute le temps d'écrire le cadeau dans "
        "la sauvegarde (les joueurs sont prévenus). Une sauvegarde est "
        "faite avant — au pire, un clic restaure.",
    "Add some gold, items or a Pal first!":
        "Ajoute d'abord de l'or, des objets ou un Pal !",
    "Gift for": "Cadeau pour",
    "Continue?": "Continuer ?",
    "Give now": "Offrir maintenant",
    "Giving gifts…": "Distribution des cadeaux…",
    "Gift delivered!": "Cadeau distribué !",
    "Gift failed — world restored.": "Échec — monde restauré.",
    "items (id xN, id xN)": "objets (id xN, id xN)",
    "Pal id (optional)": "id du Pal (facultatif)",
    "Invalid values": "Valeurs invalides",
    "Gold must be a number.": "L'or doit être un nombre.",
    "Busy — try again in a moment.": "Occupé — réessaie dans un instant.",
    # --- v14 strings (visual gift picker) ---
    "Search… (name or id)": "Rechercher… (nom ou id)",
    "Basket": "Panier",
    "Selected": "Sélection",
    "Open": "Ouvrir", "Quit": "Quitter",
    "Server is running": "Le serveur tourne",
    "Server is stopped": "Le serveur est arrêté",
    "Still running in the tray": "Toujours actif dans la barre système",
    "The window is closed but the app keeps managing the server. "
    "Double-click the sheep icon near the clock to reopen.":
        "La fenêtre est fermée mais l'appli continue de gérer le serveur. "
        "Double-cliquez sur l'icône mouton près de l'horloge pour rouvrir.",
    "Stop the server? (World is saved first.)":
        "Arrêter le serveur ? (Le monde est sauvegardé d'abord.)",
    "Update available!": "Mise à jour disponible !",
    "daily restart": "redémarrage quotidien",
    "Crash protection active": "Protection anti-crash active",
    "The server kept crashing — auto-restart paused.":
        "Le serveur plantait en boucle — redémarrage auto en pause.",
    "Resume auto-restart": "Reprendre le redémarrage auto",
    "Invalid time": "Heure invalide",
    "Invalid values": "Valeurs invalides",
    "Restart the app now to apply?": "Redémarrer l'appli maintenant pour appliquer ?",
    "Settings saved. Restart the server now so they take effect?":
        "Réglages enregistrés. Redémarrer le serveur maintenant pour les appliquer ?",
    "Saved": "Enregistré",
    "Copied": "Copié",
    "Invite copied — paste it to your friends! ✅":
        "Invitation copiée — collez-la à vos amis ! ✅",
    "Address copied. ✅": "Adresse copiée. ✅",
    "world": "monde",
    "Restore": "Restaurer", "Delete": "Supprimer", "Verify": "Vérifier",
    "Right-click a backup to restore, verify or delete it.":
        "Clic droit sur une sauvegarde pour la restaurer, vérifier ou supprimer.",
    "Peak players per day": "Pic de joueurs par jour",
    "Pal boxes": "Boîtes de Pals",
    "Worlds": "Mondes",
    "Settings profiles": "Profils de réglages",
    "Offsite backups": "Sauvegardes externes",
    "Quick actions": "Actions rapides",
    "Go to": "Aller à",
    "Create test world": "Créer un monde test",
    "Delete test world": "Supprimer le monde test",
    "Add profile": "Ajouter un profil",
    # --- v15 strings (full gift catalog + turn-off button) ---
    "Turn off the app": "Éteindre l'appli",
    "Close the app completely — it stops watching the server "
    "(the server itself keeps running).":
        "Ferme l'appli complètement — elle arrête de surveiller le serveur "
        "(le serveur lui-même continue de tourner).",
    "Turn the app off completely?\n"
    "It will stop watching the server — the server itself "
    "keeps running.":
        "Éteindre complètement l'appli ?\n"
        "Elle arrêtera de surveiller le serveur — le serveur lui-même "
        "continue de tourner.",
    "Tip: closing the window with ✕ only hides it to the tray.":
        "Astuce : fermer la fenêtre avec ✕ la réduit seulement dans la barre "
        "des tâches.",
    "The app is already running.\n"
    "Look for its icon near the clock (or in the taskbar).":
        "L'appli tourne déjà.\n"
        "Cherche son icône près de l'horloge (ou dans la barre des tâches).",
    "Saved — applies at the next server start.":
        "Enregistré — appliqué au prochain démarrage du serveur.",
    "Gift artwork ready — items and Pals now have icons.":
        "Visuels des cadeaux prêts — objets et Pals ont leurs icônes.",
    "Could not download the gift artwork (offline?). Icons stay basic.":
        "Impossible de télécharger les visuels (hors ligne ?). "
        "Icônes basiques.",
}


def T(s):
    return STR_FR.get(s, s) if LANG == "fr" else s


SECTIONS = [
    ("access", "Identity & access", "Who can join and how."),
    ("world", "World & time", "Overall difficulty and how fast time passes."),
    ("player", "Player", "Your own combat and survival rates."),
    ("pals", "Pals", "Catching, spawning, upkeep and eggs."),
    ("base", "Base & building", "Bases, structures and Pal workers."),
    ("items", "Items & resources", "Loot, gathering, durability and drops."),
    ("death", "Death & penalties", "What happens when you die."),
    ("pvp", "PvP & hardcore", "Player fighting and hardcore rules."),
    ("guild", "Guild", "Guild size and behaviour."),
    ("qol", "Convenience & extras", "Quality-of-life toggles."),
]

PLAYFIELDS = [
    # section, key, label, hint, kind, extra
    ("access", "ServerName", "Server name",
     "Shown to friends when they connect.", "str", None),
    ("access", "ServerDescription", "Description",
     "Optional flavour text for the server.", "str", None),
    ("access", "ServerPassword", "Password to join",
     "Friends must type this to enter. Share it only with them!", "str", None),
    ("access", "AdminPassword", "Admin password",
     "Your secret password for admin commands (keep it private).", "str", None),
    ("access", "ServerPlayerMaxNum", "Max players",
     "How many friends can be online at the same time.", "int", (1, 32)),
    ("access", "AutoSaveSpan", "Autosave every (minutes)",
     "How often the world saves itself. Default 30.", "mins", (1, 1440)),
    ("access", "ChatPostLimitPerMinute", "Chat messages per minute",
     "Anti-spam limit before a player is muted. Default 30.", "int", (1, 1000)),

    ("world", "Difficulty", "Difficulty preset",
     "None = use the custom rates on this page; the others override "
     "them with presets.", "enum", ["None", "Easy", "Normal", "Difficult"]),
    ("world", "RandomizerType", "Randomizer mode",
     "Random mixes up spawns and items for a fresh challenge.", "enum",
     ["None", "Random"]),
    ("world", "DayTimeSpeedRate", "Day speed",
     "Higher = days pass faster. 1 = normal.", "float", (0.1, 5)),
    ("world", "NightTimeSpeedRate", "Night speed",
     "Higher = nights pass faster. 1 = normal.", "float", (0.1, 5)),
    ("world", "ExpRate", "EXP rate",
     "How fast players level up. 1 = normal, 2 = double.", "float", (0.1, 100)),

    ("player", "PlayerDamageRateAttack", "Your attack damage",
     "How much damage players deal. 2 = double.", "float", (0.1, 100)),
    ("player", "PlayerDamageRateDefense", "Damage you take",
     "How much damage players receive. 0.5 = half.", "float", (0.1, 100)),
    ("player", "PlayerStomachDecreaceRate", "Hunger speed",
     "Higher = get hungry faster. 0 = never hungry.", "float", (0, 10)),
    ("player", "PlayerStaminaDecreaceRate", "Stamina drain",
     "Higher = tire faster. 0 = infinite stamina.", "float", (0, 10)),
    ("player", "PlayerAutoHPRegeneRate", "Health regen",
     "Passive health regeneration speed.", "float", (0, 100)),
    ("player", "PlayerAutoHpRegeneRateInSleep", "Health regen (sleeping)",
     "Regeneration speed while sleeping in a bed.", "float", (0, 100)),
    ("player", "ItemWeightRate", "Item weight",
     "Lower = carry more. 0.5 = double carrying capacity.", "float", (0.1, 100)),

    ("pals", "PalCaptureRate", "Pal capture rate",
     "How easy Pals are to catch. 1 = normal.", "float", (0.5, 100)),
    ("pals", "PalSpawnNumRate", "Wild Pal population",
     "More Pals spawn in the wild.", "float", (0.1, 10)),
    ("pals", "PalDamageRateAttack", "Pal attack damage",
     "Damage dealt by Pals.", "float", (0.1, 100)),
    ("pals", "PalDamageRateDefense", "Damage Pals take",
     "Damage received by Pals.", "float", (0.1, 100)),
    ("pals", "PalStomachDecreaceRate", "Pal hunger speed",
     "Higher = Pals get hungry faster. 0 = never.", "float", (0, 10)),
    ("pals", "PalStaminaDecreaceRate", "Pal stamina drain",
     "Higher = Pals tire faster at work.", "float", (0, 10)),
    ("pals", "PalAutoHPRegeneRate", "Pal health regen",
     "Passive regeneration for Pals.", "float", (0, 100)),
    ("pals", "PalAutoHpRegeneRateInSleep", "Pal regen (sleeping)",
     "Regeneration while Pals rest in a bed.", "float", (0, 100)),
    ("pals", "PalEggDefaultHatchingTime", "Egg hatch time (hours)",
     "How long eggs take to hatch. 0 = instant.", "float", (0, 100)),
    ("pals", "MonsterFarmActionSpeedRate", "Ranch/farm work speed",
     "Speed of ranch jobs (milk, eggs, wool…).", "float", (0.1, 100)),
    ("pals", "EnablePredatorBossPal", "Predator boss Pals",
     "Special powerful predator Pals can appear.", "bool", None),

    ("base", "BaseCampMaxNum", "Max bases (world)",
     "Total bases allowed on the server. Default 128.", "int", (1, 500)),
    ("base", "BaseCampWorkerMaxNum", "Pals working per base",
     "Default 15.", "int", (1, 100)),
    ("base", "BaseCampMaxNumInGuild", "Bases per guild",
     "Default 4.", "int", (1, 50)),
    ("base", "BuildObjectHpRate", "Building health",
     "How sturdy structures are.", "float", (0.1, 100)),
    ("base", "BuildObjectDamageRate", "Damage buildings take",
     "From attacks and raids.", "float", (0.1, 100)),
    ("base", "BuildObjectDeteriorationDamageRate", "Building decay",
     "0 = buildings never decay over time.", "float", (0, 100)),
    ("base", "MaxBuildingLimitNum", "Total building limit",
     "Max pieces in the world. 0 = no limit.", "int", (0, 100000)),
    ("base", "bBuildAreaLimit", "Building only in base zones",
     "Restrict where structures can be placed.", "bool", None),
    ("base", "bAllowEnemyCampSpawnNearBaseCamp", "Enemy camps near bases",
     "Enemies may set up camps close to your base.", "bool", None),

    ("items", "CollectionDropRate", "Gathering yield",
     "Logs, stone, ore… how much drops per hit.", "float", (0.1, 100)),
    ("items", "CollectionObjectHpRate", "Node toughness",
     "How long resource nodes take to break.", "float", (0.1, 100)),
    ("items", "CollectionObjectRespawnSpeedRate", "Resource respawn speed",
     "How fast trees/ore come back.", "float", (0.1, 100)),
    ("items", "EnemyDropItemRate", "Enemy loot amount",
     "Loot from defeated enemies.", "float", (0.1, 100)),
    ("items", "EquipmentDurabilityDamageRate", "Gear durability loss",
     "0 = weapons and armour never wear out.", "float", (0, 100)),
    ("items", "ItemCorruptionMultiplier", "Item corruption speed",
     "Higher = items corrupt faster. 1 = normal.", "float", (0, 100)),
    ("items", "DropItemMaxNum", "Max items on the ground",
     "World-wide limit of dropped items. Default 3000.", "int", (100, 100000)),
    ("items", "DropItemAliveMaxHours", "Dropped items last (hours)",
     "How long items stay on the ground.", "float", (0.1, 720)),
    ("items", "SupplyDropSpan", "Supply drop interval (minutes)",
     "Time between supply drops. Default 180.", "int", (10, 100000)),

    ("death", "DeathPenalty", "Death penalty",
     "What you drop when you die.", "enum", ["None", "Item", "All"]),
    ("death", "bCanPickupOtherGuildDeathPenaltyDrop",
     "Pick up others' death drops",
     "Allow taking items dropped by other guilds' players.", "bool", None),
    ("death", "bEnableNonLoginPenalty", "Offline hunger/sickness",
     "Pals keep getting hungry and sick while you're away.", "bool", None),
    ("death", "RespawnPenaltyTimeScale", "Respawn penalty scale",
     "Scales debuff time after respawning. Default 2.", "float", (0, 10)),

    ("pvp", "bIsPvP", "PvP mode",
     "Players can fight each other.", "bool", None),
    ("pvp", "bEnablePlayerToPlayerDamage", "Player-to-player damage",
     "Base switch for damaging other players.", "bool", None),
    ("pvp", "bEnableFriendlyFire", "Friendly fire",
     "Hits also damage your teammates and own Pals.", "bool", None),
    ("pvp", "bHardcore", "Hardcore (perma-death)",
     "Dying deletes your character.", "bool", None),
    ("pvp", "bPalLost", "Pals can be lost",
     "Pals can disappear permanently (hardcore-style).", "bool", None),
    ("pvp", "bCharacterRecreateInHardcore", "Recreate after hardcore death",
     "Allow making a new character after a hardcore death.", "bool", None),

    ("guild", "GuildPlayerMaxNum", "Max guild members",
     "Players per guild. Default 20.", "int", (1, 100)),
    ("guild", "GuildRejoinCooldownMinutes", "Guild rejoin wait (minutes)",
     "0 = can rejoin instantly after leaving.", "int", (0, 10000)),
    ("guild", "bAutoResetGuildNoOnlinePlayers", "Auto-reset empty guilds",
     "Guild resets if nobody logs in for the time below.", "bool", None),
    ("guild", "AutoResetGuildTimeNoOnlinePlayers", "Auto-reset after (hours)",
     "Hours without any member online before reset. Default 72.",
     "float", (1, 1000)),

    ("qol", "bEnableFastTravel", "Fast travel",
     "Teleport between discovered points.", "bool", None),
    ("qol", "bEnableFastTravelOnlyBaseCamp", "Fast travel only between bases",
     "Restrict fast travel to your own bases.", "bool", None),
    ("qol", "bExistPlayerAfterLogout", "Character stays after logout",
     "Your body remains in the world when you disconnect.", "bool", None),
    ("qol", "bEnableAimAssistPad", "Aim assist (controller)",
     None, "bool", None),
    ("qol", "bEnableAimAssistKeyboard", "Aim assist (mouse)",
     None, "bool", None),
    ("qol", "bEnableInvaderEnemy", "Base raids",
     "Enemies can raid your base.", "bool", None),
    ("qol", "bActiveUNKO", "Poop mechanic",
     "…the Pal poop feature. Yes, really.", "bool", None),
    ("qol", "bEnableVoiceChat", "Voice chat",
     "Proximity voice chat on the server.", "bool", None),
    ("qol", "bIsShowJoinLeftMessage", "Join/leave messages",
     "Show when players join or leave in chat.", "bool", None),
    ("qol", "bShowPlayerList", "Show player list",
     "Display the online players list.", "bool", None),
    ("qol", "bAllowGlobalPalboxExport", "Allow Pal code export",
     "Pals can be exported via Palworld cross-save codes.", "bool", None),
    ("qol", "bAllowGlobalPalboxImport", "Allow Pal code import",
     "Pals can be imported via cross-save codes.", "bool", None),
    ("qol", "bAllowEnhanceStat_Health", "Allow +Health stat points",
     None, "bool", None),
    ("qol", "bAllowEnhanceStat_Attack", "Allow +Attack stat points",
     None, "bool", None),
    ("qol", "bAllowEnhanceStat_Stamina", "Allow +Stamina stat points",
     None, "bool", None),
    ("qol", "bAllowEnhanceStat_Weight", "Allow +Weight stat points",
     None, "bool", None),
    ("qol", "bAllowEnhanceStat_WorkSpeed", "Allow +Work speed stat points",
     None, "bool", None),
]

ACCESS_KEYS = {f[1] for f in PLAYFIELDS if f[0] == "access"}

TR_SETTINGS = {  # key -> (FR label, FR hint or None)
    "ServerName": ("Nom du serveur", "Affiché à vos amis à la connexion."),
    "ServerDescription": ("Description", "Texte optionnel pour le serveur."),
    "ServerPassword": ("Mot de passe pour rejoindre",
                       "Vos amis doivent le saisir pour entrer. Ne le partagez qu'avec eux !"),
    "AdminPassword": ("Mot de passe admin",
                      "Votre secret pour les commandes admin (gardez-le privé)."),
    "ServerPlayerMaxNum": ("Joueurs maximum",
                           "Combien d'amis peuvent être en ligne en même temps."),
    "AutoSaveSpan": ("Sauvegarde auto toutes les (minutes)",
                     "Fréquence de sauvegarde du monde. Défaut 30."),
    "ChatPostLimitPerMinute": ("Messages de chat par minute",
                               "Limite anti-spam avant mute. Défaut 30."),
    "Difficulty": ("Difficulté (préréglage)",
                   "None = utiliser les taux personnalisés de cette page ; les autres remplacent tout."),
    "RandomizerType": ("Mode aléatoire",
                       "Random mélange apparitions et objets pour un nouveau défi."),
    "DayTimeSpeedRate": ("Vitesse du jour", "Plus haut = journées plus rapides. 1 = normal."),
    "NightTimeSpeedRate": ("Vitesse de la nuit", "Plus haut = nuits plus rapides. 1 = normal."),
    "ExpRate": ("Taux d'EXP", "Vitesse de montée de niveau. 1 = normal, 2 = double."),
    "PlayerDamageRateAttack": ("Vos dégâts d'attaque", "Dégâts infligés par les joueurs. 2 = double."),
    "PlayerDamageRateDefense": ("Dégâts subis", "Dégâts reçus par les joueurs. 0,5 = moitié."),
    "PlayerStomachDecreaceRate": ("Vitesse de faim", "Plus haut = faim plus vite. 0 = jamais faim."),
    "PlayerStaminaDecreaceRate": ("Endurance", "Plus haut = fatigue plus vite. 0 = endurance infinie."),
    "PlayerAutoHPRegeneRate": ("Régénération de vie", "Vitesse de régénération passive."),
    "PlayerAutoHpRegeneRateInSleep": ("Régén. de vie (sommeil)", "Régénération pendant le sommeil."),
    "ItemWeightRate": ("Poids des objets", "Plus bas = porter plus. 0,5 = capacité doublée."),
    "PalCaptureRate": ("Taux de capture des Pals", "Facilité à capturer les Pals. 1 = normal."),
    "PalSpawnNumRate": ("Population de Pals sauvages", "Plus de Pals apparaissent dans la nature."),
    "PalDamageRateAttack": ("Dégâts des Pals", "Dégâts infligés par les Pals."),
    "PalDamageRateDefense": ("Dégâts subis par les Pals", "Dégâts reçus par les Pals."),
    "PalStomachDecreaceRate": ("Faim des Pals", "Plus haut = faim plus vite. 0 = jamais."),
    "PalStaminaDecreaceRate": ("Endurance des Pals", "Plus haut = les Pals se fatiguent plus vite."),
    "PalAutoHPRegeneRate": ("Régén. des Pals", "Régénération passive des Pals."),
    "PalAutoHpRegeneRateInSleep": ("Régén. des Pals (sommeil)", "Régénération pendant leur repos."),
    "PalEggDefaultHatchingTime": ("Éclosion des œufs (heures)", "Durée d'éclosion. 0 = instantané."),
    "MonsterFarmActionSpeedRate": ("Vitesse du ranch", "Vitesse des travaux du ranch (lait, œufs, laine…)."),
    "EnablePredatorBossPal": ("Pals boss prédateurs", "Des Pals prédateurs puissants peuvent apparaître."),
    "BaseCampMaxNum": ("Bases max (monde)", "Nombre total de bases sur le serveur. Défaut 128."),
    "BaseCampWorkerMaxNum": ("Pals par base", "Défaut 15."),
    "BaseCampMaxNumInGuild": ("Bases par guilde", "Défaut 4."),
    "BuildObjectHpRate": ("Solidité des bâtiments", "Résistance des structures."),
    "BuildObjectDamageRate": ("Dégâts des bâtiments", "Dégâts subis par les constructions."),
    "BuildObjectDeteriorationDamageRate": ("Dégradation des bâtiments",
                                           "0 = les bâtiments ne se dégradent jamais."),
    "MaxBuildingLimitNum": ("Limite de construction", "Pièces max dans le monde. 0 = illimité."),
    "bBuildAreaLimit": ("Construire en zones de base", "Restreint l'emplacement des constructions."),
    "bAllowEnemyCampSpawnNearBaseCamp": ("Camps ennemis près des bases",
                                         "Les ennemis peuvent s'installer près de votre base."),
    "CollectionDropRate": ("Rendement de récolte", "Bois, pierre, minerai… quantité par coup."),
    "CollectionObjectHpRate": ("Dureté des gisements", "Temps pour casser les nœuds de ressources."),
    "CollectionObjectRespawnSpeedRate": ("Vitesse de réapparition", "Rapidité de retour des arbres/minerais."),
    "EnemyDropItemRate": ("Butin des ennemis", "Quantité de butin laissée par les ennemis."),
    "EquipmentDurabilityDamageRate": ("Usure de l'équipement", "0 = armes et armures ne s'usent jamais."),
    "ItemCorruptionMultiplier": ("Vitesse de corruption", "Plus haut = corruption plus vite. 1 = normal."),
    "DropItemMaxNum": ("Objets au sol max", "Limite mondiale d'objets posés. Défaut 3000."),
    "DropItemAliveMaxHours": ("Durée des objets au sol (h)", "Temps de persistance des objets au sol."),
    "SupplyDropSpan": ("Ravitaillement aérien (min)", "Intervalle entre les largages. Défaut 180."),
    "DeathPenalty": ("Pénalité de mort", "Ce que vous perdez en mourant."),
    "bCanPickupOtherGuildDeathPenaltyDrop": ("Ramasser le butin des autres",
                                             "Autorise à prendre les objets perdus par d'autres guildes."),
    "bEnableNonLoginPenalty": ("Faim/maladie hors-ligne", "Les Pals continuent d'avoir faim/maladie en votre absence."),
    "RespawnPenaltyTimeScale": ("Échelle pénalité résurrection", "Multiplie le debuff après réapparition. Défaut 2."),
    "bIsPvP": ("Mode PvP", "Les joueurs peuvent s'affronter."),
    "bEnablePlayerToPlayerDamage": ("Dégâts joueur contre joueur", "Interrupteur de base pour blesser d'autres joueurs."),
    "bEnableFriendlyFire": ("Tir allié", "Vos coups blessent aussi coéquipiers et Pals."),
    "bHardcore": ("Hardcore (mort définitive)", "Mourir supprime votre personnage."),
    "bPalLost": ("Pals perdables", "Les Pals peuvent disparaître définitivement (style hardcore)."),
    "bCharacterRecreateInHardcore": ("Recréer après mort hardcore",
                                     "Autorise un nouveau personnage après une mort hardcore."),
    "GuildPlayerMaxNum": ("Membres de guilde max", "Joueurs par guilde. Défaut 20."),
    "GuildRejoinCooldownMinutes": ("Délai de réintégration (min)", "0 = réintégration immédiate après départ."),
    "bAutoResetGuildNoOnlinePlayers": ("Reset auto des guildes vides",
                                       "La guilde se réinitialise si personne ne se connecte."),
    "AutoResetGuildTimeNoOnlinePlayers": ("Reset après (heures)",
                                          "Heures sans membre en ligne avant reset. Défaut 72."),
    "bEnableFastTravel": ("Voyage rapide", "Téléportation entre points découverts."),
    "bEnableFastTravelOnlyBaseCamp": ("Voyage rapide entre bases", "Limite le voyage rapide à vos bases."),
    "bExistPlayerAfterLogout": ("Personnage reste après déconnexion", "Votre corps reste dans le monde."),
    "bEnableAimAssistPad": ("Assistance visée (manette)", None),
    "bEnableAimAssistKeyboard": ("Assistance visée (souris)", None),
    "bEnableInvaderEnemy": ("Raids de base", "Des ennemis peuvent attaquer votre base."),
    "bActiveUNKO": ("Mécanique de crotte", "…la fonction crotte des Pals. Oui, vraiment."),
    "bEnableVoiceChat": ("Chat vocal", "Chat vocal de proximité sur le serveur."),
    "bIsShowJoinLeftMessage": ("Messages arrivée/départ", "Affiche les connexions dans le chat."),
    "bShowPlayerList": ("Liste des joueurs", "Affiche la liste des joueurs en ligne."),
    "bAllowGlobalPalboxExport": ("Export de Pals par code", "Les Pals peuvent être exportés via codes cross-save."),
    "bAllowGlobalPalboxImport": ("Import de Pals par code", "Les Pals peuvent être importés via codes cross-save."),
    "bAllowEnhanceStat_Health": ("Points +Santé", None),
    "bAllowEnhanceStat_Attack": ("Points +Attaque", None),
    "bAllowEnhanceStat_Stamina": ("Points +Endurance", None),
    "bAllowEnhanceStat_Weight": ("Points +Poids", None),
    "bAllowEnhanceStat_WorkSpeed": ("Points +Vitesse de travail", None),
}


def tr_setting(key, label, hint):
    if LANG == "fr" and key in TR_SETTINGS:
        fr_l, fr_h = TR_SETTINGS[key]
        return fr_l, (fr_h if hint else None)
    return label, hint


def _quote(s):
    s = str(s).replace('"', "")
    return f'"{s}"'


class Tooltip:
    """Small dark hover tooltip for any widget."""

    def __init__(self, widget, text, delay=450):
        self.widget, self.text, self.delay = widget, text, delay
        self._after = None
        self.tip = None
        for seq, fn in (("<Enter>", self._schedule), ("<Leave>", self._hide),
                        ("<ButtonPress>", self._hide)):
            try:
                widget.bind(seq, fn, add="+")
            except NotImplementedError:  # e.g. CTkSegmentedButton
                pass

    def _schedule(self, _e=None):
        self._cancel()
        self._after = self.widget.after(self.delay, self._show)

    def _show(self):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_attributes("-topmost", True)
        lbl = tk.Label(
            self.tip, text=self.text, justify="left",
            bg="#1f2937", fg="#f9fafb", relief="flat",
            padx=10, pady=6, font=("Segoe UI", 10), wraplength=340,
        )
        lbl.pack()
        self.tip.wm_geometry(f"+{x}+{y}")

    def _cancel(self):
        if self._after:
            self.widget.after_cancel(self._after)
            self._after = None

    def _hide(self, _e=None):
        self._cancel()
        if self.tip:
            self.tip.destroy()
            self.tip = None


class App(ctk.CTk):
    PAGES = [
        ("server", "🖥", "Server", "Start, stop and watch your world"),
        ("settings", "⚙", "Settings", "Every gameplay option, in plain language"),
        ("schedule", "⏰", "Schedule", "When the server runs and restarts"),
        ("maint", "🧰", "Maintenance", "Updates, backups and Windows setup"),
        ("console", "📄", "Console", "Live server output"),
        ("prefs", "🎨", "Preferences", "Appearance, language and extras"),
    ]

    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(940, 640)
        if self.cfg_geometry():
            try:
                self.geometry(self.cfg_geometry())
            except tk.TclError:
                self.geometry("1020x720")
        else:
            self.geometry("1020x720")
        self.configure(fg_color=BG)
        self.eval("tk::PlaceWindow . center")
        try:
            self.iconbitmap(os.path.join(BASE, "app.ico"))
        except tk.TclError:
            pass
        self._make_splash()
        self.cfg = load_cfg()
        self.q = queue.Queue()
        self._players = []          # [(name, uid, steamid)]
        self._sel_player = None
        self._busy = False
        self._last_desired = None
        self._events = load_events()
        self._prev_players = set()
        self._public_ip = None
        self._uptime = load_uptime()
        self._up_last_min = 0
        self._crash_times = []
        self._crash_guard = False
        self._was_running = False
        self._fw_cache = (0.0, False)
        self._tray = None
        self._toasts = []
        self._hist_cpu = deque(maxlen=60)
        self._hist_ram = deque(maxlen=60)
        self._pulse_hi = True
        self._update_pending = False
        self._build_id = local_buildid()
        self._bk_sizes = {}
        self._sel_backup = None
        self._last_stats_running = False
        self._geom_after = None
        self._verified = load_verified()
        self._console_follow = True
        self._stor_cache = {"ts": 0.0}
        self._players_hist = load_players_hist()
        self._prof_last_min = 0
        self._console_errs = 0
        self._last_errlog = 0.0
        self._bg_after = None
        self._last_guild_data = None
        self._rcon_fails = 0
        self._zombie_cd = 0.0

        root = ctk.CTkFrame(self, fg_color="transparent")
        root.pack(fill="both", expand=True)
        self._setup_background()

        # ---- sidebar ----
        side = ctk.CTkFrame(root, corner_radius=0, fg_color=SURFACE, width=212)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        if getattr(self, "_art_side", None):
            ctk.CTkLabel(
                side, image=self._art_side, text="",
                height=140,
            ).pack(pady=(14, 6))
        else:
            ctk.CTkLabel(side, text="🐑", font=("Segoe UI", 30)).pack(pady=(20, 0))
        ctk.CTkLabel(side, text="Palworld", font=("Segoe UI", 17, "bold"),
                     text_color=TEXT).pack()
        ctk.CTkLabel(side, text="SERVER MANAGER", font=("Segoe UI", 10, "bold"),
                     text_color=TEXT_DIM).pack(pady=(0, 20))
        self._nav_btns = {}
        for pid, icon, label, _sub in self.PAGES:
            b = ctk.CTkButton(
                side, text=f"  {icon}   {T(label)}", anchor="w", height=42,
                corner_radius=10, font=F_BODY, fg_color="transparent",
                hover_color=SURFACE_2, text_color=TEXT_DIM,
                command=lambda p=pid: self._show_page(p),
            )
            b.pack(fill="x", padx=12, pady=3)
            self._nav_btns[pid] = b
        # full exit (the X button only hides to the tray on purpose)
        self.btn_quit = ctk.CTkButton(
            side, text="⏻  " + T("Turn off the app"), anchor="center",
            height=32, corner_radius=10, font=("Segoe UI", 11, "bold"),
            fg_color="transparent", hover_color=("#fee2e2", "#3b1219"),
            text_color=TEXT_DIM, command=self._confirm_quit_app)
        self.btn_quit.pack(fill="x", padx=12, pady=(6, 2))
        Tooltip(self.btn_quit,
                T("Close the app completely — it stops watching the server "
                  "(the server itself keeps running)."))
        ctk.CTkLabel(side, text="Ctrl+1…6 to switch", font=("Segoe UI", 9),
                     text_color=TEXT_DIM).pack(side="bottom", pady=(2, 6))
        self.side_status = ctk.CTkLabel(side, text="● checking…", font=F_SMALL,
                                        text_color=TEXT_DIM)
        self.side_status.pack(side="bottom", pady=(10, 2))
        ctk.CTkLabel(side, text="v1.0", font=("Segoe UI", 10),
                     text_color=TEXT_DIM).pack(side="bottom", pady=(0, 8))

        # ---- content column ----
        col = ctk.CTkFrame(root, fg_color="transparent")
        col.pack(side="left", fill="both", expand=True)

        topbar = ctk.CTkFrame(col, fg_color="transparent")
        topbar.pack(fill="x", padx=(18, 20), pady=(16, 2))
        tb_left = ctk.CTkFrame(topbar, fg_color="transparent")
        tb_left.pack(side="left")
        self.page_title = ctk.CTkLabel(tb_left, text="", font=(F_DISPLAY, 20, "bold"),
                                       text_color=TEXT, anchor="w")
        self.page_title.pack(anchor="w")
        self.page_sub = ctk.CTkLabel(tb_left, text="", font=F_SMALL,
                                     text_color=TEXT_DIM, anchor="w")
        self.page_sub.pack(anchor="w")
        tb_right = ctk.CTkFrame(topbar, fg_color="transparent")
        tb_right.pack(side="right")
        self.appearance_btn = ctk.CTkSegmentedButton(
            tb_right, values=["🌙", "☀️"], width=84, height=30,
            selected_color=ACCENT_SOFT, selected_hover_color=ACCENT_SOFT,
            unselected_color=SURFACE, fg_color=SURFACE,
            command=self._set_appearance)
        self.appearance_btn.pack(side="right")
        Tooltip(self.appearance_btn, "Switch between dark and light appearance.")
        self.lbl_update = ctk.CTkLabel(
            tb_right, text="  " + T("Update available!") + "  ",
            font=("Segoe UI", 11, "bold"), text_color="#ffffff",
            fg_color=("#d97706", "#b45309"), corner_radius=13, height=26,
            cursor="hand2",
        )
        Tooltip(self.lbl_update,
                "A newer Palworld server version is out — use “Update server” "
                "in Maintenance.")
        self.lbl_update.bind("<Button-1>", lambda e: self._show_page("maint"))
        self.pill = ctk.CTkLabel(
            tb_right, text="  ● checking…  ", font=("Segoe UI", 11, "bold"),
            text_color="#ffffff", fg_color=NEUTRAL, corner_radius=13, height=26,
        )
        self.pill.pack(side="right", padx=(8, 8))
        Tooltip(self.pill, "Live state of the server process.")

        # ---- stacked pages ----
        stack = ctk.CTkFrame(col, fg_color="transparent")
        stack.pack(fill="both", expand=True, padx=(14, 18), pady=(2, 16))
        stack.grid_columnconfigure(0, weight=1)
        stack.grid_rowconfigure(0, weight=1)
        builders = {
            "server": self._build_server_tab,
            "settings": self._build_settings_tab,
            "schedule": self._build_schedule_tab,
            "maint": self._build_maint_tab,
            "console": self._build_console_tab,
            "prefs": self._build_prefs_tab,
        }
        self.pages = {}
        for pid, *_ in self.PAGES:
            page = ctk.CTkFrame(stack, fg_color="transparent")
            page.grid(row=0, column=0, sticky="nsew")
            self.pages[pid] = page
            builders[pid](page)

        self._show_page("server")
        self._load_settings_form()
        self._fetch_public_ip()
        self._refresh_lan_ip()
        self._render_playtimes()
        for i, (pid, *_rest) in enumerate(self.PAGES, start=1):
            self.bind(f"<Control-{i}>", lambda e, p=pid: self._show_page(p))
        self.bind("<Configure>", self._on_configure)
        self.bind("<Control-k>", lambda e: self._open_palette())
        self.bind("<F1>", lambda e: self._show_shortcuts())
        self.bind("<Key-question>", self._shortcut_key)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(400, self._poll_queue)
        self.after(1400, self._pulse_tick)
        threading.Thread(target=self._monitor, daemon=True).start()
        threading.Thread(target=self._update_checker, daemon=True).start()
        threading.Thread(target=self._duckdns_loop, daemon=True).start()
        threading.Thread(target=self._startup_guild_cache, daemon=True).start()
        threading.Thread(target=self._console_tail, daemon=True).start()
        threading.Thread(target=self._storage_loop, daemon=True).start()
        threading.Thread(target=self._ip_watchdog, daemon=True).start()
        self._news_fetch()
        self._setup_tray()
        self.after(700, self._kill_splash)

    def _shortcut_key(self, _e=None):
        # don't trigger while typing in a field
        w = self.focus_get()
        if isinstance(w, (tk.Entry, tk.Text)):
            return
        self._show_shortcuts()

    def _show_shortcuts(self):
        win = ctk.CTkToplevel(self)
        win.title(T("Keyboard shortcuts"))
        win.geometry("440x430")
        win.grab_set()
        try:
            win.attributes("-topmost", True)
        except tk.TclError:
            pass
        body = ctk.CTkFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=18, pady=14)
        ctk.CTkLabel(body, text="⌨  " + T("Keyboard shortcuts"),
                     font=(F_DISPLAY, 18, "bold"), text_color=TEXT).pack(
            anchor="w", pady=(0, 8))
        rows = [
            ("Ctrl + 1 … 6", T("Switch pages (Server, Settings, …)")),
            ("Ctrl + K", T("Command palette — search everything")),
            ("?", T("This shortcuts page")),
            ("F1", T("This shortcuts page")),
            ("Clic droit", T("Context menus: players, backups, guild rows")),
            ("Échap", T("Close dialogs and the palette")),
        ]
        card = ctk.CTkFrame(body, corner_radius=14, fg_color=SURFACE,
                            border_width=1, border_color=BORDER)
        card.pack(fill="x")
        for i, (keys, what) in enumerate(rows):
            r = ctk.CTkFrame(card, fg_color="transparent")
            r.pack(fill="x", padx=14, pady=7)
            ctk.CTkLabel(r, text=keys, font=("Consolas", 12, "bold"),
                         text_color=ACCENT).pack(side="left")
            ctk.CTkLabel(r, text=what, font=F_BODY, text_color=TEXT,
                         anchor="w").pack(side="left", padx=(16, 0))
            if i < len(rows) - 1:
                ctk.CTkFrame(card, height=1, fg_color=BORDER).pack(
                    fill="x", padx=14)
        ctk.CTkLabel(body, text=T("Press Esc or click to close"),
                     font=F_SMALL, text_color=TEXT_DIM).pack(pady=(10, 0))
        win.bind("<Escape>", lambda e: win.destroy())
        win.bind("<Button-1>", lambda e: win.destroy())

    def cfg_geometry(self):
        try:
            cfg = load_cfg()
            return cfg.get("geometry") or ""
        except Exception:
            return ""

    # ===== background artwork =====
    def _setup_background(self):
        """Bake the user's artwork into the identity images: launch splash,
        hero banner and sidebar banner.

        (CustomTkinter's 'transparent' frames paint the window colour, so a
        full-window watermark behind the cards is not possible — instead the
        art is placed where it is guaranteed visible, and its palette tints
        the whole theme.)
        """
        try:
            from PIL import Image, ImageDraw, ImageEnhance
        except ImportError:
            return
        path = os.path.join(BASE, "app", "bg.png")
        if not os.path.exists(path):
            return
        try:
            art = Image.open(path).convert("RGB")
            W, H = art.size

            def rounded(pil, radius):
                mask = Image.new("L", pil.size, 0)
                d = ImageDraw.Draw(mask)
                d.rounded_rectangle([0, 0, pil.size[0] - 1, pil.size[1] - 1],
                                    radius=radius, fill=255)
                out = pil.convert("RGBA")
                out.putalpha(mask)
                return out

            def vscrim(pil, start_frac, peak):
                """Darken progressively towards the bottom so overlaid white
                text stays readable on any artwork."""
                w, h = pil.size
                scrim = Image.new("L", (w, h), 0)
                d = ImageDraw.Draw(scrim)
                y0 = int(h * start_frac)
                for y in range(y0, h):
                    t = (y - y0) / max(1, h - y0)
                    d.line([(0, y), (w, y)], fill=int(peak * (t ** 1.2)))
                dark = Image.new("RGBA", (w, h), (7, 11, 20, 255))
                return Image.composite(dark, pil.convert("RGBA"), scrim)

            # hero banner: wide band from the middle of the artwork
            band = art.crop((0, int(H * 0.16), W, int(H * 0.60)))
            band = band.resize((960, 230), Image.LANCZOS)
            band = ImageEnhance.Brightness(band).enhance(0.72)
            band = ImageEnhance.Color(band).enhance(0.92)
            band = vscrim(band, 0.28, 165)
            self._art_hero = ctk.CTkImage(rounded(band, 24), size=(960, 230))

            # sidebar banner: squarish crop from the left
            side = art.crop((0, 0, int(W * 0.50), int(H * 0.58)))
            side = side.resize((184, 140), Image.LANCZOS)
            side = ImageEnhance.Brightness(side).enhance(0.58)
            self._art_side = ctk.CTkImage(rounded(side, 20), size=(184, 140))
        except Exception:
            pass

    # ===== launch splash =====
    def _make_splash(self):
        """Full-bleed artwork splash shown while the main UI builds."""
        try:
            from PIL import Image, ImageDraw, ImageEnhance, ImageFont
        except ImportError:
            return
        path = os.path.join(BASE, "app", "bg.png")
        if not os.path.exists(path):
            return
        try:
            art = Image.open(path).convert("RGB")
            W, H = art.size
            img = art.crop((0, 0, W, int(H * 0.66)))
            img = img.resize((780, 440), Image.LANCZOS)
            img = ImageEnhance.Color(img).enhance(1.05)
            img = img.convert("RGBA")
            w, h = img.size
            scrim = Image.new("L", (w, h), 0)
            d = ImageDraw.Draw(scrim)
            y0 = int(h * 0.52)
            for y in range(y0, h):
                t = (y - y0) / max(1, h - y0)
                d.line([(0, y), (w, y)], fill=int(215 * (t ** 1.1)))
            dark = Image.new("RGBA", (w, h), (6, 10, 20, 255))
            img = Image.composite(dark, img, scrim)
            d = ImageDraw.Draw(img)

            def font(paths, size):
                for p in paths:
                    try:
                        return ImageFont.truetype(p, size)
                    except OSError:
                        continue
                return ImageFont.load_default()

            f_big = font([r"C:\Windows\Fonts\seguisb.ttf",
                          r"C:\Windows\Fonts\segoeuib.ttf"], 36)
            f_sm = font([r"C:\Windows\Fonts\segoeui.ttf"], 16)
            title, sub = "MY PALWORLD SERVER", "Palworld Server Manager"
            tw = d.textlength(title, font=f_big)
            d.text(((w - tw) / 2, h - 96), title, font=f_big,
                   fill=(255, 255, 255, 255))
            sw = d.textlength(sub, font=f_sm)
            d.text(((w - sw) / 2, h - 46), sub, font=f_sm,
                   fill=(168, 200, 232, 255))
            self._splash_photo = ctk.CTkImage(img, size=(780, 440))

            sp = ctk.CTkToplevel(self)
            sp.overrideredirect(True)
            sp.attributes("-topmost", True)
            sp.geometry("+%d+%d" % (
                max(0, self.winfo_screenwidth() // 2 - 390),
                max(0, self.winfo_screenheight() // 2 - 260)))
            ctk.CTkLabel(sp, image=self._splash_photo, text="",
                         corner_radius=0).pack()
            self._splash = sp
            self.withdraw()
            sp.update_idletasks()
            sp.update()
        except Exception:
            pass

    def _kill_splash(self):
        sp = getattr(self, "_splash", None)
        if not sp:
            return

        def fade(alpha):
            try:
                sp.attributes("-alpha", alpha)
                if alpha > 0.05:
                    self.after(40, lambda: fade(round(alpha - 0.10, 2)))
                else:
                    sp.destroy()
                    self.deiconify()
            except tk.TclError:
                self.deiconify()

        self.after(900, lambda: fade(1.0))

    # ===== shared helpers =====
    def _show_page(self, pid):
        self.pages[pid].tkraise()
        for p, _icon, label, sub in self.PAGES:
            b = self._nav_btns[p]
            if p == pid:
                b.configure(fg_color=ACCENT_SOFT, text_color=ACCENT,
                            font=F_BODY_B)
                self.page_title.configure(text=T(label))
                self.page_sub.configure(text=T(sub))
            else:
                b.configure(fg_color="transparent", text_color=TEXT_DIM,
                            font=F_BODY)

    def _set_appearance(self, value):
        mode = "Dark" if value.startswith("🌙") else "Light"
        ctk.set_appearance_mode(mode)
        self.cfg["appearance"] = mode
        save_cfg(self.cfg)
        self._refresh_theme()
        try:
            self.lift()
        except tk.TclError:
            pass

    def _refresh_theme(self):
        """Re-paint raw tk widgets after an appearance switch — CTk handles its
        own widgets, but tk.Canvas backgrounds and textbox tag colours are set
        once at build time and must be redone (else light mode shows dark
        canvases / unreadable text)."""
        for name in ("cv_cpu", "cv_ram", "canvas_map", "canvas_week",
                     "canvas_players"):
            cv = getattr(self, name, None)
            if cv is not None:
                try:
                    cv.configure(bg=self._hex(SURFACE))
                except tk.TclError:
                    pass
        try:
            self._draw_spark(self.cv_cpu, self._hist_cpu)
            self._draw_spark(self.cv_ram, self._hist_ram)
            self._draw_week()
            self._draw_players()
            if getattr(self, "_map_cache", None):
                self._render_map(self._map_cache)
        except (tk.TclError, AttributeError):
            pass
        try:
            self.txt_console.tag_config(
                "err", foreground=self._hex(("#b91c1c", "#f87171")))
            self.txt_console.tag_config(
                "warn", foreground=self._hex(("#b45309", "#fbbf24")))
        except (tk.TclError, AttributeError):
            pass

    def _card(self, parent, title=None, subtitle=None):
        card = ctk.CTkFrame(parent, corner_radius=16, fg_color=SURFACE,
                            border_width=1, border_color=BORDER)
        card.pack(fill="x", padx=6, pady=7)
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=18, pady=(12, 16))
        if title:
            tt = ctk.CTkFrame(inner, fg_color="transparent")
            tt.pack(anchor="w", pady=(4, 0))
            ctk.CTkLabel(tt, text="▍", font=(F_H2[0], 15, "bold"),
                         text_color=ACCENT).pack(side="left")
            ctk.CTkLabel(tt, text=T(title), font=F_H2, anchor="w",
                         text_color=TEXT).pack(side="left", padx=(6, 0))
        if subtitle:
            ctk.CTkLabel(inner, text=T(subtitle), font=F_SMALL, text_color=TEXT_DIM,
                         anchor="w", justify="left").pack(anchor="w", pady=(0, 6))
        return inner

    def _tile(self, parent, col, caption, value="—", spark=False):
        tile = ctk.CTkFrame(parent, corner_radius=16, fg_color=SURFACE,
                            border_width=1, border_color=BORDER)
        tile.grid(row=0, column=col, sticky="ew", padx=6)
        ctk.CTkLabel(tile, text=T(caption), font=("Segoe UI", 10, "bold"),
                     text_color=TEXT_DIM, anchor="w").pack(anchor="w", padx=16,
                                                           pady=(12, 0))
        v = ctk.CTkLabel(tile, text=value, font=(F_DISPLAY, 20, "bold"),
                         text_color=TEXT, anchor="w")
        v.pack(anchor="w", padx=16, pady=(0, 2 if spark else 12))
        cv = None
        if spark:
            cv = tk.Canvas(tile, height=20, width=90, bg=self._hex(SURFACE),
                           highlightthickness=0)
            cv.pack(anchor="w", padx=16, pady=(0, 10))
        return v, cv

    # ===== toasts =====
    def _toast(self, text, icon="✅"):
        t = ctk.CTkFrame(self, corner_radius=12, fg_color=SURFACE,
                         border_width=1, border_color=ACCENT)
        ctk.CTkLabel(t, text=f"{icon}  {text}", font=F_BODY_B,
                     text_color=TEXT).pack(padx=16, pady=9)
        self._toasts.append(t)
        self._layout_toasts()
        self.after(2600, lambda: self._close_toast(t))

    def _layout_toasts(self):
        for i, t in enumerate(reversed(self._toasts[-4:])):
            try:
                t.place(relx=0.985, rely=0.985, anchor="se", y=-14 - i * 58)
            except tk.TclError:
                pass

    def _close_toast(self, t):
        if t in self._toasts:
            self._toasts.remove(t)
        try:
            t.destroy()
        except tk.TclError:
            pass
        self._layout_toasts()

    # ===== window geometry memory =====
    def _on_configure(self, event):
        if event.widget is not self:
            return
        if self._geom_after:
            self.after_cancel(self._geom_after)
        self._geom_after = self.after(900, self._save_geometry)

    def _save_geometry(self):
        try:
            g = self.geometry()
            if g and self.winfo_width() > 100:
                self.cfg["geometry"] = g
                save_cfg(self.cfg)
        except tk.TclError:
            pass

    # ===== Server page =====
    def _build_server_tab(self, t):
        scroll = ctk.CTkScrollableFrame(t, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        # crash-guard banner (hidden until needed)
        banner = ctk.CTkFrame(scroll, corner_radius=12,
                              fg_color=("#fef3c7", "#3a2b0b"),
                              border_width=1, border_color=("#f59e0b", "#7c5c0e"))
        self._crash_banner = banner
        brow = ctk.CTkFrame(banner, fg_color="transparent")
        brow.pack(fill="x", padx=14, pady=10)
        self.lbl_crash = ctk.CTkLabel(
            brow, text="⚠  " + T("Crash protection active") + " — " +
            T("The server kept crashing — auto-restart paused."),
            font=F_BODY_B, text_color=("#92400e", "#fbbf24"), anchor="w",
            justify="left",
        )
        self.lbl_crash.pack(side="left", fill="x", expand=True)
        self.btn_resume_crash = ctk.CTkButton(
            brow, text=T("Resume auto-restart"), height=32, corner_radius=8,
            fg_color=("#d97706", "#b45309"), hover_color=("#b45309", "#92400e"),
            text_color="#ffffff", command=self._resume_watchdog,
        )
        self.btn_resume_crash.pack(side="right")

        hero = self._card(scroll)
        if getattr(self, "_art_hero", None):
            self.lbl_status = ctk.CTkLabel(
                hero, image=self._art_hero, text="Checking…",
                compound="center", font=(F_DISPLAY, 20, "bold"),
                text_color="#ffffff", justify="center",
            )
            self.lbl_status.pack(fill="x", pady=(0, 4))
        else:
            self.lbl_status = ctk.CTkLabel(hero, text="Checking…",
                                           font=F_STATUS, text_color=TEXT)
            self.lbl_status.pack(anchor="w")
        self.lbl_next = ctk.CTkLabel(hero, text="", font=F_SMALL, text_color=TEXT_DIM)
        self.lbl_next.pack(anchor="w", pady=(2, 2))
        self.chips_frame = ctk.CTkFrame(hero, fg_color="transparent")
        self.chips_frame.pack(anchor="w", fill="x", pady=(2, 2))
        self.btn_finish_setup = ctk.CTkButton(
            hero, text=T("🚀  Finish setup"), font=("Segoe UI", 13, "bold"),
            height=40, corner_radius=10, fg_color=ACCENT,
            hover_color=ACCENT_HOVER, text_color="#ffffff",
            command=self._open_finish_setup,
        )
        Tooltip(self.btn_finish_setup,
                "Walk through the remaining steps so friends can connect.")

        tiles = ctk.CTkFrame(scroll, fg_color="transparent")
        tiles.pack(fill="x", padx=6, pady=(2, 7))
        for i in range(4):
            tiles.grid_columnconfigure(i, weight=1, uniform="t")
        self.t_uptime, _ = self._tile(tiles, 0, "UPTIME")
        self.t_ram, self.cv_ram = self._tile(tiles, 1, "MEMORY", spark=True)
        self.t_cpu, self.cv_cpu = self._tile(tiles, 2, "CPU", spark=True)
        self.t_players, _ = self._tile(tiles, 3, "PLAYERS ONLINE")

        c2 = self._card(scroll)
        row = ctk.CTkFrame(c2, fg_color="transparent")
        row.pack(fill="x")
        self.btn_start = ctk.CTkButton(
            row, text=T("▶   Start"), font=("Segoe UI", 13, "bold"), height=48,
            corner_radius=12, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color="#ffffff", command=self._do_start,
        )
        self.btn_stop = ctk.CTkButton(
            row, text=T("⏹   Stop"), font=("Segoe UI", 13, "bold"), height=48,
            corner_radius=12, fg_color=RED, hover_color=RED_HOVER,
            text_color="#ffffff", command=self._do_stop,
        )
        self.btn_restart = ctk.CTkButton(
            row, text=T("↻   Restart"), font=("Segoe UI", 13, "bold"), height=48,
            corner_radius=12, fg_color=BLUE, hover_color=BLUE_HOVER,
            text_color="#ffffff", command=self._do_restart,
        )
        for b, tip in (
            (self.btn_start, "Turn the server on so friends can join."),
            (self.btn_stop, "Save the world, then shut the server down."),
            (self.btn_restart, "Stop and start again — needed after changing settings."),
        ):
            b.pack(side="left", expand=True, fill="x", padx=4)
            Tooltip(b, T(tip))
        ctk.CTkLabel(
            c2, text=T("Stop always saves the world first, so nothing is lost."),
            font=F_SMALL, text_color=TEXT_DIM,
        ).pack(anchor="w", pady=(8, 0))

        # ----- invite card -----
        inv = self._card(scroll, "Invite your friends",
                         "One click copies everything they need — no explaining needed.")
        rpub = ctk.CTkFrame(inv, fg_color="transparent")
        rpub.pack(fill="x", pady=3)
        ctk.CTkLabel(rpub, text=T("🌍   Public address"), font=F_BODY,
                     text_color=TEXT).pack(side="left")
        self.btn_iprefresh = ctk.CTkButton(rpub, text="↻", width=36, height=28,
                                           corner_radius=8, fg_color=SURFACE_2,
                                           hover_color=BORDER,
                                           command=self._fetch_public_ip)
        self.btn_iprefresh.pack(side="right")
        Tooltip(self.btn_iprefresh, "Detect your public IP address again "
                                    "(useful after your internet box changes it).")
        self.lbl_pub = ctk.CTkLabel(rpub, text="detecting…", font=("Consolas", 12, "bold"),
                                    text_color=TEXT)
        self.lbl_pub.pack(side="right", padx=10)
        rlan = ctk.CTkFrame(inv, fg_color="transparent")
        rlan.pack(fill="x", pady=3)
        ctk.CTkLabel(rlan, text=T("🏠   Same Wi-Fi address"), font=F_BODY,
                     text_color=TEXT).pack(side="left")
        self.lbl_lan = ctk.CTkLabel(rlan, text="…", font=("Consolas", 12),
                                    text_color=TEXT)
        self.lbl_lan.pack(side="right", padx=10)
        rpw = ctk.CTkFrame(inv, fg_color="transparent")
        rpw.pack(fill="x", pady=3)
        ctk.CTkLabel(rpw, text=T("🔑   Password"), font=F_BODY,
                     text_color=TEXT).pack(side="left")
        self.lbl_pw = ctk.CTkLabel(rpw, text="…", font=("Consolas", 12, "bold"),
                                   text_color=TEXT)
        self.lbl_pw.pack(side="right", padx=10)
        rbtn = ctk.CTkFrame(inv, fg_color="transparent")
        rbtn.pack(fill="x", pady=(10, 0))
        self.btn_invite = ctk.CTkButton(
            rbtn, text="📋   " + T("Copy invite message"), font=("Segoe UI", 13, "bold"),
            height=46, corner_radius=12, fg_color=ACCENT,
            hover_color=ACCENT_HOVER, text_color="#ffffff",
            command=self._copy_invite,
        )
        self.btn_invite.pack(side="left", expand=True, fill="x")
        Tooltip(self.btn_invite,
                T("Copies a ready-to-paste message with the address, password and "
                  "join steps. Send it to your friends on Discord/WhatsApp!"))
        self.btn_addr = ctk.CTkButton(
            rbtn, text=T("Copy address only"), height=46, corner_radius=12,
            fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER, text_color="#ffffff",
            command=self._copy_addr,
        )
        self.btn_addr.pack(side="left", padx=(8, 0))
        Tooltip(self.btn_addr, "Copies just the IP:PORT address.")
        self.btn_invcard = ctk.CTkButton(
            rbtn, text="🖼", width=52, height=46, corner_radius=12,
            fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER, text_color="#ffffff",
            font=("Segoe UI Emoji", 16),
            command=self._export_invite_card,
        )
        self.btn_invcard.pack(side="left", padx=(8, 0))
        Tooltip(self.btn_invcard,
                T("Export a pretty invite image (address + optional password "
                  "+ QR code) to share in group chats."))

        # ----- checklist card -----
        chk = self._card(scroll, "Setup checklist",
                         "Everything your friends need to connect, in one place.")
        self.chk_rows = {}
        for item in ("Server running", "Firewall port open (UDP 8211)",
                     "Router port-forward done", "Public address known",
                     "Invite ready to send"):
            r = ctk.CTkFrame(chk, fg_color="transparent")
            r.pack(fill="x", pady=3)
            g = ctk.CTkLabel(r, text="…", font=("Segoe UI", 13, "bold"), width=3)
            g.pack(side="left")
            l = ctk.CTkLabel(r, text=T(item), font=F_BODY, anchor="w")
            l.pack(side="left", fill="x", expand=True, padx=(2, 10))
            self.chk_rows[item] = (g, l, r)
        rr = self.chk_rows["Router port-forward done"][2]
        self.btn_router = ctk.CTkButton(rr, text=T("Open router page"), width=130,
                                        height=28, corner_radius=8,
                                        fg_color=SURFACE_2, hover_color=BORDER,
                                        command=lambda: webbrowser.open("http://192.168.0.1"))
        self.btn_router.pack(side="right", padx=4)
        self.btn_router_done = ctk.CTkButton(rr, text=T("Mark done"), width=90,
                                             height=28, corner_radius=8,
                                             fg_color=ACCENT_SOFT,
                                             hover_color=BORDER,
                                             text_color=ACCENT,
                                             command=self._toggle_router_done)
        self.btn_router_done.pack(side="right")

        # ----- players -----
        c3 = self._card(scroll, "Players online",
                        "Click a player to select them, then use the buttons below "
                        "(or right-click).")
        self.plr_frame = ctk.CTkScrollableFrame(c3, height=190, fg_color="transparent")
        self.plr_frame.pack(fill="x")
        row3 = ctk.CTkFrame(c3, fg_color="transparent")
        row3.pack(fill="x", pady=(10, 0))
        self.ent_msg = ctk.CTkEntry(
            row3, height=36, corner_radius=10, fg_color=SURFACE_2, border_width=0,
            placeholder_text="Message to send to everyone on the server…",
        )
        self.ent_msg.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.btn_send = ctk.CTkButton(row3, text="📣  " + T("Send"), width=96, height=36,
                                      corner_radius=10, fg_color=ACCENT,
                                      hover_color=ACCENT_HOVER,
                                      command=self._broadcast)
        self.btn_send.pack(side="left")
        Tooltip(self.btn_send, "Shows your message on every player's screen in-game.")
        row4 = ctk.CTkFrame(c3, fg_color="transparent")
        row4.pack(fill="x", pady=(8, 0))
        self.btn_kick = ctk.CTkButton(row4, text=T("Kick"), width=96, height=34,
                                      corner_radius=10, fg_color=NEUTRAL,
                                      hover_color=NEUTRAL_HOVER, command=self._kick)
        self.btn_ban = ctk.CTkButton(row4, text=T("Ban"), width=96, height=34,
                                     corner_radius=10, fg_color=RED,
                                     hover_color=RED_HOVER, command=self._ban)
        self.btn_save = ctk.CTkButton(row4, text="💾  " + T("Save world now"), height=34,
                                      corner_radius=10, fg_color=ACCENT,
                                      hover_color=ACCENT_HOVER,
                                      command=self._save_world)
        self.btn_kick.pack(side="left")
        self.btn_ban.pack(side="left", padx=(6, 0))
        self.btn_save.pack(side="right")
        Tooltip(self.btn_kick, "Remove the selected player from the server (they can rejoin).")
        Tooltip(self.btn_ban, "Permanently block the selected player from coming back.")
        Tooltip(self.btn_save, "Force an immediate save of the world. Handy before updates.")

        # ----- world & guild -----
        guild = self._card(scroll, "World & guild",
                           "From the world save — levels, Pals and last seen per member.")
        grow = ctk.CTkFrame(guild, fg_color="transparent")
        grow.pack(fill="x", pady=(2, 4))
        self.lbl_guild_scan = ctk.CTkLabel(grow, text="", font=F_SMALL,
                                           text_color=TEXT_DIM, anchor="w")
        self.lbl_guild_scan.pack(side="left")
        self.btn_scan = ctk.CTkButton(grow, text="🔍  " + T("Scan world"), height=34,
                                      corner_radius=10, fg_color=BLUE,
                                      hover_color=BLUE_HOVER, text_color="#ffffff",
                                      command=self._scan_world)
        self.btn_scan.pack(side="right")
        Tooltip(self.btn_scan, "Reads the save file (takes ~1 min while the "
                               "server runs). Shows guild members, levels, Pals.")
        self.btn_palbox = ctk.CTkButton(grow, text="🐾  " + T("Pal boxes"),
                                        height=34, corner_radius=10,
                                        fg_color=NEUTRAL,
                                        hover_color=NEUTRAL_HOVER,
                                        text_color="#ffffff",
                                        command=self._open_palbox)
        self.btn_palbox.pack(side="right", padx=(6, 0))
        Tooltip(self.btn_palbox, "Browse any guild member's full Pal collection "
                                 "with levels and passives.")
        self.btn_guildcard = ctk.CTkButton(grow, text="🃏  " + T("Guild card"),
                                           height=34, corner_radius=10,
                                           fg_color=NEUTRAL,
                                           hover_color=NEUTRAL_HOVER,
                                           text_color="#ffffff",
                                           command=self._export_guild_card)
        self.btn_guildcard.pack(side="right", padx=(6, 0))
        Tooltip(self.btn_guildcard,
                "Export a shareable image of the guild (members, levels, Pals) "
                "to share with friends.")
        self.guild_frame = ctk.CTkFrame(guild, fg_color="transparent")
        self.guild_frame.pack(fill="x")
        ctk.CTkLabel(self.guild_frame, text="—", font=F_SMALL,
                     text_color=TEXT_DIM, anchor="w").pack(anchor="w")

        # ----- inventories (from the world save) -----
        invc = self._card(scroll, "Inventories",
                          T("Gold and most-stocked items per player, from the "
                            "world save — the friendly troll panel."))
        self.inv_frame = ctk.CTkFrame(invc, fg_color="transparent")
        self.inv_frame.pack(fill="x")
        ctk.CTkLabel(self.inv_frame, text="—", font=F_SMALL,
                     text_color=TEXT_DIM, anchor="w").pack(anchor="w")

        # ----- gifts & events -----
        gfc = self._card(scroll, "Gifts & events",
                         T("Give gold, items or Pals — written straight into "
                           "the world save, no mods. Schedule recurring ones "
                           "as events."))
        rg = ctk.CTkFrame(gfc, fg_color="transparent")
        rg.pack(fill="x", pady=(0, 6))
        ctk.CTkButton(rg, text="🎁  " + T("Give a gift now"), height=40,
                      corner_radius=10, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, text_color="#ffffff",
                      command=self._open_gift_wizard).pack(side="left")
        Tooltip(rg, T("Gold, items and Pals for one player or the whole "
                      "guild. A safety backup is made first."))
        self.ge_frame = ctk.CTkFrame(gfc, fg_color="transparent")
        self.ge_frame.pack(fill="x")
        ctk.CTkLabel(self.ge_frame, font=F_SMALL, text_color=TEXT_DIM,
                     anchor="w", text=T("No scheduled gift events yet.")
                     ).pack(anchor="w")
        rgb = ctk.CTkFrame(gfc, fg_color="transparent")
        rgb.pack(fill="x", pady=(4, 0))
        ctk.CTkButton(rgb, text="➕  " + T("Add gift event"), height=32,
                      corner_radius=8, fg_color=SURFACE_2, hover_color=BORDER,
                      command=lambda: self._add_ge_row("20:00", 50000, "", "",
                                                       True)).pack(side="left")
        ctk.CTkButton(rgb, text="💾  " + T("Save"), height=32, corner_radius=8,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color="#ffffff",
                      command=self._save_ge).pack(side="left", padx=(8, 0))
        self._ge_rows = []
        for evd in (self.cfg.get("gift_events") or [])[:6]:
            self._add_ge_row(evd.get("time", "20:00"), evd.get("gold", 0),
                             evd.get("items", ""), evd.get("pal", ""),
                             evd.get("enabled", True))

        # ----- base map -----
        mapc = self._card(scroll, "Base map",
                          "Positions of the bases found in the world save.")
        self.canvas_map = tk.Canvas(mapc, height=240, bg=self._hex(SURFACE),
                                    highlightthickness=0)
        self.canvas_map.pack(fill="x")
        self.lbl_map_info = ctk.CTkLabel(mapc, text="—", font=F_SMALL,
                                         text_color=TEXT_DIM, anchor="w")
        self.lbl_map_info.pack(anchor="w", pady=(4, 0))
        self.canvas_map.bind(
            "<Motion>", self._map_hover)

        # ----- playtime -----
        ptc = self._card(scroll, "Playtime this week",
                         "Who's been grinding, according to the activity log.")
        self.pt_frame = ctk.CTkFrame(ptc, fg_color="transparent")
        self.pt_frame.pack(fill="x")
        ctk.CTkLabel(self.pt_frame, text="—", font=F_SMALL,
                     text_color=TEXT_DIM, anchor="w").pack(anchor="w")

        # ----- sessions timeline -----
        tlc = self._card(scroll, "Sessions — last 7 days",
                         T("When each player was online, day by day."))
        self.lbl_timeline = ctk.CTkLabel(tlc, text="", font=F_SMALL,
                                         text_color=TEXT_DIM, anchor="w")
        self.lbl_timeline.pack(anchor="w")
        self.cv_timeline = tk.Canvas(tlc, height=90, bg=self._hex(SURFACE),
                                     highlightthickness=0)
        self.cv_timeline.pack(fill="x")
        self.after(1200, self._draw_timeline)

        # ----- uptime graph -----
        upc = self._card(scroll, "This week",
                         "Server availability, day by day.")
        self.lbl_weekpct = ctk.CTkLabel(upc, text="", font=("Segoe UI", 13, "bold"),
                                        text_color=TEXT, anchor="w")
        self.lbl_weekpct.pack(anchor="w", pady=(0, 6))
        self.canvas_week = tk.Canvas(upc, height=110, bg=self._hex(SURFACE),
                                     highlightthickness=0)
        self.canvas_week.pack(fill="x")
        self.lbl_weekrel = ctk.CTkLabel(upc, text="", font=F_SMALL,
                                        text_color=TEXT_DIM, anchor="w")
        self.lbl_weekrel.pack(anchor="w", pady=(8, 4))
        ctk.CTkLabel(upc, text=T("Peak players per day"),
                     font=("Segoe UI", 10, "bold"), text_color=TEXT_DIM,
                     anchor="w").pack(anchor="w")
        self.canvas_players = tk.Canvas(upc, height=64, bg=self._hex(SURFACE),
                                        highlightthickness=0)
        self.canvas_players.pack(fill="x")

        # ----- activity -----
        act = self._card(scroll, "Recent activity",
                         "Joins, leaves, restarts and maintenance — kept between "
                         "app restarts.")
        self.txt_activity = ctk.CTkTextbox(act, height=140, font=("Consolas", 11),
                                           fg_color=SURFACE_2, corner_radius=10)
        self.txt_activity.pack(fill="x")
        self.txt_activity.configure(state="disabled")
        if self._events:
            self.txt_activity.configure(state="normal")
            for line in self._events[-60:]:
                self.txt_activity.insert("end", line + "\n")
            self.txt_activity.see("end")
            self.txt_activity.configure(state="disabled")

    # ===== Console page =====
    def _build_console_tab(self, t):
        card = self._card(t, "Server console",
                          "Live server output — errors, connections, warnings. "
                          "Captured from the next server start onwards.")
        toolbar = ctk.CTkFrame(card, fg_color="transparent")
        toolbar.pack(fill="x", pady=(0, 6))
        self.var_follow = tk.BooleanVar(value=True)

        def _toggle_follow():
            self._console_follow = bool(self.var_follow.get())
        ctk.CTkSwitch(toolbar, text="Auto-scroll", variable=self.var_follow,
                      command=_toggle_follow).pack(side="left")
        ctk.CTkButton(toolbar, text="🧹  Clear", width=90, height=28,
                      corner_radius=8, fg_color=SURFACE_2, hover_color=BORDER,
                      command=lambda: self.txt_console.delete("1.0", "end")
                      ).pack(side="left", padx=(10, 0))
        ctk.CTkButton(toolbar, text="📂  Open file", width=110, height=28,
                      corner_radius=8, fg_color=SURFACE_2, hover_color=BORDER,
                      command=lambda: os.startfile(CONSOLE_LOG)
                      ).pack(side="left", padx=(10, 0))
        self.lbl_console_state = ctk.CTkLabel(toolbar, text="", font=F_SMALL,
                                              text_color=TEXT_DIM)
        self.lbl_console_state.pack(side="right")
        self.lbl_console_errs = ctk.CTkLabel(
            toolbar, text="", font=("Segoe UI", 10, "bold"), text_color="#ffffff",
            fg_color=("#d97706", "#b45309"), corner_radius=11, height=24,
        )
        self.txt_console = ctk.CTkTextbox(card, font=("Consolas", 10),
                                          fg_color=SURFACE_2, corner_radius=10)
        self.txt_console.pack(fill="both", expand=True)
        self.txt_console.tag_config("err", foreground=self._hex(("#b91c1c", "#f87171")))
        self.txt_console.tag_config("warn", foreground=self._hex(("#b45309", "#fbbf24")))

    def _console_tail(self):
        pos = 0
        while True:
            try:
                if os.path.exists(CONSOLE_LOG):
                    size = os.path.getsize(CONSOLE_LOG)
                    if size < pos:
                        pos = 0  # log truncated by a new server start
                    if size > pos:
                        with open(CONSOLE_LOG, "rb") as f:
                            f.seek(pos)
                            chunk = f.read(min(size - pos, 65536))
                        pos += len(chunk)
                        self.q.put(("console", chunk.decode("utf-8", "replace")))
            except OSError:
                pass
            time.sleep(2)

    def _append_console(self, text):
        self.txt_console.configure(state="normal")
        n_err = 0
        for line in text.splitlines(True):
            low = line.lower()
            tag = None
            if any(k in low for k in ("error", "fatal", "assert", "failed")):
                tag = "err"
                n_err += 1
            elif "warn" in low:
                tag = "warn"
            self.txt_console.insert("end", line, tag or ())
        lines = int(self.txt_console.index("end-1c").split(".")[0])
        if lines > 4000:
            self.txt_console.delete("1.0", "2000.0")
        if self._console_follow:
            self.txt_console.see("end")
        self.txt_console.configure(state="disabled")
        if n_err:
            self._console_errs += n_err
            try:
                self.lbl_console_errs.configure(text=f"  ⚠ {self._console_errs}  ")
                if not self.lbl_console_errs.winfo_ismapped():
                    self.lbl_console_errs.pack(side="right", padx=(0, 8))
            except tk.TclError:
                pass
            if time.time() - self._last_errlog > 300:
                self._last_errlog = time.time()
                self._log_event(f"⚠ {n_err} console error(s) detected — see Console")

    # ===== Settings page =====
    def _build_settings_tab(self, t):
        scroll = ctk.CTkScrollableFrame(t, fg_color="transparent")
        scroll.pack(fill="both", expand=True)
        search = ctk.CTkEntry(
            scroll, height=38, corner_radius=10, fg_color=SURFACE,
            border_width=1, border_color=BORDER,
            placeholder_text=T("Search the settings… (name, effect or keyword)"),
        )
        search.pack(fill="x", padx=6, pady=(2, 8))
        self._settings_search = search
        search.bind("<KeyRelease>", lambda e: self._filter_settings(search.get()))

        # --- one-click rule presets ---
        PRESETS = [
            ("🕊", T("Peaceful"), "peaceful",
             T("No PvP, nothing lost on death — chill building with friends.")),
            ("⚖", T("Normal"), "normal",
             T("The vanilla experience — drop items on death.")),
            ("💀", T("Hardcore"), "hardcore",
             T("Drop EVERYTHING on death — for the brave.")),
            ("⚔", T("PvP"), "pvp",
             T("Guild wars: players can fight, equipment drops on death.")),
        ]
        prs = ctk.CTkFrame(scroll, fg_color="transparent")
        prs.pack(fill="x", padx=6, pady=(0, 6))
        for i in range(4):
            prs.grid_columnconfigure(i, weight=1, uniform="p")
        for i, (icon, label, pid, desc) in enumerate(PRESETS):
            b = ctk.CTkButton(prs, text=f"{icon}  {label}", height=46,
                              corner_radius=12, font=F_BODY_B,
                              fg_color=SURFACE, hover_color=SURFACE_2,
                              border_width=1, border_color=BORDER,
                              text_color=TEXT,
                              command=lambda p=pid: self._apply_preset(p))
            b.grid(row=0, column=i, sticky="ew", padx=3)
            Tooltip(b, desc + "\n" + T("Applies the rules and offers a restart."))

        self._fields = {}   # key -> (widget, kind, boolvar-or-None)
        self._settings_rows = {}
        self._settings_cards = {}
        for sec_id, title, subtitle in SECTIONS:
            card = ctk.CTkFrame(scroll, corner_radius=16, fg_color=SURFACE,
                                border_width=1, border_color=BORDER)
            card.pack(fill="x", padx=6, pady=7)
            self._settings_cards[sec_id] = card
            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="both", expand=True, padx=18, pady=(12, 16))
            ctk.CTkLabel(inner, text=T(title), font=F_H2, anchor="w",
                         text_color=TEXT).pack(anchor="w", pady=(4, 0))
            ctk.CTkLabel(inner, text=T(subtitle), font=F_SMALL,
                         text_color=TEXT_DIM, anchor="w",
                         justify="left").pack(anchor="w", pady=(0, 6))
            grid = ctk.CTkFrame(inner, fg_color="transparent")
            grid.pack(fill="x")
            grid.columnconfigure(0, weight=1)
            r = 0
            for sec, key, label, hint, kind, extra in PLAYFIELDS:
                if sec != sec_id:
                    continue
                label, hint = tr_setting(key, label, hint)
                lab = ctk.CTkFrame(grid, fg_color="transparent")
                lab.grid(row=r, column=0, sticky="ew", pady=7, padx=(0, 12))
                ctk.CTkLabel(lab, text=label, font=F_BODY, anchor="w").pack(anchor="w")
                if hint:
                    ctk.CTkLabel(lab, text=hint, font=F_SMALL, text_color=TEXT_DIM,
                                 anchor="w", justify="left").pack(anchor="w")
                var = None
                if kind == "str":
                    w = ctk.CTkEntry(grid, width=240, fg_color=SURFACE_2,
                                     border_width=0)
                    if "password" in key.lower():
                        w.configure(show="•")
                elif kind == "bool":
                    var = tk.BooleanVar()
                    w = ctk.CTkSwitch(grid, text="", variable=var, width=56)
                elif kind in ("int", "float", "mins"):
                    w = ctk.CTkEntry(grid, width=110, fg_color=SURFACE_2,
                                     border_width=0)
                else:  # enum
                    w = ctk.CTkOptionMenu(grid, values=extra, width=140,
                                          fg_color=SURFACE_2,
                                          button_color=BORDER,
                                          button_hover_color=TEXT_DIM)
                w.grid(row=r, column=1, sticky="e")
                Tooltip(w, hint or label)
                self._fields[key] = (w, kind, var)
                self._settings_rows[key] = (lab, w)
                if key == "ServerPassword":
                    gen = ctk.CTkButton(grid, text="🎲", width=40, height=28,
                                        corner_radius=8, fg_color=SURFACE_2,
                                        hover_color=BORDER,
                                        command=self._gen_password)
                    gen.grid(row=r, column=2, padx=(6, 0))
                    Tooltip(gen, "Generate a new friendly-but-strong password "
                                 "and fill it in.")
                r += 1
        self.btn_save_settings = ctk.CTkButton(
            scroll, text="💾  " + T("Save settings"), font=("Segoe UI", 13, "bold"),
            height=46, width=220, corner_radius=12, fg_color=ACCENT,
            hover_color=ACCENT_HOVER, text_color="#ffffff",
            command=self._save_settings,
        )
        self.btn_save_settings.pack(anchor="w", pady=(10, 8))
        Tooltip(self.btn_save_settings,
                "Writes these values into the server config file. "
                "You'll be offered a restart so they apply immediately.")

    def _filter_settings(self, q):
        q = q.strip().lower()
        visible = set()
        for sec, key, label, hint, _kind, _extra in PLAYFIELDS:
            label, hint = tr_setting(key, label, hint)
            hay = " ".join(x for x in (label, hint, key) if x).lower()
            if not q or q in hay:
                visible.add(key)
                visible.add(sec)
        for key, (lab, w) in self._settings_rows.items():
            if key in visible:
                lab.grid()
                w.grid()
            else:
                lab.grid_remove()
                w.grid_remove()
        for sec, card in self._settings_cards.items():
            if sec in visible:
                card.pack(fill="x", padx=6, pady=7,
                          before=self.btn_save_settings)
            else:
                card.pack_forget()

    def _load_settings_form(self):
        s = load_server_settings()
        self.lbl_pw.configure(text=s.get("ServerPassword", "").strip('"') or "—")
        self._render_chips(s)
        for key, (w, kind, var) in self._fields.items():
            raw = s.get(key, "")
            if kind == "enum":
                w.set(raw or (self._extra(key) or ["None"])[0])
            elif kind == "bool":
                var.set(raw.lower().strip() == "true")
            elif kind == "mins":  # ini stores seconds
                try:
                    w.delete(0, "end")
                    w.insert(0, str(max(1, round(float(raw or 1800) / 60))))
                except ValueError:
                    w.insert(0, "30")
            elif kind == "float":
                w.delete(0, "end")
                w.insert(0, str(round(float(raw or 1), 2)))
            else:  # str and int
                w.delete(0, "end")
                w.insert(0, raw.strip('"') if kind == "str" else raw or "0")

    def _render_chips(self, s=None):
        for w in self.chips_frame.winfo_children():
            w.destroy()
        s = s or load_server_settings()
        chips = [
            "🌍 " + s.get("ServerName", "").strip('"'),
            f"👥 {s.get('ServerPlayerMaxNum', '16')} slots",
            "🎮 Steam only",
        ]
        if self._build_id:
            chips.append(f"🧱 build {self._build_id}")
        for c in chips:
            ctk.CTkLabel(self.chips_frame, text="  " + c + "  ", font=("Segoe UI", 10),
                         text_color=TEXT_DIM, fg_color=SURFACE_2, corner_radius=11,
                         height=22).pack(side="left", padx=(0, 6))

    @staticmethod
    def _extra(key):
        for f in PLAYFIELDS:
            if f[1] == key:
                return f[5]
        return None

    def _gen_password(self):
        import secrets
        words = ["pal", "lamb", "wolf", "fluffy", "meadow", "shepherd",
                 "blaze", "frost", "ember", "claw", "run", "crag", "misty"]
        pw = "-".join(secrets.choice(words) for _ in range(3)) + \
            str(secrets.randbelow(90) + 10)
        w = self._fields["ServerPassword"][0]
        w.delete(0, "end")
        w.insert(0, pw)
        self._toast("New password generated — remember to Save settings!", "🎲")

    def _save_settings(self):
        updates, errors = {}, []
        for key, (w, kind, var) in self._fields.items():
            if kind == "str":
                updates[key] = _quote(str(w.get()).strip())
            elif kind == "bool":
                updates[key] = "True" if var.get() else "False"
            elif kind == "mins":  # displayed minutes -> ini seconds
                raw = str(w.get()).strip()
                try:
                    v = float(raw)
                    lo, hi = self._extra(key)
                    if not (lo <= v <= hi):
                        raise ValueError
                    updates[key] = str(int(round(v * 60)))
                except ValueError:
                    errors.append(key)
            elif kind == "int":
                raw = str(w.get()).strip()
                lo, hi = self._extra(key)
                if not raw.lstrip("-").isdigit() or not (lo <= int(raw) <= hi):
                    errors.append(key)
                else:
                    updates[key] = str(int(raw))
            elif kind == "float":
                raw = str(w.get()).strip()
                try:
                    v = round(float(raw), 2)
                    lo, hi = self._extra(key)
                    if not (lo <= v <= hi):
                        raise ValueError
                    updates[key] = str(v)
                except ValueError:
                    errors.append(key)
            else:  # enum
                updates[key] = str(w.get())
        if errors:
            names = ", ".join(tr_setting(f[1], f[2], f[3])[0]
                              for f in PLAYFIELDS if f[1] in errors)
            messagebox.showerror(T("Invalid values"), "Please check:\n" + names)
            return
        try:
            current = load_server_settings()
            changed_risky = [k for k, v in updates.items()
                             if k not in ACCESS_KEYS and current.get(k) != v]
            if changed_risky:
                backup_now()
                self._log_event("🗄 Safety backup before settings change")
        except (OSError, ValueError) as e:
            messagebox.showerror("Error", f"Could not read settings:\n{e}")
            return
        running = is_running()
        restart_now = (not running) or messagebox.askyesno(
            T("Saved"),
            T("Settings saved. Restart the server now so they take effect?"),
        )
        if restart_now and self._busy:
            restart_now = False
        if restart_now:
            self._set_busy(T("Restarting…"))

            def work():
                try:
                    if running:
                        stop_server()
                    # write while STOPPED — the server rewrites the ini
                    # with its in-memory settings on exit, which would
                    # revert edits made while it runs
                    write_server_settings(updates)
                except (OSError, ValueError) as e:
                    self._log_event(f"⚠ Could not write settings: {e}")
                    self.after(0, lambda: messagebox.showerror(
                        "Error", f"Could not write settings:\n{e}"))
                    self.after(0, lambda: self._flash(None))
                    return
                ok = start_server()
                self._log_event("↻ Server restarted"
                                if ok else "⚠ Restart failed")
                self.after(0, lambda: self._flash(
                    "Server is UP ✅" if ok else "Server failed to start ❌"))
            threading.Thread(target=work, daemon=True).start()
        else:
            # deferred: flushed into the ini by the next server start
            apply_ini_updates(updates)
            self._toast(T("Saved — applies at the next server start."), "💾")

    PRESET_VALUES = {
        "peaceful": {"bIsPvP": "False", "DeathPenalty": "None"},
        "normal":   {"bIsPvP": "False", "DeathPenalty": "Item"},
        "hardcore": {"bIsPvP": "False", "DeathPenalty": "All"},
        "pvp":      {"bIsPvP": "True", "DeathPenalty": "ItemAndEquipment"},
    }

    def _apply_preset(self, pid):
        vals = self.PRESET_VALUES[pid]
        names = {"bIsPvP": T("PvP"), "DeathPenalty": T("Death penalty")}
        desc = "\n".join(f"  •  {names[k]}: {v}" for k, v in vals.items())
        if not messagebox.askyesno(
                T("Apply preset"),
                T("This will change the game rules:") + f"\n{desc}\n\n" +
                T("A safety backup is made first. Continue?")):
            return
        try:
            backup_now()
            self._log_event("🗄 Safety backup before preset change")
        except OSError as e:
            messagebox.showerror("Error", f"Backup failed:\n{e}")
            return
        running = is_running()
        restart_now = (not running) or messagebox.askyesno(
            T("Saved"),
            T("Settings saved. Restart the server now so they take effect?"),
        )
        if restart_now and self._busy:
            restart_now = False
        if restart_now:
            self._set_busy(T("Restarting…"))

            def work():
                try:
                    if running:
                        stop_server()
                    write_server_settings(vals)  # while STOPPED (see above)
                except (OSError, ValueError) as e:
                    self._log_event(f"⚠ Could not write settings: {e}")
                    self.after(0, lambda: messagebox.showerror(
                        "Error", f"Could not write settings:\n{e}"))
                    self.after(0, lambda: self._flash(None))
                    return
                ok = start_server()
                self._log_event("↻ Server restarted"
                                if ok else "⚠ Restart failed")
                self.after(0, lambda: self._flash(
                    "Server is UP ✅" if ok else "Server failed to start ❌"))
            threading.Thread(target=work, daemon=True).start()
        else:
            apply_ini_updates(vals)
        self._load_settings_form()
        self._toast(T("Preset applied"), "✅")
        self._log_event(f"🎚 Preset applied: {pid}")

    # ===== Schedule page =====
    def _build_schedule_tab(self, t):
        c1 = self._card(t, "When should the server run?",
                        "The app turns the server on and off by itself at these times.")
        self.var_mode = tk.StringVar(
            value="Always on (24/7)" if self.cfg["mode"] == "always"
            else "On a schedule"
        )
        seg = ctk.CTkSegmentedButton(
            c1, values=[T("Always on (24/7)"), T("On a schedule")],
            variable=self.var_mode, command=lambda _v: self._sched_mode_toggle(),
        )
        seg.pack(anchor="w", pady=(2, 10))
        Tooltip(seg, "Always on = runs 24/7. Schedule = runs only between the times below.")
        self.sched_box = ctk.CTkFrame(c1, fg_color="transparent")
        self.sched_box.pack(anchor="w", fill="x")
        ctk.CTkLabel(self.sched_box, text=T("Turn ON at"), font=F_BODY).grid(
            row=0, column=0, padx=(0, 6))
        self.ent_on = ctk.CTkEntry(self.sched_box, width=80)
        self.ent_on.insert(0, self.cfg["on_time"])
        self.ent_on.grid(row=0, column=1, padx=(0, 18))
        ctk.CTkLabel(self.sched_box, text=T("Turn OFF at"), font=F_BODY).grid(
            row=0, column=2, padx=(0, 6))
        self.ent_off = ctk.CTkEntry(self.sched_box, width=80)
        self.ent_off.insert(0, self.cfg["off_time"])
        self.ent_off.grid(row=0, column=3)
        ctk.CTkLabel(
            self.sched_box, font=F_SMALL, text_color=TEXT_DIM, justify="left",
            text="24-hour clock, e.g. 18:00 and 23:00. Times may cross midnight\n"
                 "(ON 20:00 → OFF 02:00) — the app handles that automatically.",
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(8, 0))
        self._sched_mode_toggle()

        c2 = self._card(t, "Automation")
        r1 = ctk.CTkFrame(c2, fg_color="transparent")
        r1.pack(fill="x", pady=3)
        self.ent_restart = ctk.CTkEntry(r1, width=80)
        self.ent_restart.insert(0, self.cfg["daily_restart"])
        box1 = ctk.CTkFrame(r1, fg_color="transparent")
        box1.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(box1, text=T("Daily automatic restart at"), font=F_BODY,
                     anchor="w").pack(anchor="w")
        ctk.CTkLabel(box1, text="Frees memory and keeps the server healthy. "
                                "Empty = no daily restart.",
                     font=F_SMALL, text_color=TEXT_DIM, anchor="w").pack(anchor="w")
        self.ent_restart.pack(side="right")
        r2 = ctk.CTkFrame(c2, fg_color="transparent")
        r2.pack(fill="x", pady=3)
        self.var_watchdog = tk.BooleanVar(value=self.cfg["watchdog"])
        sw1 = ctk.CTkSwitch(r2, text="", variable=self.var_watchdog)
        sw1.pack(side="right")
        Tooltip(sw1, "If enabled, the app relaunches the server within seconds "
                     "whenever it crashes.")
        ctk.CTkLabel(r2, text=T("Restart automatically if the server crashes"),
                     font=F_BODY, anchor="w").pack(side="left", fill="x", expand=True)
        r3 = ctk.CTkFrame(c2, fg_color="transparent")
        r3.pack(fill="x", pady=3)
        self.var_autostart = tk.BooleanVar(value=self.cfg["autostart_app"])
        sw2 = ctk.CTkSwitch(r3, text="", variable=self.var_autostart)
        sw2.pack(side="right")
        Tooltip(sw2, "The app opens quietly when Windows starts, so the schedule "
                     "and crash-restart keep working after a reboot.")
        ctk.CTkLabel(r3, text=T("Open this app when Windows starts (recommended for 24/7)"),
                     font=F_BODY, anchor="w").pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(
            t, text="ℹ️  Keep this app open (minimised is fine) — it applies the "
                    "schedule and restarts the server if it crashes.",
            font=F_SMALL, text_color=TEXT_DIM, justify="left",
        ).pack(anchor="w", padx=10, pady=(2, 6))
        self.btn_save_sched = ctk.CTkButton(
            t, text="💾  " + T("Save schedule"), font=("Segoe UI", 13, "bold"),
            height=46, width=220, corner_radius=12, fg_color=ACCENT,
            hover_color=ACCENT_HOVER, text_color="#ffffff",
            command=self._save_schedule,
        )
        self.btn_save_sched.pack(anchor="w", padx=10)
        Tooltip(self.btn_save_sched, "Saves these times. The app starts using them "
                                     "within about 10 seconds.")

    def _sched_mode_toggle(self):
        state = "disabled" if self.var_mode.get().startswith(("Always", "Toujours")) \
            else "normal"
        for w in (self.ent_on, self.ent_off):
            w.configure(state=state)

    def _save_schedule(self):
        def hm_ok(s, allow_empty=False):
            if allow_empty and not s:
                return True
            return bool(re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", s))
        vals = {
            "mode": "always" if self.var_mode.get().startswith(("Always", "Toujours"))
                    else "scheduled",
            "on_time": self.ent_on.get().strip(),
            "off_time": self.ent_off.get().strip(),
            "daily_restart": self.ent_restart.get().strip(),
            "watchdog": bool(self.var_watchdog.get()),
            "autostart_app": bool(self.var_autostart.get()),
        }
        bad = [k for k in ("on_time", "off_time") if not hm_ok(vals[k])]
        if not hm_ok(vals["daily_restart"], allow_empty=True):
            bad.append("daily_restart")
        if bad:
            messagebox.showerror(
                T("Invalid time"),
                "Use the HH:MM format (e.g. 18:00) for:\n" + ", ".join(bad)
            )
            return
        self.cfg.update(vals)
        save_cfg(self.cfg)
        set_app_autostart(vals["autostart_app"])
        self._last_desired = None  # re-evaluate desired state immediately
        messagebox.showinfo(T("Saved"), "Schedule saved — the app is now using it.")

    # ===== Maintenance page =====
    def _build_maint_tab(self, t):
        scroll = ctk.CTkScrollableFrame(t, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        c1 = self._card(scroll, "Server files")
        self._maint_row(
            c1, "⬇  " + T("Update server"), ACCENT, ACCENT_HOVER,
            "Downloads the latest Palworld server version (stops the server, "
            "backs up, updates, restarts — you'll see a live log).",
            self._update,
        )
        self._maint_row(
            c1, "🔧  " + T("Repair game files"), BLUE, BLUE_HOVER,
            "Re-downloads any corrupted game files and restarts — use this "
            "if the server keeps crashing after an update.",
            self._repair,
        )
        self._maint_row(
            c1, "🔍  " + T("Check for Palworld update now"), BLUE, BLUE_HOVER,
            "Compares your installed server version with the latest on Steam.",
            self._check_update_now,
        )
        self._maint_row(
            c1, "👥  " + T("Import a friend's character"), ACCENT, ACCENT_HOVER,
            "If a friend played your old co-op world: have them join the server "
            "once, then bring back their level, items and Pals with this wizard.",
            self._open_friend_wizard,
        )
        self._maint_row(
            c1, "🗄  " + T("Backup now"), BLUE, BLUE_HOVER,
            "Copies the current world saves to E:\\PalworldServer\\backups. "
            "Do this before big adventures!",
            self._backup,
        )
        self._maint_row(
            c1, "📂  " + T("Open saves / backups folders"), NEUTRAL, NEUTRAL_HOVER,
            "Browse the files on disk (world saves and their backups).",
            self._open_folders,
        )
        bk = self._card(scroll, "Backups",
                        T("Right-click a backup to restore, verify or delete it."))
        self.bk_frame = ctk.CTkScrollableFrame(bk, height=150,
                                               fg_color="transparent")
        self.bk_frame.pack(fill="x")
        self._render_backups_list()

        cw = self._card(scroll, "Worlds",
                        "Keep a second, throwaway world to test updates and "
                        "settings before touching the real one.")
        self.lbl_worlds = ctk.CTkLabel(cw, text="…", font=("Consolas", 10.5),
                                       text_color=TEXT, anchor="w",
                                       justify="left")
        self.lbl_worlds.pack(anchor="w")
        rw = ctk.CTkFrame(cw, fg_color="transparent")
        rw.pack(fill="x", pady=(6, 0))
        ctk.CTkButton(rw, text="🌍  " + T("Create test world"), height=34,
                      corner_radius=8, fg_color=ACCENT,
                      hover_color=ACCENT_HOVER, text_color="#ffffff",
                      command=self._create_test_world).pack(side="left")
        ctk.CTkButton(rw, text="🔄  Switch main ⇄ test", height=34,
                      corner_radius=8, fg_color=BLUE, hover_color=BLUE_HOVER,
                      text_color="#ffffff",
                      command=lambda: self._switch_world(
                          "test" if self.cfg.get("active_label") == "main"
                          else "main")).pack(side="left", padx=(8, 0))
        ctk.CTkButton(rw, text="🗑  " + T("Delete test world"), height=34,
                      corner_radius=8, fg_color=NEUTRAL,
                      hover_color=NEUTRAL_HOVER, text_color="#ffffff",
                      command=self._delete_test_world).pack(side="left",
                                                            padx=(8, 0))
        self._worlds_refresh()

        cst = self._card(scroll, "Storage",
                         "Disk space and save sizes — glanceable prevention.")
        self.lbl_stor = ctk.CTkLabel(cst, text="…", font=("Consolas", 11),
                                     text_color=TEXT, anchor="w", justify="left")
        self.lbl_stor.pack(anchor="w")

        c2 = self._card(scroll, "Windows setup (one time)",
                        "Needed once so friends can connect from outside your home.")
        self._maint_row(
            c2, "🛡  " + T("Apply Windows fixes"), BLUE, BLUE_HOVER,
            "Opens the firewall port (UDP 8211), disables PC sleep, and removes "
            "old auto-start leftovers. Windows will ask for permission — click Yes.",
            self._admin_fix,
        )
        self.lbl_tasks = ctk.CTkLabel(c2, text="", font=F_SMALL, text_color=TEXT_DIM,
                                      anchor="w", justify="left")
        self.lbl_tasks.pack(anchor="w", pady=(6, 0))
        self._refresh_tasks_label()

        c3 = self._card(scroll, "Resources",
                        "Handy links for you and your friends.")
        rres = ctk.CTkFrame(c3, fg_color="transparent")
        rres.pack(fill="x", pady=2)
        for label, url in (
            ("📖  " + T("Palworld Wiki"), "https://palworld.fandom.com"),
            ("🗺  " + T("Guides & interactive map"), "https://game8.co/games/Palworld"),
            ("🥚  " + T("Search breeding calculator"),
             "https://www.google.com/search?q=palworld+breeding+calculator"),
        ):
            b = ctk.CTkButton(rres, text=label, height=38, corner_radius=10,
                              fg_color=SURFACE_2, hover_color=BORDER,
                              command=lambda u=url: webbrowser.open(u))
            b.pack(side="left", expand=True, fill="x", padx=4)
            Tooltip(b, url)

        cnews = self._card(scroll, "Palworld news",
                           T("Official patch notes and announcements — click a "
                             "headline to read it in your browser."))
        nrow = ctk.CTkFrame(cnews, fg_color="transparent")
        nrow.pack(fill="x")
        self.lbl_news_state = ctk.CTkLabel(nrow, text=T("Loading…"), font=F_SMALL,
                                           text_color=TEXT_DIM, anchor="w")
        self.lbl_news_state.pack(side="left")
        ctk.CTkButton(nrow, text="🔄  " + T("Refresh"), height=30, corner_radius=8,
                      fg_color=SURFACE_2, hover_color=BORDER,
                      command=self._news_fetch).pack(side="right")
        self.news_frame = ctk.CTkFrame(cnews, fg_color="transparent")
        self.news_frame.pack(fill="x")

    def _maint_row(self, parent, text, color, hover, desc, cmd):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=4)
        b = ctk.CTkButton(row, text=text, width=240, height=36, corner_radius=8,
                          fg_color=color, hover_color=hover,
                          text_color="#ffffff", command=cmd)
        b.pack(side="right")
        Tooltip(b, desc)
        ctk.CTkLabel(row, text=desc, font=F_SMALL, text_color=TEXT_DIM,
                     anchor="w", justify="left", wraplength=460).pack(
            side="left", fill="x", expand=True, padx=(0, 12)
        )
        return row

    # ===== storage =====
    def _storage_loop(self):
        while True:
            try:
                du = shutil.disk_usage(BASE)
                free_gb = du.free / 1024**3
                total_gb = du.total / 1024**3
                world_gb = dir_size(SAVES_DIR) / 1024**3
                bks = list_backups()
                bk_gb = sum(self._bk_sizes.get(b, 0) or backup_size(b)
                            for b in bks) / 1024**3
                for b in bks:
                    if b not in self._bk_sizes:
                        self._bk_sizes[b] = backup_size(b)
                self.q.put(("storage", {
                    "free_gb": round(free_gb, 0), "total_gb": round(total_gb, 0),
                    "world_gb": round(world_gb, 2), "bk_n": len(bks),
                    "bk_gb": round(bk_gb, 1),
                }))
            except OSError:
                pass
            time.sleep(120)

    def _render_storage(self, s):
        warn = s["free_gb"] < 30
        self.lbl_stor.configure(
            text=(f"💽  disk  {s['free_gb']:.0f} GB free of {s['total_gb']:.0f} GB\n"
                  f"🌍  world saves  {s['world_gb']:.2f} GB\n"
                  f"🗄  backups  {s['bk_n']} · {s['bk_gb']:.1f} GB"),
            text_color=(("#b91c1c", "#ef4444") if warn else TEXT),
        )

    # ===== backups list =====
    def _bk_size(self, name):
        if name not in self._bk_sizes:
            self._bk_sizes[name] = backup_size(name)
        gb = self._bk_sizes[name] / 1024**3
        return f"{gb:.2f} GB" if gb >= 1 else f"{self._bk_sizes[name]/1024**2:.0f} MB"

    def _render_backups_list(self):
        for w in self.bk_frame.winfo_children():
            w.destroy()
        bks = list_backups()
        if not bks:
            ctk.CTkLabel(self.bk_frame, text="—", font=F_SMALL,
                         text_color=TEXT_DIM).pack(anchor="w")
            return
        for name in bks[:30]:
            sel = name == self._sel_backup
            ok = self._verified.get(name)
            prefix = ("✓ " if ok else ("✗ " if ok is False else ""))
            b = ctk.CTkButton(
                self.bk_frame, anchor="w", height=32, corner_radius=8,
                font=("Consolas", 11),
                text=f"{prefix}🗄  {name}   ·   {self._bk_size(name)}",
                fg_color=ACCENT_SOFT if sel else SURFACE_2,
                text_color=(ACCENT if sel else
                            ((("#15803d", "#4ade80") if ok else RED)
                             if ok is not None else TEXT)),
                hover_color=BORDER,
                command=lambda n=name: self._select_backup(n),
            )
            b.pack(fill="x", pady=2)
            menu = tk.Menu(self, tearoff=0)
            menu.add_command(label=T("Restore"), command=lambda n=name:
                             self._restore_named(n))
            menu.add_command(label=T("Verify"), command=lambda n=name:
                             self._verify_backup(n))
            menu.add_command(label=T("Delete"), command=lambda n=name:
                             self._delete_backup(n))

            def rcm(e, m=menu):
                try:
                    m.tk_popup(e.x_root, e.y_root)
                finally:
                    m.grab_release()
            b.bind("<Button-3>", rcm)
            Tooltip(b, "Right-click to restore, verify or delete this backup.")

    def _select_backup(self, name):
        self._sel_backup = name
        self._render_backups_list()

    def _verify_backup(self, name):
        self._toast(f"Verifying {name}…", "🔍")

        def work():
            ok, _tail = verify_backup(name)
            self._verified[name] = ok
            save_verified(self._verified)
            self._log_event(f"{'✅' if ok else '⚠'} Backup {name} "
                            f"{'verified' if ok else 'FAILED verification'}")
            self.after(0, lambda: self._toast(
                f"{name}: {'healthy ✓' if ok else 'FAILED verification'}",
                "✅" if ok else "⚠"))
            self.after(0, self._render_backups_list)
        threading.Thread(target=work, daemon=True).start()

    def _delete_backup(self, name):
        if not messagebox.askyesno(
            T("Delete"), f"Delete backup {name}?\nThis cannot be undone."
        ):
            return
        delete_backup(name)
        if self._sel_backup == name:
            self._sel_backup = None
        self._bk_sizes.pop(name, None)
        self._verified.pop(name, None)
        save_verified(self._verified)
        self._log_event(f"🗑 Backup deleted ({name})")
        self._render_backups_list()

    def _restore_named(self, name):
        if not messagebox.askyesno(
            T("Restore"),
            f"Restore backup {name}?\n\nThe server will stop and CURRENT saves "
            "are replaced by this backup.",
        ):
            return
        was = is_running()

        def work():
            self._busy = True
            try:
                restore_backup(name, was)
                self._log_event(f"⏪ Backup restored ({name})")
                if was:
                    start_server()
                self.after(0, lambda: self._toast(
                    f"Backup {name} restored", "⏪"))
            except (OSError, subprocess.SubprocessError) as e:
                self.after(0, lambda e=e: messagebox.showerror("Error", str(e)))
            finally:
                self._busy = False
        threading.Thread(target=work, daemon=True).start()

    # ===== friend import wizard =====
    def _open_friend_wizard(self):
        win = ctk.CTkToplevel(self)
        win.title(T("Import a friend's character"))
        win.geometry("640x520")
        win.grab_set()
        body = ctk.CTkFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=18, pady=14)

        ctk.CTkLabel(
            body, font=F_SMALL, text_color=TEXT_DIM, justify="left",
            text="1) The friend joins your server once and creates a character.\n"
                 "2) Pick their OLD character (level/progress from your world)\n"
                 "     and their NEW character on the server.\n"
                 "3) Import — the app backs up, swaps, restarts. They relog and "
                 "keep everything.",
        ).pack(anchor="w", pady=(0, 10))

        self._wiz_status = ctk.CTkLabel(body, text="", font=F_SMALL,
                                        text_color=TEXT_DIM, anchor="w",
                                        justify="left")
        self._wiz_status.pack(anchor="w", pady=(0, 6))
        self._wiz_src = ctk.CTkOptionMenu(body, values=["—"], width=420)
        self._wiz_tgt = ctk.CTkOptionMenu(body, values=["—"], width=420)
        ctk.CTkLabel(body, text="Old character (from your co-op world):",
                     font=F_BODY_B, anchor="w").pack(anchor="w")
        self._wiz_src.pack(anchor="w", pady=(2, 10))
        ctk.CTkLabel(body, text="New server character (after they joined):",
                     font=F_BODY_B, anchor="w").pack(anchor="w")
        self._wiz_tgt.pack(anchor="w", pady=(2, 12))
        rbtn = ctk.CTkFrame(body, fg_color="transparent")
        rbtn.pack(anchor="w")
        ctk.CTkButton(rbtn, text="🔄  " + T("Scan world"), height=38, width=140,
                      corner_radius=10, fg_color=BLUE, hover_color=BLUE_HOVER,
                      text_color="#ffffff",
                      command=self._wiz_refresh).pack(side="left")
        self._wiz_import_btn = ctk.CTkButton(
            rbtn, text="👥  " + T("Import a friend's character"), height=38,
            corner_radius=10, fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color="#ffffff", command=self._wiz_import)
        self._wiz_import_btn.pack(side="left", padx=(8, 0))
        self._wiz_win = win
        self._wiz_refresh()

    def _wiz_refresh(self):
        self._wiz_status.configure(text="⏳ scanning the world…")
        self._wiz_import_btn.configure(state="disabled")

        def work():
            data = run_world_scan()
            self.after(0, lambda: self._wiz_fill(data))
        threading.Thread(target=work, daemon=True).start()

    def _wiz_fill(self, data):
        try:
            self._wiz_status.configure(text="")
            players = (data or {}).get("all_players", [])
            if not players:
                self._wiz_status.configure(
                    text="No characters found — scan tools missing?")
                return
            labels = [f"{p['name']}  ·  Lv{p['level']}  ·  "
                      f"{p['pals']} Pals  ·  {p['uid'][:8]}"
                      for p in players]
            self._wiz_src.configure(values=labels)
            self._wiz_tgt.configure(values=labels)
            self._wiz_src.set(labels[0])
            self._wiz_tgt.set(labels[1] if len(labels) > 1 else labels[0])
            self._wiz_players = players
            self._wiz_import_btn.configure(state="normal")
        except tk.TclError:
            pass  # wizard window closed mid-scan

    def _wiz_import(self):
        players = getattr(self, "_wiz_players", [])
        labels = [f"{p['name']}  ·  Lv{p['level']}  ·  "
                  f"{p['pals']} Pals  ·  {p['uid'][:8]}" for p in players]
        try:
            src = players[labels.index(self._wiz_src.get())]
            tgt = players[labels.index(self._wiz_tgt.get())]
        except (ValueError, IndexError):
            return
        if src["uid"] == tgt["uid"]:
            messagebox.showwarning(T("Import a friend's character"),
                                   "Pick two different characters.")
            return
        if not messagebox.askyesno(
            T("Import a friend's character"),
            f"Move {src['name']} (Lv{src['level']}, {src['pals']} Pals) onto "
            f"the new character {tgt['name']} (Lv{tgt['level']})?\n\n"
            "The server will stop (a backup is taken first).",
        ):
            return
        self._wiz_import_btn.configure(state="disabled")
        self._wiz_status.configure(text="⏳ importing… (backup + swap + restart)")

        def work():
            self._busy = True
            try:
                backup_now()
                was = is_running()
                if was:
                    stop_server()
                ok, tail = run_friend_migration(src["uid"], tgt["uid"])
                if ok:
                    self._log_event(f"👥 Imported {src['name']}'s character onto "
                                    f"{tgt['uid'][:8]}")
                if was:
                    start_server()
                msg = ("✅ Done — your friend can relog and will have their "
                       "level, items and Pals!"
                       if ok else f"❌ Migration failed:\n{tail}")
                self.after(0, lambda m=msg: self._wiz_status.configure(text=m))
                self.after(0, lambda: self._toast(
                    "Character imported" if ok else "Import failed",
                    "👥" if ok else "⚠"))
            finally:
                self._busy = False
        threading.Thread(target=work, daemon=True).start()

    # ===== finish-setup guided flow =====
    def _open_finish_setup(self):
        win = ctk.CTkToplevel(self)
        win.title(T("🚀  Finish setup"))
        win.geometry("600x460")
        win.grab_set()
        self._fs_win = win
        self._fs_body = ctk.CTkFrame(win, fg_color="transparent")
        self._fs_body.pack(fill="both", expand=True, padx=18, pady=14)
        self._refresh_finish_setup()

    def _refresh_finish_setup(self):
        try:
            for w in self._fs_body.winfo_children():
                w.destroy()
        except tk.TclError:
            return
        ctk.CTkLabel(self._fs_body, font=("Segoe UI", 15, "bold"),
                     text="Almost there — let's get your friends in! 🚀"
                     ).pack(anchor="w", pady=(0, 8))
        running = is_running()
        fw = self._fw_ok()
        router = self.cfg.get("router_done")
        ip = bool(self._public_ip or
                  (self.cfg.get("duck_domain") and self.cfg.get("duck_token")))
        steps = [
            (running, "Start the server", "▶  " + T("Start"),
             lambda: (self._do_start(), self._fs_refresh_later())),
            (fw, "Open the Windows firewall (one admin click)",
             "🛡  " + T("Apply Windows fixes"),
             lambda: (self._fs_admin_fix(), self._fs_refresh_later())),
            (router, "Forward UDP 8211 on your router (page: 192.168.0.1)",
             "🌐  " + T("Open router page"),
             lambda: (webbrowser.open("http://192.168.0.1"),
                      self._fs_router_done(), self._fs_refresh_later())),
            (ip, "Know your public address",
             "↻  Retry", lambda: (self._fetch_public_ip(),
                                  self._fs_refresh_later())),
        ]
        for ok, desc, btn, cmd in steps:
            r = ctk.CTkFrame(self._fs_body, fg_color="transparent")
            r.pack(fill="x", pady=5)
            ctk.CTkLabel(r, text="✅" if ok else "⏳", width=3,
                         font=("Segoe UI", 14, "bold"),
                         text_color=ACCENT if ok else TEXT_DIM).pack(side="left")
            ctk.CTkLabel(r, text=desc, font=F_BODY, anchor="w").pack(
                side="left", fill="x", expand=True, padx=(2, 10))
            if not ok:
                ctk.CTkButton(r, text=btn, height=30, corner_radius=8, width=190,
                              fg_color=SURFACE_2, hover_color=BORDER,
                              command=cmd).pack(side="right")
        ctk.CTkLabel(
            self._fs_body, font=F_SMALL, text_color=TEXT_DIM, justify="left",
            text="Then hit “Copy invite message” on the Server page and send it "
                 "to your friends. That's it!",
        ).pack(anchor="w", pady=(10, 0))
        ctk.CTkButton(self._fs_body, text="Close", height=34, corner_radius=10,
                      width=110, fg_color=NEUTRAL, hover_color=NEUTRAL_HOVER,
                      text_color="#ffffff",
                      command=self._fs_win.destroy).pack(anchor="w", pady=(12, 0))

    def _fs_refresh_later(self):
        self.after(1500, self._refresh_finish_setup)
        self.after(1500, lambda: self._update_checklist(self._last_stats_running))

    def _fs_admin_fix(self):
        try:
            if run_admin_fix():
                self._log_event("🛡 Windows fixes applied (firewall / sleep / tasks)")
                self._refresh_tasks_label()
        except OSError:
            pass

    def _fs_router_done(self):
        self.cfg["router_done"] = True
        save_cfg(self.cfg)
        self.btn_router_done.configure(text=T("Undo"))

    # ===== Preferences page =====
    def _build_prefs_tab(self, t):
        scroll = ctk.CTkScrollableFrame(t, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        c1 = self._card(scroll, "Appearance",
                        "Make it yours. Takes effect after the app restarts.")
        row_acc = ctk.CTkFrame(c1, fg_color="transparent")
        row_acc.pack(fill="x", pady=4)
        ctk.CTkLabel(row_acc, text=T("Accent color"), font=F_BODY).pack(
            side="left", padx=(0, 16))
        for name, (main, _h, _s) in ACCENTS.items():
            active = self.cfg.get("accent", "green") == name
            sw = ctk.CTkButton(
                row_acc, text="✓" if active else "", width=44, height=36,
                corner_radius=10, fg_color=main, hover_color=main,
                text_color="#ffffff",
                command=lambda n=name: self._set_accent(n),
            )
            sw.pack(side="left", padx=4)
            Tooltip(sw, name.capitalize())
        row_lang = ctk.CTkFrame(c1, fg_color="transparent")
        row_lang.pack(fill="x", pady=(10, 2))
        ctk.CTkLabel(row_lang, text=T("Language"), font=F_BODY).pack(
            side="left", padx=(0, 16))
        self.lang_seg = ctk.CTkSegmentedButton(
            row_lang, values=["English", "Français"],
            command=self._set_language,
        )
        self.lang_seg.set("Français" if LANG == "fr" else "English")
        self.lang_seg.pack(side="left")
        ctk.CTkLabel(c1, text=T("Takes effect after the app restarts."),
                     font=F_SMALL, text_color=TEXT_DIM).pack(anchor="w", pady=(6, 0))

        c2 = self._card(scroll, "Notifications")
        r = ctk.CTkFrame(c2, fg_color="transparent")
        r.pack(fill="x", pady=3)
        self.var_notify = tk.BooleanVar(value=self.cfg.get("tray_notifications", True))
        sw = ctk.CTkSwitch(r, text="", variable=self.var_notify,
                           command=self._save_notify_pref)
        sw.pack(side="right")
        ctk.CTkLabel(r, text=T("Show a popup when players join or leave"),
                     font=F_BODY, anchor="w").pack(side="left", fill="x",
                                                   expand=True)
        r2 = ctk.CTkFrame(c2, fg_color="transparent")
        r2.pack(fill="x", pady=3)
        self.var_chime = tk.BooleanVar(value=self.cfg.get("join_sound", True))

        def _chime_toggle():
            self.cfg["join_sound"] = bool(self.var_chime.get())
            save_cfg(self.cfg)
        ctk.CTkSwitch(r2, text="", variable=self.var_chime,
                      command=_chime_toggle).pack(side="right")
        ctk.CTkLabel(r2, text=T("Play a chime when someone joins"),
                     font=F_BODY, anchor="w").pack(side="left", fill="x",
                                                   expand=True)

        cb = self._card(scroll, "Friends-only lock",
                        T("Anyone who joins but isn't on the approved list is "
                          "kicked automatically (on top of the password)."))
        rb = ctk.CTkFrame(cb, fg_color="transparent")
        rb.pack(fill="x", pady=3)
        self.var_bouncer = tk.BooleanVar(value=self.cfg.get("bouncer_enabled",
                                                            False))
        ctk.CTkSwitch(rb, text="", variable=self.var_bouncer).pack(side="right")
        ctk.CTkLabel(rb, text="Enable friends-only lock", font=F_BODY,
                     anchor="w").pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(cb, text=T("Approved players (one Steam ID per line)"),
                     font=F_SMALL, text_color=TEXT_DIM, anchor="w").pack(
            anchor="w", pady=(6, 2))
        self.txt_approved = ctk.CTkTextbox(cb, height=110, font=("Consolas", 10),
                                           fg_color=SURFACE_2, corner_radius=10)
        self.txt_approved.pack(fill="x")
        approved = self.cfg.get("bouncer_approved") or []
        self.txt_approved.insert("1.0", "\n".join(approved))
        rbb = ctk.CTkFrame(cb, fg_color="transparent")
        rbb.pack(fill="x", pady=(6, 0))
        ctk.CTkButton(rbb, text="💾  " + T("Save"), height=34, corner_radius=8,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color="#ffffff",
                      command=self._save_bouncer).pack(side="left")
        ctk.CTkButton(rbb, text="👥  " + T("Approve everyone online now"),
                      height=34, corner_radius=8, fg_color=SURFACE_2,
                      hover_color=BORDER,
                      command=self._approve_online).pack(side="left", padx=(8, 0))

        # --- Discord notifications ---
        cd = self._card(scroll, "Discord notifications",
                        T("Get a message in your Discord channel when players "
                          "join or leave, the server crashes, or an update is "
                          "applied."))
        rd1 = ctk.CTkFrame(cd, fg_color="transparent")
        rd1.pack(fill="x", pady=4)
        ctk.CTkLabel(rd1, text=T("Webhook URL"), font=F_BODY).pack(
            side="left", padx=(0, 10))
        self.ent_discord = ctk.CTkEntry(rd1, fg_color=SURFACE_2, border_width=0,
                                        placeholder_text=(
                                            "https://discord.com/api/webhooks/…"))
        self.ent_discord.insert(0, self.cfg.get("discord_webhook", ""))
        self.ent_discord.pack(side="left", fill="x", expand=True)
        rdb2 = ctk.CTkFrame(cd, fg_color="transparent")
        rdb2.pack(fill="x", pady=(6, 0))
        ctk.CTkButton(rdb2, text="💾  " + T("Save"), height=34, corner_radius=8,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color="#ffffff",
                      command=self._save_discord).pack(side="left")
        ctk.CTkButton(rdb2, text="🔔  " + T("Send test message"), height=34,
                      corner_radius=8, fg_color=SURFACE_2, hover_color=BORDER,
                      command=self._test_discord).pack(side="left", padx=(8, 0))
        ctk.CTkLabel(
            cd, text=T("In Discord: server settings → Integrations → Webhooks "
                       "→ New webhook → Copy URL."),
            font=F_SMALL, text_color=TEXT_DIM, anchor="w", justify="left",
        ).pack(anchor="w", pady=(6, 0))

        # --- password rotation ---
        cr = self._card(scroll, "Password rotation",
                        T("Change the server password automatically every week "
                          "and copy the new invite to your clipboard."))
        rr1 = ctk.CTkFrame(cr, fg_color="transparent")
        rr1.pack(fill="x", pady=4)
        self.var_rotate = tk.BooleanVar(value=self.cfg.get("rotate_password",
                                                           False))
        ctk.CTkSwitch(rr1, text="", variable=self.var_rotate).pack(side="right")
        ctk.CTkLabel(rr1, text=T("Enable weekly rotation"), font=F_BODY,
                     anchor="w").pack(side="left", fill="x", expand=True)
        rr2 = ctk.CTkFrame(cr, fg_color="transparent")
        rr2.pack(fill="x", pady=3)
        ctk.CTkLabel(rr2, text=T("Rotate on"), font=F_BODY).pack(
            side="left", padx=(0, 10))
        self.om_rotate_day = ctk.CTkOptionMenu(rr2, width=96, values=WEEKDAYS,
                                               fg_color=SURFACE_2,
                                               button_color=BORDER)
        self.om_rotate_day.set(self.cfg.get("rotate_day", "Mon")
                               if self.cfg.get("rotate_day") in WEEKDAYS
                               else "Mon")
        self.om_rotate_day.pack(side="left", padx=(0, 18))
        ctk.CTkLabel(rr2, text=T("at"), font=F_BODY).pack(
            side="left", padx=(0, 10))
        self.ent_rotate_hour = ctk.CTkEntry(rr2, width=70)
        self.ent_rotate_hour.insert(0, self.cfg.get("rotate_hour", "09:00"))
        self.ent_rotate_hour.pack(side="left")
        ctk.CTkButton(cr, text="💾  " + T("Save"), height=34, corner_radius=8,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color="#ffffff",
                      command=self._save_rotation).pack(anchor="w", pady=(6, 0))
        ctk.CTkLabel(cr, text=T("Players get a 2-minute warning, then the "
                                "server restarts with the new password."),
                     font=F_SMALL, text_color=TEXT_DIM, anchor="w",
                     justify="left").pack(anchor="w", pady=(4, 0))

        # --- Steam avatars ---
        cs = self._card(scroll, "Steam avatars",
                        T("Show players' real Steam profile pictures instead of "
                          "initials (free API key required)."))
        rs1 = ctk.CTkFrame(cs, fg_color="transparent")
        rs1.pack(fill="x", pady=4)
        ctk.CTkLabel(rs1, text=T("Steam API key"), font=F_BODY).pack(
            side="left", padx=(0, 10))
        self.ent_steamkey = ctk.CTkEntry(rs1, fg_color=SURFACE_2, border_width=0)
        self.ent_steamkey.insert(0, self.cfg.get("steam_api_key", ""))
        self.ent_steamkey.pack(side="left", fill="x", expand=True)
        rs2 = ctk.CTkFrame(cs, fg_color="transparent")
        rs2.pack(fill="x", pady=(6, 0))
        ctk.CTkButton(rs2, text="💾  " + T("Save"), height=34, corner_radius=8,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color="#ffffff",
                      command=self._save_steamkey).pack(side="left")
        ctk.CTkButton(rs2, text="🔑  " + T("Get a free key"), height=34,
                      corner_radius=8, fg_color=NEUTRAL,
                      hover_color=NEUTRAL_HOVER, text_color="#ffffff",
                      command=lambda: webbrowser.open(
                          "https://steamcommunity.com/dev/apikey")
                      ).pack(side="left", padx=(8, 0))

        ca = self._card(scroll, "Announcements",
                        T("Broadcast these messages in-game at the given times."))
        self.ann_frame = ctk.CTkFrame(ca, fg_color="transparent")
        self.ann_frame.pack(fill="x")
        self._ann_rows = []
        for ann in (self.cfg.get("announcements") or [])[:10]:
            self._add_ann_row(ann.get("time", "20:00"), ann.get("text", ""))
        rab = ctk.CTkFrame(ca, fg_color="transparent")
        rab.pack(fill="x", pady=(4, 0))
        ctk.CTkButton(rab, text="➕  " + T("Add announcement"), height=32,
                      corner_radius=8, fg_color=SURFACE_2, hover_color=BORDER,
                      command=lambda: self._add_ann_row("20:00", "")
                      ).pack(side="left")
        ctk.CTkButton(rab, text="💾  " + T("Save"), height=32, corner_radius=8,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color="#ffffff",
                      command=self._save_announcements).pack(side="left",
                                                            padx=(8, 0))

        cprof = self._card(scroll, "Settings profiles",
                           "Example: 2× EXP weekends — rates change automatically "
                           "with an in-game announcement, then revert.")
        self.prof_frame = ctk.CTkFrame(cprof, fg_color="transparent")
        self.prof_frame.pack(fill="x")
        self._prof_rows = []
        for prof in (self.cfg.get("profiles") or [])[:6]:
            self._add_prof_row(prof)
        rpb2 = ctk.CTkFrame(cprof, fg_color="transparent")
        rpb2.pack(fill="x", pady=(4, 0))
        ctk.CTkButton(rpb2, text="➕  " + T("Add profile"), height=32,
                      corner_radius=8, fg_color=SURFACE_2, hover_color=BORDER,
                      command=lambda: self._add_prof_row(
                          {"name": "2× EXP weekend", "sd": "Fri", "st": "18:00",
                           "ed": "Sun", "et": "23:59", "exp": "2", "cap": "2"})
                      ).pack(side="left")
        ctk.CTkButton(rpb2, text="💾  " + T("Save"), height=32, corner_radius=8,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color="#ffffff",
                      command=self._save_profiles).pack(side="left", padx=(8, 0))

        cm = self._card(scroll, "Welcome message",
                        T("Sent in-game every time someone joins."))
        rm = ctk.CTkFrame(cm, fg_color="transparent")
        rm.pack(fill="x", pady=4)
        self.var_motd = tk.BooleanVar(value=self.cfg.get("motd_enabled", True))
        ctk.CTkSwitch(rm, text="", variable=self.var_motd).pack(side="right")
        self.ent_motd = ctk.CTkEntry(rm, fg_color=SURFACE_2, border_width=0,
                                     placeholder_text="Welcome! 🐑")
        self.ent_motd.insert(0, self.cfg.get("motd", ""))
        self.ent_motd.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ctk.CTkButton(cm, text="💾  " + T("Save"), height=34, corner_radius=8,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color="#ffffff", command=self._save_motd
                      ).pack(anchor="w", pady=(6, 0))

        c3 = self._card(scroll, "Automatic backups",
                        "Extra copies of the world, fully automatic.")
        rbk = ctk.CTkFrame(c3, fg_color="transparent")
        rbk.pack(fill="x", pady=4)
        ctk.CTkLabel(rbk, text=T("Every (hours)"), font=F_BODY).pack(
            side="left", padx=(0, 8))
        self.ent_bk_hours = ctk.CTkEntry(rbk, width=70)
        self.ent_bk_hours.insert(0, str(self.cfg.get("backup_interval_h", 4)))
        self.ent_bk_hours.pack(side="left", padx=(0, 22))
        ctk.CTkLabel(rbk, text=T("Keep last"), font=F_BODY).pack(
            side="left", padx=(0, 8))
        self.ent_bk_keep = ctk.CTkEntry(rbk, width=70)
        self.ent_bk_keep.insert(0, str(self.cfg.get("backup_keep", 20)))
        self.ent_bk_keep.pack(side="left")
        ctk.CTkLabel(c3, text=T("0 disables automatic backups."),
                     font=F_SMALL, text_color=TEXT_DIM).pack(anchor="w", pady=(4, 6))
        ctk.CTkButton(c3, text="💾  " + T("Save"), height=38, corner_radius=10,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color="#ffffff", command=self._save_backups_prefs
                      ).pack(anchor="w")

        cu = self._card(scroll, "Automatic updates",
                        T("When an update is available, apply it automatically at "
                          "this time (players get a 2-minute warning first)."))
        ru = ctk.CTkFrame(cu, fg_color="transparent")
        ru.pack(fill="x", pady=4)
        self.var_autoupd = tk.BooleanVar(value=self.cfg.get("auto_update_enabled",
                                                            False))
        ctk.CTkSwitch(ru, text="", variable=self.var_autoupd).pack(side="right")
        ctk.CTkLabel(ru, text=T("Update time"), font=F_BODY).pack(
            side="left", padx=(0, 10))
        self.ent_autoupd = ctk.CTkEntry(ru, width=70)
        self.ent_autoupd.insert(0, self.cfg.get("auto_update_time", "05:30"))
        self.ent_autoupd.pack(side="left")
        ctk.CTkButton(cu, text="💾  " + T("Save"), height=38, corner_radius=10,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color="#ffffff", command=self._save_autoupd
                      ).pack(anchor="w", pady=(6, 0))

        cofs = self._card(scroll, "Offsite backups",
                          "Mirror the newest backups to a second location — e.g. "
                          "your OneDrive folder — so even a dead disk loses "
                          "nothing.")
        ro1 = ctk.CTkFrame(cofs, fg_color="transparent")
        ro1.pack(fill="x", pady=3)
        self.var_offsite = tk.BooleanVar(value=self.cfg.get("offsite_enabled",
                                                            False))
        ctk.CTkSwitch(ro1, text="", variable=self.var_offsite).pack(side="right")
        ctk.CTkLabel(ro1, text="Enable offsite copies", font=F_BODY,
                     anchor="w").pack(side="left", fill="x", expand=True)
        ro2 = ctk.CTkFrame(cofs, fg_color="transparent")
        ro2.pack(fill="x", pady=3)
        self.ent_offsite_dir = ctk.CTkEntry(ro2, fg_color=SURFACE_2,
                                            border_width=0,
                                            placeholder_text="D:\\OneDrive\\PalworldBackups")
        self.ent_offsite_dir.insert(0, self.cfg.get("offsite_dir", ""))
        self.ent_offsite_dir.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(ro2, text="📂", width=40, height=30, corner_radius=8,
                      fg_color=SURFACE_2, hover_color=BORDER,
                      command=self._pick_offsite_dir).pack(side="left")
        ro3 = ctk.CTkFrame(cofs, fg_color="transparent")
        ro3.pack(fill="x", pady=3)
        ctk.CTkLabel(ro3, text=T("Keep last"), font=F_BODY).pack(side="left",
                                                                 padx=(0, 8))
        self.ent_offsite_keep = ctk.CTkEntry(ro3, width=60)
        self.ent_offsite_keep.insert(0, str(self.cfg.get("offsite_keep", 5)))
        self.ent_offsite_keep.pack(side="left")
        ctk.CTkButton(ro3, text="💾  " + T("Save"), height=32, corner_radius=8,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color="#ffffff",
                      command=self._save_offsite).pack(side="left", padx=(14, 0))

        c4 = self._card(scroll, "Permanent address (DuckDNS)",
                        "A free yourname.duckdns.org address that always points to "
                        "you — the invite never goes stale.")
        rd1 = ctk.CTkFrame(c4, fg_color="transparent")
        rd1.pack(fill="x", pady=3)
        ctk.CTkLabel(rd1, text=T("Domain (without .duckdns.org)"),
                     font=F_BODY).pack(side="left", padx=(0, 10))
        self.ent_duck_domain = ctk.CTkEntry(rd1, width=200)
        self.ent_duck_domain.insert(0, self.cfg.get("duck_domain", ""))
        self.ent_duck_domain.pack(side="left", fill="x", expand=True)
        rd2 = ctk.CTkFrame(c4, fg_color="transparent")
        rd2.pack(fill="x", pady=3)
        ctk.CTkLabel(rd2, text=T("Token"), font=F_BODY).pack(
            side="left", padx=(0, 10))
        self.ent_duck_token = ctk.CTkEntry(rd2, width=200, show="•")
        self.ent_duck_token.insert(0, self.cfg.get("duck_token", ""))
        self.ent_duck_token.pack(side="left", fill="x", expand=True)
        self.lbl_duck = ctk.CTkLabel(c4, text="", font=F_SMALL, text_color=TEXT_DIM,
                                     anchor="w")
        self.lbl_duck.pack(anchor="w", pady=(4, 0))
        rdb = ctk.CTkFrame(c4, fg_color="transparent")
        rdb.pack(fill="x", pady=(6, 0))
        ctk.CTkButton(rdb, text="💾  " + T("Save") + " & update", height=38,
                      corner_radius=10, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color="#ffffff", command=self._save_duckdns
                      ).pack(side="left")
        ctk.CTkButton(rdb, text="🌐  " + T("Open duckdns.org"), height=38,
                      corner_radius=10, fg_color=NEUTRAL,
                      hover_color=NEUTRAL_HOVER, text_color="#ffffff",
                      command=lambda: webbrowser.open("https://www.duckdns.org")
                      ).pack(side="left", padx=(8, 0))
        ctk.CTkLabel(
            c4, text=T("Create a free account at duckdns.org, then paste your "
                       "domain and token here."),
            font=F_SMALL, text_color=TEXT_DIM, anchor="w", justify="left",
        ).pack(anchor="w", pady=(6, 0))

        # --- trophy shelf ---
        ctr = self._card(scroll, "Trophy shelf",
                         T("Little achievements earned by running the server. "
                           "Some are hidden until you get them…"))
        self.trophy_frame = ctk.CTkFrame(ctr, fg_color="transparent")
        self.trophy_frame.pack(fill="x")
        self._render_trophy_shelf()

        c5 = self._card(scroll, "About")
        rex = ctk.CTkFrame(c5, fg_color="transparent")
        rex.pack(fill="x")
        ctk.CTkButton(rex, text="📤  Export app settings", height=34,
                      corner_radius=8, fg_color=SURFACE_2, hover_color=BORDER,
                      command=self._export_cfg).pack(side="left")
        ctk.CTkButton(rex, text="📥  Import app settings", height=34,
                      corner_radius=8, fg_color=SURFACE_2, hover_color=BORDER,
                      command=self._import_cfg).pack(side="left", padx=(8, 0))
        ctk.CTkLabel(
            c5, text="Palworld Server Manager v1.0\nManage your own world 🐑\n"
                     "Hosted with 🖤",
            font=F_SMALL, text_color=TEXT_DIM, anchor="w", justify="left",
        ).pack(anchor="w", pady=(8, 0))

    # ----- announcements helpers -----
    def _add_ann_row(self, tval, text):
        row = ctk.CTkFrame(self.ann_frame, fg_color="transparent")
        row.pack(fill="x", pady=3)
        ent_t = ctk.CTkEntry(row, width=70)
        ent_t.insert(0, tval)
        ent_t.pack(side="left")
        ent_x = ctk.CTkEntry(row, fg_color=SURFACE_2, border_width=0,
                             placeholder_text="Message to broadcast…")
        ent_x.insert(0, text)
        ent_x.pack(side="left", fill="x", expand=True, padx=(8, 8))
        self._ann_rows.append((ent_t, ent_x, row))

        def rm():
            self._ann_rows.remove((ent_t, ent_x, row))
            row.destroy()
        ctk.CTkButton(row, text="✕", width=32, height=28, corner_radius=8,
                      fg_color=SURFACE_2, hover_color=RED_HOVER,
                      command=rm).pack(side="right")

    def _save_announcements(self):
        anns = []
        for ent_t, ent_x, _row in self._ann_rows:
            t = ent_t.get().strip()
            txt = ent_x.get().strip()
            if txt and re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", t):
                anns.append({"time": t, "text": txt, "enabled": True})
        self.cfg["announcements"] = anns
        self.cfg["ann_fired"] = {}
        save_cfg(self.cfg)
        self._toast(f"{len(anns)} announcement(s) saved", "📣")

    # ----- bouncer helpers -----
    def _save_bouncer(self):
        lines = [l.strip() for l in self.txt_approved.get("1.0", "end").splitlines()
                 if l.strip()]
        self.cfg["bouncer_approved"] = lines
        self.cfg["bouncer_enabled"] = bool(self.var_bouncer.get())
        save_cfg(self.cfg)
        self._toast(T("Saved"), "🛡")

    def _approve_online(self):
        approved = set(self.cfg.get("bouncer_approved") or [])
        for name, _uid, sid in self._players:
            if sid:
                approved.add(sid)
                self._log_event(f"🛡 Approved {name} ({sid})")
        self.cfg["bouncer_approved"] = sorted(approved)
        save_cfg(self.cfg)
        self.txt_approved.delete("1.0", "end")
        self.txt_approved.insert("1.0", "\n".join(self.cfg["bouncer_approved"]))
        self._toast(f"{len(approved)} players approved", "👥")

    # ----- cfg export/import -----
    def _export_cfg(self):
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            initialfile="palworld-manager-settings.json",
            filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, indent=2)
            self._toast(f"Settings exported to {os.path.basename(path)}", "📤")
        except OSError as e:
            messagebox.showerror("Error", str(e))

    def _import_cfg(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("not a settings file")
            self.cfg.update({k: v for k, v in data.items()
                             if k in DEFAULT_CFG})
            save_cfg(self.cfg)
        except (OSError, ValueError) as e:
            messagebox.showerror("Error", f"Could not import:\n{e}")
            return
        if messagebox.askyesno(T("Saved"),
                               T("Restart the app now to apply?")):
            self._relaunch()

    # ----- profile helpers -----
    def _add_prof_row(self, prof):
        row = ctk.CTkFrame(self.prof_frame, fg_color=SURFACE_2, corner_radius=10)
        row.pack(fill="x", pady=4)
        inner = ctk.CTkFrame(row, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=6)
        e_name = ctk.CTkEntry(inner, width=130, fg_color=SURFACE,
                              border_width=0)
        e_name.insert(0, prof.get("name", "2× EXP weekend"))
        e_name.pack(side="left")
        om_sd = ctk.CTkOptionMenu(inner, width=64, values=DAY_NAMES,
                                  fg_color=SURFACE, button_color=BORDER)
        om_sd.set(prof.get("sd", "Fri"))
        om_sd.pack(side="left", padx=(8, 2))
        e_st = ctk.CTkEntry(inner, width=58, fg_color=SURFACE, border_width=0)
        e_st.insert(0, prof.get("st", "18:00"))
        e_st.pack(side="left")
        ctk.CTkLabel(inner, text="→", text_color=TEXT_DIM).pack(side="left",
                                                                padx=4)
        om_ed = ctk.CTkOptionMenu(inner, width=64, values=DAY_NAMES,
                                  fg_color=SURFACE, button_color=BORDER)
        om_ed.set(prof.get("ed", "Sun"))
        om_ed.pack(side="left", padx=(2, 2))
        e_et = ctk.CTkEntry(inner, width=58, fg_color=SURFACE, border_width=0)
        e_et.insert(0, prof.get("et", "23:59"))
        e_et.pack(side="left")
        ctk.CTkLabel(inner, text="EXP ×", text_color=TEXT_DIM,
                     font=("Segoe UI", 10)).pack(side="left", padx=(10, 2))
        e_exp = ctk.CTkEntry(inner, width=44, fg_color=SURFACE, border_width=0)
        e_exp.insert(0, str(prof.get("exp", "2")))
        e_exp.pack(side="left")
        ctk.CTkLabel(inner, text="catch ×", text_color=TEXT_DIM,
                     font=("Segoe UI", 10)).pack(side="left", padx=(6, 2))
        e_cap = ctk.CTkEntry(inner, width=44, fg_color=SURFACE, border_width=0)
        e_cap.insert(0, str(prof.get("cap", "2")))
        e_cap.pack(side="left")
        rec = (e_name, om_sd, e_st, om_ed, e_et, e_exp, e_cap, row)
        self._prof_rows.append(rec)

        def rm():
            self._prof_rows.remove(rec)
            row.destroy()
        ctk.CTkButton(inner, text="✕", width=30, height=26, corner_radius=8,
                      fg_color=SURFACE, hover_color=RED_HOVER,
                      command=rm).pack(side="left", padx=(8, 0))

    def _save_profiles(self):
        profs = []
        for (e_name, om_sd, e_st, om_ed, e_et, e_exp, e_cap, _r) in \
                getattr(self, "_prof_rows", []):
            st, et = e_st.get().strip(), e_et.get().strip()
            if not (re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", st) and
                    re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", et)):
                continue
            try:
                float(e_exp.get())
                float(e_cap.get())
            except ValueError:
                continue
            profs.append({"name": e_name.get().strip() or "profile",
                          "sd": om_sd.get(), "st": st,
                          "ed": om_ed.get(), "et": et,
                          "exp": e_exp.get().strip() or "2",
                          "cap": e_cap.get().strip() or "2"})
        self.cfg["profiles"] = profs
        save_cfg(self.cfg)
        self._toast(f"{len(profs)} profile(s) saved", "🚀")

    # ----- offsite helpers -----
    def _pick_offsite_dir(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(title="Choose the offsite backup folder")
        if d:
            self.ent_offsite_dir.delete(0, "end")
            self.ent_offsite_dir.insert(0, d)

    def _save_offsite(self):
        try:
            keep = max(1, int(self.ent_offsite_keep.get().strip() or 5))
        except ValueError:
            messagebox.showerror(T("Invalid values"), "Numbers only, please.")
            return
        self.cfg["offsite_enabled"] = bool(self.var_offsite.get())
        self.cfg["offsite_dir"] = self.ent_offsite_dir.get().strip()
        self.cfg["offsite_keep"] = keep
        save_cfg(self.cfg)
        self._toast(T("Saved"), "📤")

    def _set_accent(self, name):
        if self.cfg.get("accent") == name:
            return
        self.cfg["accent"] = name
        save_cfg(self.cfg)
        if messagebox.askyesno(APP_TITLE, T("Restart the app now to apply?")):
            self._relaunch()

    def _set_language(self, value):
        lang = "fr" if value == "Français" else "en"
        if self.cfg.get("lang") == lang:
            return
        self.cfg["lang"] = lang
        save_cfg(self.cfg)
        if messagebox.askyesno(APP_TITLE, T("Restart the app now to apply?")):
            self._relaunch()

    def _relaunch(self):
        try:
            if getattr(sys, "frozen", False):
                os.startfile(sys.executable)
            else:
                subprocess.Popen([sys.executable, os.path.abspath(__file__)])
        except OSError:
            pass
        self.after(300, self._quit_app)

    def _save_notify_pref(self):
        self.cfg["tray_notifications"] = bool(self.var_notify.get())
        save_cfg(self.cfg)

    def _save_motd(self):
        self.cfg["motd"] = self.ent_motd.get().strip()
        self.cfg["motd_enabled"] = bool(self.var_motd.get())
        save_cfg(self.cfg)
        self._toast(T("Saved"), "💾")

    def _save_discord(self):
        url = self.ent_discord.get().strip()
        if url and not url.startswith("https://discord.com/api/webhooks/"):
            if not messagebox.askyesno(
                    T("Hmm…"),
                    "That doesn't look like a Discord webhook URL.\n"
                    "Save it anyway?"):
                return
        self.cfg["discord_webhook"] = url
        save_cfg(self.cfg)
        self._toast(T("Saved"), "💾")

    def _test_discord(self):
        url = self.ent_discord.get().strip() or self.cfg.get("discord_webhook")

        def work():
            ok = discord_send(url, "✅ **PalworldControl** connected — "
                                    "server notifications will arrive here!")
            self._log_event("🔔 Discord test message sent" if ok
                            else "⚠ Discord test failed — check the webhook URL")
        if not url:
            self._toast("Paste a webhook URL first.", "⚠")
            return
        self._toast(T("Sending…"), "🔔")
        threading.Thread(target=work, daemon=True).start()

    def _save_rotation(self):
        t = self.ent_rotate_hour.get().strip()
        if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", t):
            messagebox.showerror(T("Invalid time"), "Use HH:MM (e.g. 09:00).")
            return
        self.cfg["rotate_password"] = bool(self.var_rotate.get())
        self.cfg["rotate_day"] = self.om_rotate_day.get()
        self.cfg["rotate_hour"] = t
        save_cfg(self.cfg)
        self._toast(T("Saved"), "🔑")

    def _save_steamkey(self):
        key = self.ent_steamkey.get().strip()
        self.cfg["steam_api_key"] = key
        save_cfg(self.cfg)
        self._toast(T("Saved"), "🖼")
        if key and self._players:
            sids = [p[2] for p in self._players if p[2]]

            def work():
                if fetch_steam_avatars(key, sids):
                    self.q.put(("avatars", None))
            threading.Thread(target=work, daemon=True).start()

    def _save_autoupd(self):
        t = self.ent_autoupd.get().strip()
        if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", t):
            messagebox.showerror(T("Invalid time"), "Use HH:MM (e.g. 05:30).")
            return
        self.cfg["auto_update_time"] = t
        self.cfg["auto_update_enabled"] = bool(self.var_autoupd.get())
        save_cfg(self.cfg)
        self._toast(T("Saved"), "💾")

    def _save_backups_prefs(self):
        try:
            hours = max(0, int(self.ent_bk_hours.get().strip() or 0))
            keep = max(1, int(self.ent_bk_keep.get().strip() or 20))
        except ValueError:
            messagebox.showerror(T("Invalid values"), "Numbers only, please.")
            return
        self.cfg["backup_interval_h"] = hours
        self.cfg["backup_keep"] = keep
        save_cfg(self.cfg)
        messagebox.showinfo(T("Saved"), f"Automatic backups every {hours}h, "
                                        f"keeping the last {keep}.")

    def _save_duckdns(self):
        self.cfg["duck_domain"] = self.ent_duck_domain.get().strip()
        self.cfg["duck_token"] = self.ent_duck_token.get().strip()
        save_cfg(self.cfg)
        if not (self.cfg["duck_domain"] and self.cfg["duck_token"]):
            self.lbl_duck.configure(text=T("Saved") + " — disabled (empty).")
            return

        def work():
            ok = duckdns_update(self.cfg["duck_domain"], self.cfg["duck_token"])
            def done():
                self.lbl_duck.configure(
                    text=("✅  DuckDNS updated — invite address is now "
                           f"{self.cfg['duck_domain']}.duckdns.org")
                           if ok else "⚠  DuckDNS said KO — check domain/token.")
            self.after(0, done)
        threading.Thread(target=work, daemon=True).start()

    # ===== invite & events =====
    def _refresh_lan_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
        except OSError:
            ip = "unknown"
        self.lbl_lan.configure(text=f"{ip}:{GAME_PORT}")

    def _fetch_public_ip(self):
        self.lbl_pub.configure(text="detecting…", text_color=TEXT_DIM)

        def work():
            try:
                with urllib.request.urlopen("https://api.ipify.org", timeout=8) as r:
                    ip = r.read().decode().strip()
            except OSError:
                ip = None
            self.q.put(("pubip", ip))
        threading.Thread(target=work, daemon=True).start()

    def _join_address(self):
        if self.cfg.get("duck_domain") and self.cfg.get("duck_token"):
            return f"{self.cfg['duck_domain']}.duckdns.org:{GAME_PORT}"
        return f"{self._public_ip or 'YOUR-PUBLIC-IP'}:{GAME_PORT}"

    def _invite_text(self):
        addr = self._join_address()
        try:
            pw = load_server_settings().get("ServerPassword", "").strip('"')
        except (OSError, ValueError):
            pw = "?"
        return (
            "🐑 Come play Palworld with me!\n"
            "\n"
            "1) Open Palworld → Multiplayer\n"
            "2) Scroll down and choose \"Connect via IP\"\n"
            f"3) Enter this address:  {addr}\n"
            f"4) Password:  {pw}\n"
            "\n"
            "See you in-game! ❤"
        )

    def _copy_invite(self):
        self.clipboard_clear()
        self.clipboard_append(self._invite_text())
        self.update()
        self._toast(T("Invite copied — paste it to your friends! ✅"), "📋")

    def _copy_addr(self):
        self.clipboard_clear()
        self.clipboard_append(self._join_address())
        self.update()
        self._toast(T("Address copied. ✅"), "📋")

    def _log_event(self, text):
        stamp = datetime.now().strftime("%d/%m %H:%M")
        line = f"[{stamp}]  {text}"
        self._events.append(line)
        save_events(self._events)
        self.q.put(("event", line))

    def _append_event(self, line):
        self.txt_activity.configure(state="normal")
        self.txt_activity.insert("end", line + "\n")
        self.txt_activity.see("end")
        self.txt_activity.configure(state="disabled")
        self._render_playtimes()
        self._draw_timeline()

    def _notify(self, title, msg):
        if not (self._tray and self.cfg.get("tray_notifications", True)):
            return
        try:
            self._tray.notify(msg, title)
        except Exception:
            pass

    def _discord(self, content):
        """Send a message to the configured Discord webhook (async, safe)."""
        hook = self.cfg.get("discord_webhook")
        if not hook:
            return
        threading.Thread(target=discord_send, args=(hook, content),
                         daemon=True).start()

    # ----- password rotation -----
    def _rotate_password(self):
        """New random password → ini → restart → clipboard. Runs in monitor."""
        try:
            pw = generate_password()
            # deferred while running — flushed by the restart right below
            apply_ini_updates({"ServerPassword": _quote(pw)})
            self._log_event("🔑 Password rotated automatically")
            self._notify("🔑 " + T("Password rotated"),
                         T("New invite copied to clipboard"))
            self._discord("🔑 Weekly password rotation — ask the host for the new "
                          "invite!")
            if is_running():
                self._warn_and_wait()
                stop_server()
                start_server()
            self.q.put(("rotated", pw))
        except (OSError, ValueError) as e:
            self._log_event(f"⚠ Password rotation failed: {e}")

    def _copy_rotated(self, pw):
        """UI thread: put the fresh invite in the clipboard + toast."""
        try:
            addr = (f"{self.cfg.get('duck_domain')}.duckdns.org"
                    if self.cfg.get("duck_domain")
                    else (self._public_ip or "your-ip"))
            self.clipboard_clear()
            self.clipboard_append(
                f"Palworld — My Server\nAddress: {addr}:{GAME_PORT}\n"
                f"Password: {pw}")
        except tk.TclError:
            pass
        self._toast(T("New password copied — invite ready to send!"), "🔑")

    # ----- display names (nicknames) -----
    def _disp_name(self, name, sid=None):
        nicks = self.cfg.get("nicknames") or {}
        if sid and sid in nicks:
            return nicks[sid]
        return nicks.get(name, name)

    # ----- trophies -----
    def _trophy_conditions(self):
        ev = "\n".join(self._events)
        joined = any("👤" in l and "joined" in l for l in self._events)
        night = any(re.match(r"\[\d{2}/\d{2} 0[2-4]:", l) for l in self._events)
        verified = sum(1 for v in (load_verified() or {}).values() if v is True)
        gc = load_guild_cache() or {}
        data = gc.get("data") or {}
        facts = data.get("facts") or {}
        gold = sum(p.get("gold", 0) for p in data.get("inventory") or [])
        hours = sum(s for _n, s in self._parse_playtimes())
        return {
            "first_friend": joined,
            "uptime_7": longest_up_run(self._uptime) >= 7 * 1440,
            "hours_100": hours >= 100 * 3600,
            "night_owl": night,
            "verified_10": verified >= 10,
            "pals_1000": (facts.get("pals_total") or 0) >= 1000,
            "cartographer": bool(gc.get("data")),
            "crash_survivor": "💥" in ev,
            "gold_rush": gold >= 1000000,
            "santa": "🎁" in ev,
        }

    def _trophy_check(self):
        won = self.cfg.get("trophies") or {}
        conds = self._trophy_conditions()
        for t in TROPHIES:
            if t["id"] not in won and conds.get(t["id"]):
                self._award_trophy(t)

    def _award_trophy(self, t):
        self.cfg.setdefault("trophies", {})[t["id"]] = \
            datetime.now().strftime("%Y-%m-%d")
        save_cfg(self.cfg)
        title = t["fr"] if LANG == "fr" else t["en"]
        self._log_event(f"🏆 Trophy earned: {title}")
        self._toast(f"{t['icon']}  {T('Trophy earned!')} {title}", "🏆")
        self._notify("🏆 " + T("Trophy earned!"), title)
        self._chime("ok")
        self._confetti()
        if hasattr(self, "trophy_frame"):
            self._render_trophy_shelf()

    def _confetti(self):
        try:
            cv = tk.Canvas(self, highlightthickness=0,
                           bg=self._hex(BG))
        except tk.TclError:
            return
        cv.place(x=0, y=0, relwidth=1, relheight=1)
        pieces = []
        colors = ["#38b6f0", "#22c55e", "#f59e0b", "#a78bfa", "#f472b6"]
        for i in range(42):
            x = (i * 37) % max(1, self.winfo_width())
            piece = cv.create_rectangle(
                x, -20 - (i % 7) * 24, x + 8, -12 - (i % 7) * 24,
                fill=colors[i % len(colors)], outline="")
            pieces.append([piece, 3 + (i % 5) * 1.7])

        def step():
            for p in pieces:
                cv.move(p[0], (p[1] - 4) * 0.6, p[1])
            if pieces and float(cv.coords(pieces[0][0])[1]) < \
                    self.winfo_height() + 40:
                self.after(28, step)
            else:
                cv.destroy()

        self.after(28, step)

    def _render_trophy_shelf(self):
        if not hasattr(self, "trophy_frame"):
            return
        for w in self.trophy_frame.winfo_children():
            w.destroy()
        won = self.cfg.get("trophies") or {}
        lbl = ctk.CTkLabel(
            self.trophy_frame,
            text=f"{T('Earned')}: {len(won)} / {len(TROPHIES)}",
            font=F_BODY_B, text_color=ACCENT, anchor="w")
        lbl.pack(anchor="w", pady=(0, 4))
        grid = ctk.CTkFrame(self.trophy_frame, fg_color="transparent")
        grid.pack(fill="x")
        for i in range(3):
            grid.grid_columnconfigure(i, weight=1, uniform="tr")
        for i, t in enumerate(TROPHIES):
            got = t["id"] in won
            cell = ctk.CTkButton(
                grid, text=t["icon"] if got else "❓",
                font=("Segoe UI Emoji", 30 if got else 24),
                width=64, height=64, corner_radius=14,
                fg_color=ACCENT_SOFT if got else SURFACE_2,
                hover_color=BORDER, text_color=ACCENT if got else TEXT_DIM,
                command=lambda tt=t: self._trophy_detail(tt))
            cell.grid(row=i // 3, column=i % 3, padx=4, pady=4)
            if got:
                Tooltip(cell, f"{t['icon']} {t['fr'] if LANG == 'fr' else t['en']}"
                        f" — {won[t['id']]}")
            else:
                Tooltip(cell, "❓ " + (t["d_fr"] if LANG == "fr" else t["d_en"]))

    def _trophy_detail(self, t):
        won = (self.cfg.get("trophies") or {}).get(t["id"])
        body = (t["fr"] if LANG == "fr" else t["en"]) + "\n" + \
               (t["d_fr"] if LANG == "fr" else t["d_en"])
        if won:
            body += "\n\n🏆 " + T("Earned on") + " " + won
        else:
            body += "\n\n🔒 " + T("Not earned yet…")
        messagebox.showinfo(t["icon"], body)

    # ----- invite card -----
    def _export_invite_card(self):
        try:
            from PIL import Image, ImageDraw, ImageEnhance
        except ImportError:
            self._toast("PIL missing — cannot render the card.", "⚠")
            return
        addr = (f"{self.cfg.get('duck_domain')}.duckdns.org"
                if self.cfg.get("duck_domain")
                else (self._public_ip or "your-ip")) + f":{GAME_PORT}"
        try:
            s = load_server_settings().get("ServerPassword", "").strip('"')
        except (OSError, ValueError):
            s = ""
        show_pw = bool(s) and messagebox.askyesno(
            T("Invite card"),
            T("Include the password on the card?") +
            "\n\n" + T("(Choose “No” if you will send it in a private message.)"))

        def font(paths, size):
            for p in paths:
                try:
                    from PIL import ImageFont
                    return ImageFont.truetype(p, size)
                except OSError:
                    continue
            from PIL import ImageFont
            return ImageFont.load_default()

        from PIL import ImageFont
        W, H = 900, 560
        img = Image.new("RGB", (W, H), (11, 18, 32))
        bg_path = os.path.join(BASE, "app", "bg.png")
        if os.path.exists(bg_path):
            try:
                art = Image.open(bg_path).convert("RGB")
                art = art.resize((W, W * art.size[1] // art.size[0]))
                art = art.crop((0, 0, W, H))
                art = ImageEnhance.Brightness(art).enhance(0.34)
                img = art
            except Exception:
                pass
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, W, 118], fill=(8, 12, 22))
        f_title = font([r"C:\Windows\Fonts\seguisb.ttf"], 38)
        f_big = font([r"C:\Windows\Fonts\seguisb.ttf"], 46)
        f_sub = font([r"C:\Windows\Fonts\segoeui.ttf"], 18)
        d.text((40, 34), "MY PALWORLD SERVER", font=f_title, fill=(255, 255, 255))
        d.text((42, 86), T("Join our Palworld server!"), font=f_sub,
               fill=(150, 190, 230))
        d.text((40, 160), T("Address"), font=f_sub, fill=(141, 161, 189))
        d.text((40, 190), addr, font=f_big, fill=(56, 182, 240))
        if show_pw:
            d.text((40, 280), T("Password"), font=f_sub, fill=(141, 161, 189))
            d.text((40, 310), s, font=f_big, fill=(255, 255, 255))
        else:
            d.text((40, 290), T("Password: ask the host 😉"), font=f_big,
                   fill=(220, 220, 230))
        steps = (T("In Palworld: Multiplayer → Join via IP → paste the address") +
                 (" + " + T("password") if show_pw else "") + ".")
        d.text((40, 410), steps, font=f_sub, fill=(180, 196, 216))
        d.rectangle([0, H - 46, W, H], fill=(8, 12, 22))
        d.text((40, H - 34), "My Palworld Server 🐑 · Palworld Server Manager",
               font=f_sub, fill=(120, 140, 170))
        # QR code with the join info
        try:
            import qrcode
            payload = f"Palworld\n{addr}\n"
            payload += f"Password: {s}" if show_pw else \
                T("Password: ask the host")
            qr = qrcode.QRCode(border=1, box_size=6)
            qr.add_data(payload)
            qr.make(fit=True)
            qimg = qr.make_image(fill_color="#0b1220",
                                 back_color="#e8f2fc").convert("RGB")
            img.paste(qimg, (W - 40 - qimg.size[0], H - 80 - qimg.size[1]))
        except Exception:
            pass
        out = os.path.join(BASE, "invite_card.png")
        try:
            img.save(out)
        except OSError as e:
            self._toast(f"Could not save: {e}", "⚠")
            return
        try:
            os.startfile(out)
        except OSError:
            pass
        self._log_event("🖼 Invite card exported")
        self._toast(T("Invite card saved") + f" → {out}", "🖼")
        self._trophy_check()

    # ----- player rename -----
    def _rename_player(self, p):
        from tkinter import simpledialog
        new = simpledialog.askstring(
            T("Rename player"),
            T("Display name for") + f" {p[0]}:",
            initialvalue=self._disp_name(p[0], p[2]))
        if new is None:
            return
        new = new.strip()[:24]
        nicks = self.cfg.get("nicknames") or {}
        if new and new != p[0]:
            nicks[p[2]] = new
        else:
            nicks.pop(p[2], None)
        self.cfg["nicknames"] = nicks
        save_cfg(self.cfg)
        self._render_players(self._players)
        self._toast(T("Saved"), "🏷")

    # ----- sessions timeline -----
    def _parse_sessions(self):
        sessions = {}
        pat = re.compile(r"\[(\d{2}/\d{2} \d{2}:\d{2})\]  👤 (.+?) (joined|left)")
        year = datetime.now().year
        for line in self._events:
            m = pat.match(line)
            if not m:
                continue
            try:
                dt = datetime.strptime(m.group(1) + f" {year}",
                                       "%d/%m %H:%M %Y")
            except ValueError:
                continue
            name, ev = m.group(2), m.group(3)
            if ev == "joined":
                sessions.setdefault(name, []).append([dt, None])
            else:
                for s in reversed(sessions.get(name, [])):
                    if s[1] is None:
                        s[1] = dt
                        break
        return sessions

    def _draw_timeline(self):
        cv = getattr(self, "cv_timeline", None)
        if cv is None:
            return
        cv.delete("all")
        sessions = self._parse_sessions()
        now = datetime.now()
        start = now - timedelta(days=7)
        totals = self._parse_playtimes() or []
        names = [n for n, _s in totals if n in sessions][:6] or \
            list(sessions.keys())[:6]
        if not names:
            self.lbl_timeline.configure(
                text=T("Sessions will appear once people have played."))
            return
        self.lbl_timeline.configure(text="")
        w = max(420, cv.winfo_width() or 640)
        row_h, top = 30, 8
        h = top + row_h * len(names)
        cv.configure(height=h + 22)
        span = 7 * 86400

        def X(dt):
            return 8 + (dt - start).total_seconds() / span * (w - 16)

        for i, day in enumerate(range(7)):
            x = 8 + i * (w - 16) / 7
            if i:
                cv.create_line(x, top - 4, x, h - 4,
                               fill=self._hex(BORDER))
            dd = (start + timedelta(days=i)).strftime("%a")
            cv.create_text(x + (w - 16) / 14, h + 2, text=dd,
                           fill=self._hex(TEXT_DIM), font=("Segoe UI", 8))
        for r, name in enumerate(names):
            y = top + r * row_h
            color = AVATAR_COLORS[sum(name.encode()) % len(AVATAR_COLORS)]
            sid = self._sid_for(name)
            cv.create_text(10, y + row_h / 2, anchor="w",
                           text=self._disp_name(name, sid)[:14],
                           fill=self._hex(TEXT), font=("Segoe UI", 9, "bold"))
            for j, l in sessions.get(name, []):
                end = l or now
                x0, x1 = X(max(j, start)), X(min(end, now))
                if x1 - x0 < 1.5:
                    x1 = x0 + 1.5
                cv.create_rectangle(x0, y + 6, x1, y + row_h - 8,
                                    fill=color, outline="")
        cv.configure(scrollregion=(0, 0, w, h + 14))

    # ----- repair -----
    def _repair(self):
        if self._busy:
            return
        if not messagebox.askyesno(
                T("Repair game files"),
                T("This stops the server, re-downloads any corrupted game "
                  "files, then restarts. Takes 5-15 minutes. Continue?")):
            return
        win = ctk.CTkToplevel(self)
        win.title(T("Repair game files"))
        win.geometry("760x440")
        txt = ctk.CTkTextbox(win, wrap="word", font=F_MONO)
        txt.pack(fill="both", expand=True, padx=8, pady=8)
        win.grab_set()

        def line_cb(s):
            def _append():
                txt.insert("end", s + "\n")
                txt.see("end")
            self.after(0, _append)

        def work():
            self._busy = True
            try:
                steamcmd_update(line_cb)
                self._log_event("🔧 Game files verified / repaired")
                self.after(0, lambda: self._toast(T("Repair finished"), "🔧"))
            finally:
                self._busy = False
        threading.Thread(target=work, daemon=True).start()

    # ----- weekly Discord recap -----
    def _weekly_recap_text(self):
        now = datetime.now()
        week = [ts for ts, _u in self._uptime
                if now.timestamp() - ts * 60 <= 7 * 86400]
        ups = [u for ts, u in self._uptime
               if now.timestamp() - ts * 60 <= 7 * 86400]
        pct = (100.0 * sum(ups) / len(ups)) if ups else 0.0
        lines = [f"📊 **{T('Weekly recap')} — Palworld Server**"]
        tops = self._parse_playtimes()[:5]
        if tops:
            per = ", ".join(f"{self._disp_name(n, self._sid_for(n))} "
                            f"{int(s // 3600)}h{int(s % 3600 // 60):02d}"
                            for n, s in tops)
            lines.append(f"⏱️ {T('Playtime')}: {per}")
        lines.append(f"✅ {T('Uptime')}: {pct:.1f}%")
        verified = sum(1 for v in (load_verified() or {}).values() if v is True)
        lines.append(f"💾 {T('Backups verified')}: {verified}")
        crashes = sum(1 for l in self._events if "💥" in l)
        lines.append(f"💥 {T('Crashes')}: {crashes}")
        gc = load_guild_cache() or {}
        data = gc.get("data") or {}
        facts = data.get("facts") or {}
        gt = data.get("game_time") or {}
        if facts:
            lines.append(f"🐑 {facts.get('pals_total', '—')} Pals · "
                         f"{facts.get('bases', '—')} bases"
                         + (f" · {T('Day')} {gt.get('day', '?')}" if gt else ""))
        return "\n".join(lines)

    def _weekly_recap(self):
        msg = self._weekly_recap_text()
        hook = self.cfg.get("discord_webhook")
        if hook and discord_send(hook, msg):
            self._log_event("📊 Weekly recap sent to Discord")
        else:
            self._log_event("📊 Weekly recap (Discord not configured):\n" + msg)

    # ----- inventory card -----
    def _render_inventory(self, data):
        if not hasattr(self, "inv_frame"):
            return
        for w in self.inv_frame.winfo_children():
            w.destroy()
        inv = (data or {}).get("inventory") or []
        if not inv:
            ctk.CTkLabel(self.inv_frame,
                         text=T("Scan the world to see who hoards what."),
                         font=F_SMALL, text_color=TEXT_DIM).pack(anchor="w")
            return
        inv = sorted(inv, key=lambda p: -p.get("gold", 0))
        for p in inv:
            row = ctk.CTkFrame(self.inv_frame, fg_color=SURFACE_2,
                               corner_radius=10)
            row.pack(fill="x", pady=3)
            sid = (self.cfg.get("player_ids") or {}).get(p["name"])
            av = self._avatar(row, p["name"], sid)
            av.pack(side="left", padx=(8, 10), pady=6)
            box = ctk.CTkFrame(row, fg_color="transparent")
            box.pack(side="left", fill="x", expand=True, pady=5)
            ctk.CTkLabel(box, anchor="w", font=F_BODY_B, text_color=TEXT,
                         text=f"{self._disp_name(p['name'], sid)}    ·    "
                              f"🪙 {p.get('gold', 0):,}").pack(anchor="w")
            items = ", ".join(f"{n} ×{c}"
                              for n, c in (p.get("top_items") or [])[:4])
            if items:
                ctk.CTkLabel(box, anchor="w", font=F_SMALL,
                             text_color=TEXT_DIM, text=items).pack(anchor="w")

    # ----- gifts & events -----
    def _guild_members(self):
        """[(name, uid)] of real players from the guild cache."""
        data = self._last_guild_data or (load_guild_cache() or {}).get("data") \
            or {}
        out = []
        for p in data.get("all_players") or []:
            uid = p.get("uid", "")
            if uid and uid != "00000000000000000000000000000001":
                out.append((p.get("name") or uid[:8], uid))
        return out or []

    def _add_ge_row(self, tval, gold, items, pal, enabled):
        if not hasattr(self, "ge_frame"):
            return
        row = ctk.CTkFrame(self.ge_frame, fg_color="transparent")
        row.pack(fill="x", pady=3)
        var_en = tk.BooleanVar(value=bool(enabled))
        ctk.CTkSwitch(row, text="", width=48, variable=var_en).pack(side="left")
        ent_t = ctk.CTkEntry(row, width=64)
        ent_t.insert(0, tval)
        ent_t.pack(side="left", padx=(6, 4))
        ent_g = ctk.CTkEntry(row, width=90, placeholder_text=T("gold"))
        ent_g.insert(0, str(gold or ""))
        ent_g.pack(side="left", padx=4)
        ent_i = ctk.CTkEntry(row, width=130,
                             placeholder_text=T("items (id xN, id xN)"))
        ent_i.insert(0, items or "")
        ent_i.pack(side="left", padx=4, fill="x", expand=True)
        ent_p = ctk.CTkEntry(row, width=110,
                             placeholder_text=T("Pal id (optional)"))
        ent_p.insert(0, pal or "")
        ent_p.pack(side="left", padx=4)
        del_btn = ctk.CTkButton(row, text="✖", width=34, height=28,
                                corner_radius=8, fg_color=SURFACE_2,
                                hover_color=RED_HOVER, text_color=TEXT_DIM,
                                command=lambda: (self._ge_rows.remove(
                                    [ent_t, ent_g, ent_i, ent_p, var_en, row]),
                                                 row.destroy()))
        del_btn.pack(side="left")
        self._ge_rows.append([ent_t, ent_g, ent_i, ent_p, var_en, row])

    def _save_ge(self):
        events = []
        for ent_t, ent_g, ent_i, ent_p, var_en, _row in self._ge_rows:
            t = ent_t.get().strip()
            g = ent_g.get().strip()
            if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", t or ""):
                messagebox.showerror(T("Invalid time"),
                                     T("Use HH:MM (e.g. 20:00)."))
                return
            try:
                gold = int(g) if g else 0
            except ValueError:
                messagebox.showerror(T("Invalid values"),
                                     T("Gold must be a number."))
                return
            events.append({"time": t, "gold": gold,
                           "items": ent_i.get().strip(),
                           "pal": ent_p.get().strip(),
                           "enabled": bool(var_en.get())})
        self.cfg["gift_events"] = events
        self.cfg.pop("gift_fired", None)
        save_cfg(self.cfg)
        self._toast(T("Saved"), "🎁")

    def _parse_items_text(self, text):
        """'PalSphere x20, Arrow x100' -> [['PalSphere', 20], ...]"""
        out = []
        for part in re.split(r"[,;\n]", text or ""):
            m = re.match(r"\s*([A-Za-z_0-9]+)\s*[x×]\s*(\d+)\s*$",
                         part, re.IGNORECASE)
            if m:
                out.append([m.group(1), int(m.group(2))])
        return out

    def _open_gift_wizard(self):
        members = self._guild_members()
        data = self._last_guild_data or (load_guild_cache() or {}).get("data") \
            or {}
        pal_meta = load_pal_meta()
        item_meta = load_item_meta()
        if pal_meta:
            # full catalog: every pal with an icon, paldeck order; world-seen
            # ids are always kept (they are proven-valid on this server)
            world = data.get("pal_catalog") or []
            pal_cat = [p for p in pal_meta
                       if not p.startswith(("RAID_", "GYM_"))]
            known = set(pal_cat)
            pal_cat += [p for p in sorted(world) if p not in known]
            pal_cat.sort(key=lambda p: (pal_meta.get(p, {}).get("deck")
                                        or 999, pal_disp(p).lower()))
        else:
            pal_cat = data.get("pal_catalog") or ["Lamball"]
        if item_meta:
            # world ids first (proven-valid, e.g. legacy lowercase 'bone'),
            # then the full data table in game order — casing duplicates skip
            world_i = data.get("item_catalog") or []
            seen = {_norm_key(w) for w in world_i}
            item_cat = list(world_i) + [
                i for i in sorted(item_meta,
                                  key=lambda i: item_meta[i].get("sort")
                                  or 999999)
                if _norm_key(i) not in seen]
        else:
            item_cat = data.get("item_catalog") or ["PalSphere"]
        paldex = load_paldex()
        if not load_item_meta() and not getattr(self, "_gift_dl", False):
            self._gift_dl = True

            def _fetch_art():
                ok = bootstrap_gift_assets()
                global _ITEM_META, _PAL_META
                _ITEM_META, _PAL_META = None, None
                self._gift_dl = False

                def done():
                    self._toast(
                        T("Gift artwork ready \u2014 items and Pals now "
                          "have icons.") if ok else
                        T("Could not download the gift artwork "
                          "(offline?). Icons stay basic."),
                        "\U0001f3a8" if ok else "\u26a0")
                    try:
                        if getattr(self, "_gw_grid_inner", None) and \
                                self._gw_grid_inner.winfo_exists():
                            self._gw_render(getattr(self, "_gw_pal_cat", []),
                                            getattr(self, "_gw_item_cat", []),
                                            getattr(self, "_gw_paldex", None))
                    except tk.TclError:
                        pass
                self.after(0, done)
            threading.Thread(target=_fetch_art, daemon=True).start()

        win = ctk.CTkToplevel(self)
        win.title(T("Give a gift"))
        win.geometry("980x680")
        win.grab_set()

        # ---------------- left: visual picker ----------------
        left = ctk.CTkFrame(win, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=(14, 6), pady=12)

        topbar = ctk.CTkFrame(left, fg_color="transparent")
        topbar.pack(fill="x", pady=(0, 6))
        self._gw_search = ctk.CTkEntry(topbar, height=34, corner_radius=10,
                                       fg_color=SURFACE, border_width=1,
                                       border_color=BORDER,
                                       placeholder_text=T("Search… (name or id)"))
        self._gw_search.pack(side="left", fill="x", expand=True)
        self._gw_tab = tk.StringVar(value="pals")
        seg = ctk.CTkSegmentedButton(
            topbar, values=["\U0001f43e  " + T("Pals"), "\U0001f392  " + T("Items")],
            variable=self._gw_tab,
            command=lambda _v: self._gw_render(pal_cat, item_cat, paldex))
        seg.pack(side="left", padx=(8, 0))

        self._gw_grid = ctk.CTkScrollableFrame(left, fg_color="transparent")
        self._gw_grid.pack(fill="both", expand=True)
        # NB: never destroy a ScrollableFrame's own children (that kills its
        # internal canvas) — clear this plain inner frame instead
        self._gw_grid_inner = ctk.CTkFrame(self._gw_grid,
                                           fg_color="transparent")
        self._gw_grid_inner.pack(fill="both", expand=True)

        # ---------------- right: basket ----------------
        right = ctk.CTkFrame(win, corner_radius=14, fg_color=SURFACE,
                             border_width=1, border_color=BORDER, width=300)
        right.pack(side="right", fill="y", padx=(6, 14), pady=12)
        right.pack_propagate(False)
        pad = ctk.CTkFrame(right, fg_color="transparent")
        pad.pack(fill="both", expand=True, padx=12, pady=10)
        ctk.CTkLabel(pad, text="\U0001fa7a  " + T("Basket"),
                     font=(F_DISPLAY, 16, "bold"),
                     text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(pad, text=T("To"), font=F_SMALL,
                     text_color=TEXT_DIM).pack(anchor="w", pady=(6, 0))
        who = ctk.CTkComboBox(
            pad, width=270,
            values=["\U0001f381 " + T("Everyone (guild)")] +
                   [f"{n}  \u00b7  {u[:8]}" for n, u in members],
            fg_color=SURFACE_2)
        who.set("\U0001f381 " + T("Everyone (guild)"))
        who.pack(fill="x")
        ctk.CTkLabel(pad, text="\U0001fa99  " + T("Gold"), font=F_SMALL,
                     text_color=TEXT_DIM).pack(anchor="w", pady=(8, 0))
        ent_gold = ctk.CTkEntry(pad, width=120, placeholder_text="0")
        ent_gold.pack(fill="x")

        ctk.CTkLabel(pad, text=T("Selected"), font=F_SMALL,
                     text_color=TEXT_DIM).pack(anchor="w", pady=(8, 0))
        self._gw_basket_frame = ctk.CTkScrollableFrame(pad, height=250,
                                                       fg_color="transparent")
        self._gw_basket_frame.pack(fill="both", expand=True)
        self._gw_basket_inner = ctk.CTkFrame(self._gw_basket_frame,
                                             fg_color="transparent")
        self._gw_basket_inner.pack(fill="both", expand=True)

        self._gw_sel = {}          # id -> {"kind": pal/item, qty/lv: int}
        self._gw_buttons = {}      # id -> tile button
        self._gw_pal_cat = pal_cat
        self._gw_item_cat = item_cat

        def refresh_basket():
            for w in list(self._gw_basket_inner.winfo_children()):
                try:
                    w.destroy()
                except tk.TclError:
                    pass
            if not self._gw_sel:
                ctk.CTkLabel(self._gw_basket_inner, text="\u2014",
                             font=F_SMALL, text_color=TEXT_DIM).pack(pady=4)
                return
            for sid, info in list(self._gw_sel.items()):
                row = ctk.CTkFrame(self._gw_basket_inner, fg_color=SURFACE_2,
                                   corner_radius=10)
                row.pack(fill="x", pady=3)
                if info["kind"] == "pal":
                    img = pal_icon2_path(sid) or cached_pal_image(sid, paldex)
                else:
                    img = item_icon_path(sid)
                if img:
                    ci = ctimg(img, (28, 28))
                    if ci is not None:
                        ctk.CTkLabel(row, text="", image=ci).pack(
                            side="left", padx=(8, 6))
                    else:
                        img = None
                if not img:
                    ctk.CTkLabel(row, text=item_emoji(sid) if
                                 info["kind"] == "item" else "\U0001f43e",
                                 width=30,
                                 font=("Segoe UI Emoji", 14)
                                 ).pack(side="left", padx=(8, 6))
                nm = (pal_disp(sid) if info["kind"] == "pal"
                      else item_disp(sid))
                ctk.CTkLabel(row, text=nm[:20], font=F_SMALL, anchor="w",
                             text_color=TEXT).pack(side="left", fill="x",
                                                   expand=True)
                ent = ctk.CTkEntry(row, width=56)
                ent.insert(0, str(info.get("lv") or info.get("qty") or ""))
                ent.pack(side="left", padx=(4, 2))

                def changed(e, s=sid, box=ent):
                    try:
                        v = int(box.get() or 0)
                    except ValueError:
                        return
                    key = "lv" if self._gw_sel[s]["kind"] == "pal" else "qty"
                    self._gw_sel[s][key] = v

                ent.bind("<KeyRelease>", changed)
                ctk.CTkButton(row, text="\u2716", width=30, height=26,
                              corner_radius=8, fg_color=SURFACE,
                              hover_color=RED_HOVER, text_color=TEXT_DIM,
                              command=lambda s=sid: (self._gw_sel.pop(s, None),
                                                     refresh_basket(),
                                                     self._gw_mark(s, False))
                              ).pack(side="left", padx=(2, 6))

        self._gw_refresh_basket = refresh_basket
        refresh_basket()

        hint = ctk.CTkLabel(
            pad, justify="left", font=F_SMALL, text_color=TEXT_DIM, anchor="w",
            text=T("The server restarts for a minute while the gift is "
                   "written into the save (players get a warning). A backup "
                   "is made first \u2014 worst case, one click restores."))
        hint.pack(anchor="w", pady=(6, 4))

        def give():
            try:
                gold = int(ent_gold.get().strip() or 0)
            except ValueError:
                messagebox.showerror(T("Invalid values"),
                                     T("Gold must be a number."), parent=win)
                return
            items = [[s, i["qty"]] for s, i in self._gw_sel.items()
                     if i["kind"] == "item" and i.get("qty", 0) > 0]
            pals = [{"id": s, "lv": max(1, i.get("lv", 30))}
                    for s, i in self._gw_sel.items() if i["kind"] == "pal"]
            if not gold and not items and not pals:
                messagebox.showerror(T("Hmm\u2026"),
                                     T("Add some gold, items or a Pal first!"),
                                     parent=win)
                return
            sel = who.get()
            if sel.startswith("\U0001f381"):
                targets = members
                names = "everyone"
            else:
                targets = [next((n, u) for n, u in members
                                if sel.startswith(n))]
                names = targets[0][0]
            gifts = [{"uid": u, "gold": gold, "items": items, "pals": pals}
                     for _n, u in targets]
            desc = []
            if gold:
                desc.append(f"\U0001fa99 {gold:,}")
            if items:
                desc.append(", ".join(f"{item_disp(i)} \u00d7{c}"
                                      for i, c in items))
            if pals:
                desc.append(", ".join(f"{pal_disp(p['id'])} Lv{p['lv']}"
                                      for p in pals))
            if not messagebox.askyesno(
                    T("Give a gift"),
                    T("Gift for") + f" {names}:\n  \u2022  " +
                    "\n  \u2022  ".join(desc) + "\n\n" + T("Continue?"),
                    parent=win):
                return
            win.destroy()
            self._apply_gift(gifts, ", ".join(desc))

        ctk.CTkButton(pad, text="\U0001f381  " + T("Give now"),
                      height=44, corner_radius=12,
                      font=("Segoe UI", 13, "bold"),
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color="#ffffff", command=give).pack(fill="x",
                                                               pady=(6, 0))

        self._gw_render(pal_cat, item_cat, paldex)
        self._gw_search.bind("<KeyRelease>",
                             lambda e: self._gw_render(pal_cat, item_cat,
                                                       paldex))

        # fetch the remaining pal images in the background; the grid
        # refreshes in waves as they land
        def prefetch():
            fresh = 0
            for pid in pal_cat:
                if pal_icon2_path(pid):
                    continue  # already has art from the editor icon set
                try:
                    got = pal_image_for(pid, paldex)
                except Exception:
                    continue
                if got:
                    fresh += 1
                try:
                    alive = win.winfo_exists()
                except tk.TclError:
                    return
                if not alive:
                    return
                # fill art in place every few downloads — a full grid
                # re-render here froze the UI
                if fresh and fresh % 10 == 0:
                    self.after(0, self._gw_fill_images)
                time.sleep(0.05)
            try:
                if win.winfo_exists():
                    self.after(0, self._gw_fill_images)
            except tk.TclError:
                pass
        threading.Thread(target=prefetch, daemon=True).start()

    def _gw_mark(self, sid, on):
        btn = self._gw_buttons.get(sid)
        if btn is not None:
            try:
                btn.configure(fg_color=ACCENT_SOFT if on else SURFACE,
                              border_color=ACCENT if on else BORDER)
            except tk.TclError:
                pass

    def _gw_render(self, pal_cat, item_cat, paldex):
        """Rebuild the grid progressively in small chunks so the UI never
        freezes — creating 300 CTk tiles in one go blocks the mainloop for
        seconds."""
        grid = getattr(self, "_gw_grid_inner", None)
        if grid is None or not grid.winfo_exists():
            return
        self._gw_gen = getattr(self, "_gw_gen", 0) + 1
        gen = self._gw_gen
        self._gw_paldex = paldex
        self._gw_has_img = {}
        for w in list(grid.winfo_children()):
            try:
                w.destroy()
            except tk.TclError:
                pass
        self._gw_buttons = {}
        mode = "pals" if (not str(self._gw_tab.get()).startswith("\U0001f392")) \
            else "items"
        q = _norm_key(self._gw_search.get() if self._gw_search else "")
        entries = pal_cat if mode == "pals" else item_cat
        if q:
            meta = load_pal_meta() if mode == "pals" else load_item_meta()

            def hit(e):
                m = meta.get(e) or {}
                hay = _norm_key(e + " " + str(m.get("fr") or "") + " "
                                + str(m.get("en") or ""))
                return q in hay
            entries = [e for e in entries if hit(e)]
        if mode == "pals" and not load_pal_meta():
            entries = sorted(entries, key=lambda e: (e.startswith("BOSS_"), e))
        self._gw_entries = entries[:600]
        self._gw_mode = mode
        self._gw_chunk(0, gen)

    def _gw_chunk(self, start, gen):
        if gen != getattr(self, "_gw_gen", -1):
            return  # a newer render/search superseded this one
        grid = getattr(self, "_gw_grid_inner", None)
        if grid is None or not grid.winfo_exists():
            return
        mode = self._gw_mode
        entries = self._gw_entries
        cols = 5
        made = 0

        def toggle(sid, kind):
            if sid in self._gw_sel:
                self._gw_sel.pop(sid, None)
                self._gw_mark(sid, False)
            else:
                self._gw_sel[sid] = ({"kind": "pal", "lv": 30}
                                     if kind == "pals"
                                     else {"kind": "item", "qty": 10})
                self._gw_mark(sid, True)
            self._gw_refresh_basket()

        for i, sid in enumerate(entries[start:start + 12]):
            boss = sid.startswith("BOSS_")
            disp = pal_disp(sid) if mode == "pals" else item_disp(sid)
            # NB: tiles are CTkFrames, not buttons — packing children inside
            # a CTkButton is impossible (its canvas/text are grid-managed).
            tile = ctk.CTkFrame(
                grid, width=104, height=118, corner_radius=12,
                fg_color=ACCENT_SOFT if sid in self._gw_sel else SURFACE,
                border_width=2,
                border_color=ACCENT if sid in self._gw_sel else BORDER,
                cursor="hand2")
            tile.grid(row=(start + i) // cols, column=(start + i) % cols,
                      padx=4, pady=4)
            tile.grid_propagate(False)
            tile.pack_propagate(False)
            self._gw_buttons[sid] = tile
            if mode == "pals":
                img_path = (pal_icon2_path(sid)
                            or cached_pal_image(sid, self._gw_paldex))
            else:
                img_path = item_icon_path(sid)
            placed_img = False
            if img_path:
                ci = ctimg(img_path, (64, 64))
                if ci is not None:
                    ctk.CTkLabel(tile, text="", image=ci).pack(
                        pady=(8, 0), padx=8)
                    placed_img = True
            if not placed_img:
                ph = ctk.CTkLabel(tile,
                                  text=item_emoji(sid) if mode == "items"
                                  else "\U0001f43e",
                                  font=("Segoe UI Emoji", 26))
                ph.pack(pady=(10, 0))
                ph._gw_placeholder = True
            else:
                self._gw_has_img[sid] = True
            ctk.CTkLabel(tile, text=disp[:16], font=("Segoe UI", 9, "bold"),
                         text_color=ACCENT if sid in self._gw_sel else TEXT
                         ).pack(pady=(1, 2))
            for w in list(tile.winfo_children()) + [tile]:
                try:
                    w.bind("<Button-1>",
                           lambda e, s=sid, k=mode: toggle(s, k))
                except tk.TclError:
                    pass
            Tooltip(tile, disp + "\n" + sid)
            made += 1

        if start + made < len(entries):
            self.after(15, lambda: self._gw_chunk(start + made, gen))

    def _gw_fill_images(self):
        try:
            self._gw_fill_images_inner()
        except tk.TclError:
            pass  # wizard closed / widgets torn down mid-pass

    def _gw_fill_images_inner(self):
        """Swap \U0001f43e placeholders for downloaded art IN PLACE — never
        rebuild the grid (a full re-render per download batch froze the UI
        for tens of seconds)."""
        paldex = getattr(self, "_gw_paldex", None)
        if paldex is None:
            return
        grid = getattr(self, "_gw_grid_inner", None)
        if grid is None or not grid.winfo_exists():
            return
        for sid, tile in list(self._gw_buttons.items()):
            if self._gw_has_img.get(sid):
                continue
            path = (pal_icon2_path(sid) or cached_pal_image(sid, paldex)
                    if getattr(self, "_gw_mode", "pals") == "pals"
                    else item_icon_path(sid))
            if not path:
                continue
            ci = ctimg(path, (64, 64))
            if ci is None:
                continue
            for c in tile.winfo_children():
                if isinstance(c, ctk.CTkLabel) and \
                        getattr(c, "_gw_placeholder", False):
                    try:
                        c.configure(image=ci, text="")
                        c._gw_placeholder = False
                        self._gw_has_img[sid] = True
                    except tk.TclError:
                        pass
                    break

    def _apply_gift(self, gifts, note=""):
        """Stop → backup → gift.py → verify → start → announce. Threaded."""
        if not (os.path.isfile(TOOLS_PY312) and os.path.isfile(TOOLS_GIFT)):
            self._toast("Gift tools missing.", "⚠")
            return
        if self._busy:
            self._toast(T("Busy — try again in a moment."), "⏳")
            return
        world = world_dir()
        if not world:
            self._toast("World save not found.", "⚠")
            return

        def work():
            was_running = is_running()
            self.after(0, lambda: self._set_busy(T("Giving gifts…")))
            try:
                dst = backup_now()
                self._log_event("🗄 Safety backup before gift ("
                                + os.path.basename(dst) + ")")
                if was_running:
                    self._warn_and_wait()
                    stop_server()
                payload_path = os.path.join(_APPDATA, "gift_payload.json")
                with open(payload_path, "w", encoding="utf-8") as f:
                    json.dump({"gifts": gifts}, f)
                try:
                    r = subprocess.run(
                        [TOOLS_PY312, TOOLS_GIFT, world, payload_path],
                        capture_output=True, text=True, timeout=1800,
                        encoding="utf-8", errors="replace")
                    out = (r.stdout or "") + (r.stderr or "")
                except (OSError, subprocess.SubprocessError) as e:
                    out = str(e)
                ok = "GIFT_OK" in out
                if not ok:
                    # the tool saves Level.sav.giftbak right before writing
                    bak = os.path.join(world, "Level.sav.giftbak")
                    if os.path.exists(bak):
                        shutil.copy2(bak, os.path.join(world, "Level.sav"))
                    self._log_event("⚠ Gift failed — world restored from "
                                    "pre-gift copy. " + out.strip()[-160:])
                    self.after(0, lambda: self._toast(
                        T("Gift failed — world restored."), "⚠"))
                else:
                    self._log_event(f"🎁 Gift delivered: {note}")
                    self.after(0, lambda: self._toast(
                        T("Gift delivered!"), "🎁"))
                    self._discord(f"🎁 **Gift from the host**: {note}")
                if was_running:
                    start_server()
                    for attempt in range(30):
                        time.sleep(2)
                        if is_running():
                            break
                    try:
                        rcon_exec("Broadcast 🎁 " + (
                            note[:120] or "gift!"), timeout=6)
                    except (RconError, OSError, ValueError):
                        pass
                self._trophy_check()
            finally:
                self.after(0, lambda: self._flash(None))
        threading.Thread(target=work, daemon=True).start()

    def _chime(self, kind="ok"):
        if not winsound:
            return
        try:
            winsound.MessageBeep(
                winsound.MB_OK if kind == "ok" else winsound.MB_ICONEXCLAMATION)
        except RuntimeError:
            pass

    # ===== checklist =====
    def _toggle_router_done(self):
        self.cfg["router_done"] = not self.cfg.get("router_done", False)
        save_cfg(self.cfg)
        self.btn_router_done.configure(
            text=T("Undo") if self.cfg["router_done"] else T("Mark done"))
        self._update_checklist(self._last_stats_running)

    def _fw_ok(self):
        ts, ok = self._fw_cache
        if time.time() - ts > 300:
            ok = firewall_rule_present()
            self._fw_cache = (time.time(), ok)
        return ok

    def _checklist_states(self):
        return {
            "Server running": self._last_stats_running,
            "Firewall port open (UDP 8211)": self._fw_ok(),
            "Router port-forward done": self.cfg.get("router_done", False),
            "Public address known": bool(
                self._public_ip or (self.cfg.get("duck_domain")
                                    and self.cfg.get("duck_token"))),
            "Invite ready to send": bool(
                self._public_ip or (self.cfg.get("duck_domain")
                                    and self.cfg.get("duck_token"))),
        }

    def _update_checklist(self, running):
        states = self._checklist_states()
        for item, ok in states.items():
            if item not in self.chk_rows:
                continue
            g, l, _row = self.chk_rows[item]
            g.configure(text="✅" if ok else "⚠️",
                        text_color=ACCENT if ok else (("#b45309", "#f59e0b")))
            l.configure(text_color=TEXT if ok else TEXT_DIM)
        if all(states.values()):
            self.btn_finish_setup.pack_forget()
        else:
            self.btn_finish_setup.pack(anchor="w", pady=(8, 0),
                                       before=self.chips_frame)

    # ===== guild scan + map =====
    def _scan_world(self):
        self.btn_scan.configure(state="disabled")
        self.lbl_guild_scan.configure(text="⏳ scanning (about a minute)…")

        def work():
            data = run_world_scan()
            self.q.put(("guild", data))
        threading.Thread(target=work, daemon=True).start()

    def _startup_guild_cache(self):
        cache = load_guild_cache()
        if cache and time.time() - cache.get("ts", 0) < 6 * 3600:
            self.q.put(("guild", cache["data"], cache.get("ts", 0), True))
            return
        data = run_world_scan()
        if data:
            self.q.put(("guild", data, time.time(), False))

    def _render_guild(self, data, ts=None, cached=False):
        try:
            self._last_guild_data = data
            self.btn_scan.configure(state="normal")
            if cached and ts:
                mins = max(1, int((time.time() - ts) / 60))
                ago = (f"{mins // 60}h" if mins >= 60 else f"{mins}m")
                self.lbl_guild_scan.configure(text=f"✓ scanned {ago} ago")
            else:
                self.lbl_guild_scan.configure(text="✓")
                save_guild_cache(data)
            gt = (data or {}).get("game_time") or {}
            if gt:
                self.lbl_guild_scan.configure(
                    text=self.lbl_guild_scan.cget("text") +
                    f"   ·   📅 Day {gt.get('day', '?')} · {gt.get('clock', '')}")
            for w in self.guild_frame.winfo_children():
                w.destroy()
            if not data or not data.get("guilds"):
                ctk.CTkLabel(self.guild_frame, text="—",
                             font=F_SMALL, text_color=TEXT_DIM).pack(anchor="w")
                return
            for g in data["guilds"]:
                for p in g["players"]:
                    row = ctk.CTkFrame(self.guild_frame, fg_color=SURFACE_2,
                                       corner_radius=10)
                    row.pack(fill="x", pady=3)
                    av = self._avatar(row, p["name"], self._sid_for(p["name"]))
                    av.pack(side="left", padx=(8, 10), pady=6)
                    box = ctk.CTkFrame(row, fg_color="transparent")
                    box.pack(side="left", fill="x", expand=True, pady=5)
                    star = "⭐ " if p["admin"] else ""
                    ctk.CTkLabel(
                        box, anchor="w", font=F_BODY_B,
                        text_color=ACCENT if p["admin"] else TEXT,
                        text=(f"{star}{p['name']}    ·    Lv {p['level']}    ·    "
                              f"{p['pals']} Pals    ·    {p['last_seen']}")
                    ).pack(anchor="w")
                    if p.get("top_pals"):
                        dex = ", ".join(f"{n} ×{c}" for n, c in p["top_pals"][:4])
                        ctk.CTkLabel(box, anchor="w", font=F_SMALL,
                                     text_color=TEXT_DIM,
                                     text=f"{T('Top:')} {dex}").pack(anchor="w")
            self._render_map(data)
            self._render_inventory(data)
            self._trophy_check()
        except tk.TclError:
            pass

    def _render_map(self, data):
        c = self.canvas_map
        c.delete("all")
        self._map_cache = data
        self._map_points = []
        bases = (data or {}).get("bases") or []
        locs = (data or {}).get("player_locs") or []
        pts = [(b["x"], b["y"], f"🏠", f"Base ({b['x']}, {b['y']})")
               for b in bases]
        pts += [(p["x"], p["y"], "👤", f"{p['name']} (last known)")
                for p in locs]
        if not pts:
            self.lbl_map_info.configure(text="— scan the world to see bases —")
            return
        w = max(400, c.winfo_width() or 620)
        h = 220
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        minx, maxx = min(xs), max(xs)
        miny, maxy = min(ys), max(ys)
        spanx = max(1, maxx - minx)
        spany = max(1, maxy - miny)
        pad = 36
        # faint grid
        for i in range(1, 4):
            x = pad + (w - 2 * pad) * i / 4
            c.create_line(x, pad, x, h - pad, fill=self._hex(BORDER))
            y = pad + (h - 2 * pad) * i / 4
            c.create_line(pad, y, w - pad, y, fill=self._hex(BORDER))
        for idx, (x, y, glyph, label) in enumerate(pts):
            px = pad + (w - 2 * pad) * (x - minx) / spanx
            py = h - pad - (h - 2 * pad) * (y - miny) / spany
            tid = c.create_text(px, py, text=glyph, font=("Segoe UI", 15),
                                tags="pin")
            self._map_points.append((px, py, label, tid))
        self.lbl_map_info.configure(
            text=f"{len(bases)} base(s)" +
                 (f" · {len(locs)} player position(s)" if locs else "") +
                 " — hover a pin for details")

    def _map_hover(self, event):
        best = None
        for px, py, label, _tid in getattr(self, "_map_points", []):
            d = (px - event.x) ** 2 + (py - event.y) ** 2
            if d < 900 and (best is None or d < best[0]):
                best = (d, label)
        self.lbl_map_info.configure(
            text=best[1] if best else
            (f"{len(getattr(self, '_map_points', []))} pin(s) — hover for details"))

    # ===== avatars =====
    def _avatar(self, parent, name, sid=None):
        """Round avatar: the player's real Steam picture when cached on disk,
        coloured initials otherwise."""
        if sid:
            p = os.path.join(AVATAR_DIR, sid + ".jpg")
            if os.path.exists(p):
                try:
                    from PIL import Image, ImageDraw
                    im = Image.open(p).convert("RGB")
                    im = im.resize((30, 30), Image.LANCZOS)
                    mask = Image.new("L", (30, 30), 0)
                    ImageDraw.Draw(mask).ellipse([0, 0, 29, 29], fill=255)
                    im.putalpha(mask)
                    return ctk.CTkLabel(
                        parent, text="", width=30, height=30,
                        image=ctk.CTkImage(im, size=(30, 30)))
                except Exception:
                    pass
        ini = "".join(w[0] for w in name.split()[:2]).upper()[:2] or "?"
        color = AVATAR_COLORS[sum(name.encode()) % len(AVATAR_COLORS)]
        return ctk.CTkLabel(parent, text=ini, width=30, height=30,
                            corner_radius=15, fg_color=color,
                            text_color="#ffffff",
                            font=("Segoe UI", 11, "bold"))

    def _sid_for(self, name):
        return (self.cfg.get("player_ids") or {}).get(name)

    # ===== playtime =====
    def _parse_playtimes(self):
        sessions = {}
        pat = re.compile(r"\[(\d{2}/\d{2} \d{2}:\d{2})\]  👤 (.+?) (joined|left)")
        year = datetime.now().year
        for line in self._events:
            m = pat.match(line)
            if not m:
                continue
            try:
                dt = datetime.strptime(m.group(1) + f" {year}",
                                       "%d/%m %H:%M %Y")
            except ValueError:
                continue
            name, ev = m.group(2), m.group(3)
            if ev == "joined":
                sessions.setdefault(name, []).append([dt, None])
            else:
                for s in reversed(sessions.get(name, [])):
                    if s[1] is None:
                        s[1] = dt
                        break
        week_ago = datetime.now() - timedelta(days=7)
        totals = {}
        for name, ss in sessions.items():
            tot = 0.0
            for j, l in ss:
                end = l or datetime.now()
                if end >= week_ago:
                    tot += max(0.0, (end - max(j, week_ago)).total_seconds())
            if tot >= 60:
                totals[name] = tot
        return sorted(totals.items(), key=lambda kv: -kv[1])

    def _playtime_for(self, name):
        for n, secs in self._parse_playtimes():
            if n == name:
                h, m = int(secs // 3600), int(secs % 3600 // 60)
                return (f"{h}h {m:02d}m" if h else f"{m}m")
        return None

    def _render_playtimes(self):
        try:
            for w in self.pt_frame.winfo_children():
                w.destroy()
            totals = self._parse_playtimes()
            if not totals:
                ctk.CTkLabel(self.pt_frame, text="—", font=F_SMALL,
                             text_color=TEXT_DIM).pack(anchor="w")
                return
            for name, secs in totals[:6]:
                h, m = int(secs // 3600), int(secs % 3600 // 60)
                row = ctk.CTkFrame(self.pt_frame, fg_color="transparent")
                row.pack(fill="x", pady=3)
                av = self._avatar(row, name, self._sid_for(name))
                av.pack(side="left", padx=(0, 10))
                ctk.CTkLabel(row, text=name, font=F_BODY, anchor="w").pack(
                    side="left")
                ctk.CTkLabel(row, text=f"{h}h {m:02d}m" if h else f"{m}m",
                             font=("Segoe UI", 12, "bold"), text_color=ACCENT
                             ).pack(side="right")
        except tk.TclError:
            pass

    # ===== uptime graph =====
    def _draw_week(self):
        c = self.canvas_week
        c.delete("all")
        w = max(400, c.winfo_width() or 640)
        days = {}
        for ts, up in self._uptime:
            day = datetime.fromtimestamp(ts * 60).strftime("%d/%m")
            tot, ups = days.get(day, (0, 0))
            days[day] = (tot + 1, ups + int(up))
        last7 = sorted(days.items())[-7:]
        if not last7:
            self.lbl_weekpct.configure(text=T("Server up this week:") + " —")
            return
        total_up = sum(v[1] for _d, v in last7)
        total = sum(v[0] for _d, v in last7)
        pct = (100.0 * total_up / total) if total else 0.0
        self.lbl_weekpct.configure(
            text=f"{T('Server up this week:')} {pct:.1f}%")
        bw = (w - 40) / 7
        for i, (day, (tot, ups)) in enumerate(last7):
            x0 = 20 + i * bw + bw * 0.15
            x1 = 20 + (i + 1) * bw - bw * 0.15
            h = 70
            c.create_rectangle(x0, 15, x1, 15 + h, fill=self._hex(SURFACE_2),
                               outline="")
            frac = (ups / tot) if tot else 0
            c.create_rectangle(x0, 15 + h * (1 - frac), x1, 15 + h,
                               fill=self._hex(ACCENT), outline="")
            c.create_text((x0 + x1) / 2, 15 + h + 12, text=day,
                          fill=self._hex(TEXT_DIM), font=("Segoe UI", 9))

    @staticmethod
    def _hex(color_tuple):
        """Pick the right member of a (light, dark) pair for the canvas."""
        try:
            mode = ctk.get_appearance_mode().lower()
        except Exception:
            mode = "dark"
        return color_tuple[1] if mode == "dark" else color_tuple[0]

    def _draw_spark(self, canvas, hist):
        if canvas is None:
            return
        canvas.delete("all")
        pts = list(hist)
        if len(pts) < 2:
            return
        mx = max(pts) or 1.0
        w, h = 88, 18
        step = w / (len(pts) - 1)
        coords = []
        for i, v in enumerate(pts):
            coords += [2 + i * step, 2 + h - (min(v, mx) / mx) * (h - 4)]
        canvas.create_line(*coords, fill=self._hex(ACCENT), width=2, smooth=True)

    # ===== maintenance actions =====
    def _update(self):
        if self._busy:
            return
        win = ctk.CTkToplevel(self)
        win.title(T("Update server"))
        win.geometry("760x440")
        txt = ctk.CTkTextbox(win, wrap="word", font=F_MONO)
        txt.pack(fill="both", expand=True, padx=8, pady=8)
        win.grab_set()

        def line_cb(s):
            def _append():
                txt.insert("end", s + "\n")
                txt.see("end")
            self.after(0, _append)

        def work():
            self._busy = True
            try:
                steamcmd_update(line_cb)
                self._log_event("⬇ Server files updated via SteamCMD")
                self._update_pending = False
            finally:
                self._busy = False
        threading.Thread(target=work, daemon=True).start()

    def _check_update_now(self):
        self._toast("Checking for updates…", "🔍")

        def work():
            r = remote_buildid()
            l = local_buildid()
            self.q.put(("update", None if (r is None or l is None) else r != l))
        threading.Thread(target=work, daemon=True).start()

    def _backup(self):
        try:
            dst = backup_now()
            self._log_event("🗄 Backup created (" + os.path.basename(dst) + ")")
            self._render_backups_list()
            self._toast(f"Backup saved ({os.path.basename(dst)})", "🗄")
        except (OSError, subprocess.SubprocessError) as e:
            messagebox.showerror("Error", str(e))

    def _open_folders(self):
        os.startfile(SAVES_DIR)
        os.startfile(BACKUP_DIR)

    def _admin_fix(self):
        if not messagebox.askyesno(
            "Administrator",
            "Windows will ask for permission (UAC window).\nContinue?",
        ):
            return
        try:
            ok = run_admin_fix()
        except OSError as e:
            messagebox.showerror("Error", str(e))
            return
        if ok:
            self._log_event("🛡 Windows fixes applied (firewall / sleep / tasks)")
        self._refresh_tasks_label()
        messagebox.showinfo(
            "Done" if ok else "Maybe skipped",
            "Windows fixes applied." if ok
            else "The UAC prompt was closed or declined — nothing changed.",
        )

    def _refresh_tasks_label(self):
        tasks = old_tasks_present()
        self.lbl_tasks.configure(
            text=("⚠️  Old auto-start tasks still present: " + ", ".join(tasks)
                  + " — run the fix above to remove them.")
            if tasks
            else "✅  No old auto-start tasks — this app is fully in charge."
        )

    # ===== server actions =====
    def _do_start(self):
        if self._busy or is_running():
            return
        self._set_busy("Starting…")

        def work():
            ok = start_server()
            self._log_event("▶ Server started" if ok else "⚠ Server failed to start")
            self.after(0, lambda: self._flash(
                "Server is UP ✅" if ok else "Server failed to start ❌"))
        threading.Thread(target=work, daemon=True).start()

    def _do_stop(self):
        if self._busy or not is_running():
            return
        if not messagebox.askyesno("Stop", T("Stop the server? (World is saved first.)")):
            return
        self._set_busy("Stopping…")

        def work():
            stop_server()
            self._log_event("⏹ Server stopped")
            self.after(0, lambda: self._flash("Server stopped."))
        threading.Thread(target=work, daemon=True).start()

    def _do_restart(self):
        if self._busy:
            return
        self._set_busy("Restarting…")

        def work():
            if is_running():
                stop_server()
            ok = start_server()
            self._log_event("↻ Server restarted" if ok else "⚠ Restart failed")
            self.after(0, lambda: self._flash(
                "Server is UP ✅" if ok else "Server failed to start ❌"))
        threading.Thread(target=work, daemon=True).start()

    def _save_world(self):
        def work():
            try:
                rcon_exec("Save", timeout=8)
                self.after(0, lambda: self._toast("World saved.", "💾"))
            except (RconError, OSError, ValueError) as e:
                self.after(0, lambda e=e: self._toast(f"Save failed: {e}", "⚠"))
        threading.Thread(target=work, daemon=True).start()

    def _broadcast(self):
        msg = self.ent_msg.get().strip()
        if not msg:
            return

        def work():
            try:
                rcon_exec("Broadcast " + msg, timeout=5)
                self.after(0, lambda: self._toast("Message sent.", "📣"))
            except (RconError, OSError, ValueError) as e:
                self.after(0, lambda e=e: self._toast(f"Broadcast failed: {e}", "⚠"))
        threading.Thread(target=work, daemon=True).start()

    def _pick_player(self, p):
        self._sel_player = None if self._sel_player == p else p
        self._render_players(self._players)

    def _selected_player(self):
        if not self._sel_player:
            messagebox.showinfo(T("Players online"), "Click a player in the list first.")
            return None
        return self._sel_player

    def _kick(self):
        p = self._selected_player()
        if not p:
            return
        if messagebox.askyesno(T("Kick"), f"Kick {p[0]}?"):
            try:
                rcon_exec("KickPlayer " + p[2])
                self._toast(f"Kicked {p[0]}.", "👢")
            except (RconError, OSError, ValueError) as e:
                self._toast(f"Kick failed: {e}", "⚠")

    def _ban(self):
        p = self._selected_player()
        if not p:
            return
        if messagebox.askyesno(T("Ban"), f"BAN {p[0]}?\n(They cannot come back.)"):
            try:
                rcon_exec("BanPlayer " + p[2])
                self._toast(f"Banned {p[0]}.", "🚫")
            except (RconError, OSError, ValueError) as e:
                self._toast(f"Ban failed: {e}", "⚠")

    # ===== scheduled settings profiles (e.g. 2× EXP weekends) =====
    def _profile_tick(self, now):
        active = None
        for prof in self.cfg.get("profiles") or []:
            if profile_active(prof, now):
                active = prof
                break
        state = self.cfg.get("profile_state") or {}
        applied = state.get("name")
        if active and active.get("name") != applied:
            try:
                s = load_server_settings()
                backup = {"ExpRate": s.get("ExpRate", "1.0"),
                          "PalCaptureRate": s.get("PalCaptureRate", "1.0")}
                apply_ini_updates({
                    "ExpRate": str(float(active.get("exp", "2"))),
                    "PalCaptureRate": str(float(active.get("cap", "2")))})
                self.cfg["profile_state"] = {"name": active["name"],
                                             "backup": backup}
                save_cfg(self.cfg)
            except (OSError, ValueError, TypeError):
                return
            self._log_event(f"🚀 Profile “{active['name']}” ON — "
                            f"EXP ×{active.get('exp')} · capture ×{active.get('cap')}")
            try:
                rcon_exec(f"Broadcast 🚀 {active['name']} starts now — "
                          f"EXP ×{active.get('exp')}! Restarting in 2 min.",
                          timeout=5)
            except (RconError, OSError, ValueError):
                pass
            time.sleep(120)
            if is_running():
                stop_server()
            start_server()
        elif not active and applied:
            try:
                backup = state.get("backup") or {}
                if backup:
                    apply_ini_updates(backup)
                self.cfg["profile_state"] = {}
                save_cfg(self.cfg)
            except (OSError, ValueError):
                return
            self._log_event(f"🔚 Profile “{applied}” over — normal rates restored")
            try:
                rcon_exec(f"Broadcast 🔚 {applied} is over — back to normal "
                          f"rates! Restarting in 2 min.", timeout=5)
            except (RconError, OSError, ValueError):
                pass
            time.sleep(120)
            if is_running():
                stop_server()
            start_server()

    # ===== Pal box browser =====
    # ----- guild card export -----
    def _export_guild_card(self):
        """Render a shareable guild-summary PNG using the app artwork."""
        data = self._last_guild_data or (load_guild_cache() or {}).get("data") or {}
        members = []
        for g in data.get("guilds") or []:
            for p in g.get("players") or []:
                members.append(p)
        if not members:
            self._toast("Scan the world first (members list needed).", "🃏")
            return
        try:
            from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
        except ImportError:
            self._toast("PIL missing — cannot render the card.", "⚠")
            return

        def font(paths, size):
            for p in paths:
                try:
                    return ImageFont.truetype(p, size)
                except OSError:
                    continue
            return ImageFont.load_default()

        W, H = 920, 200 + 66 * len(members) + 130
        card = Image.new("RGB", (W, H), (11, 18, 32))
        # artwork backdrop, heavily dimmed
        bg_path = os.path.join(BASE, "app", "bg.png")
        if os.path.exists(bg_path):
            try:
                art = Image.open(bg_path).convert("RGB")
                art = art.resize((W, W * art.size[1] // art.size[0]), Image.LANCZOS)
                art = art.crop((0, 0, W, H))
                art = art.filter(ImageFilter.GaussianBlur(9))
                art = ImageEnhance.Brightness(art).enhance(0.30)
                card = ImageEnhance.Color(art).enhance(0.9)
            except Exception:
                pass
        d = ImageDraw.Draw(card)
        # header scrim
        d.rectangle([0, 0, W, 150], fill=(8, 12, 22))
        f_title = font([r"C:\Windows\Fonts\seguisb.ttf"], 40)
        f_sub = font([r"C:\Windows\Fonts\segoeui.ttf"], 17)
        f_name = font([r"C:\Windows\Fonts\seguisb.ttf"], 22)
        f_stat = font([r"C:\Windows\Fonts\segoeui.ttf"], 16)

        d.text((40, 38), "MY PALWORLD SERVER", font=f_title, fill=(255, 255, 255))
        facts = data.get("facts") or {}
        gt = data.get("game_time") or {}
        sub = (f"Guild card · {len(members)} members · "
               f"{facts.get('pals_total', '—')} Pals · "
               f"{facts.get('bases', '—')} bases"
               + (f" · Day {gt.get('day', '?')}" if gt else ""))
        d.text((42, 96), sub, font=f_sub, fill=(150, 190, 230))

        ids = self.cfg.get("player_ids") or {}
        y = 170
        for p in members:
            # avatar (real Steam pic when cached) + row card
            d.rounded_rectangle([30, y, W - 30, y + 54], radius=14,
                                fill=(16, 26, 44))
            av_path = os.path.join(AVATAR_DIR,
                                   (ids.get(p["name"]) or "") + ".jpg")
            drew_av = False
            if ids.get(p["name"]) and os.path.exists(av_path):
                try:
                    av = Image.open(av_path).convert("RGB").resize((40, 40))
                    mask = Image.new("L", (40, 40), 0)
                    ImageDraw.Draw(mask).ellipse([0, 0, 39, 39], fill=255)
                    card.paste(av, (44, y + 7), mask)
                    drew_av = True
                except Exception:
                    pass
            if not drew_av:
                d.ellipse([44, y + 7, 84, y + 47], fill=(56, 182, 240))
                ini = "".join(w[0] for w in p["name"].split()[:2]).upper()[:2]
                d.text((52, y + 16), ini or "?", font=f_name, fill=(13, 24, 38))
            star = "⭐ " if p.get("admin") else ""
            try:
                d.text((100, y + 8), f"{star}{p['name']}",
                       font=f_name, fill=(255, 255, 255))
            except Exception:
                d.text((100, y + 8), p["name"], font=f_name, fill=(255, 255, 255))
            d.text((100, y + 33),
                   f"Lv {p['level']}   ·   {p['pals']} Pals   ·   "
                   f"{p.get('last_seen', '')}", font=f_stat, fill=(141, 161, 189))
            y += 66

        d.rectangle([0, H - 78, W, H], fill=(8, 12, 22))
        week = datetime.now().strftime("%d/%m/%Y")
        d.text((40, H - 56), f"Generated {week} · Palworld Server Manager",
               font=f_sub, fill=(120, 140, 170))
        out = os.path.join(BASE, "guild_card.png")
        try:
            card.save(out)
        except OSError as e:
            self._toast(f"Could not save: {e}", "⚠")
            return
        try:
            os.startfile(out)
        except OSError:
            pass
        self._toast(T("Guild card saved") + f" → {out}", "🃏")
        self._log_event("🃏 Guild card exported")

    # ----- steam news -----
    def _news_fetch(self):
        def work():
            items = fetch_steam_news(5)
            self.q.put(("news", items))
        threading.Thread(target=work, daemon=True).start()

    def _render_news(self, items):
        for w in self.news_frame.winfo_children():
            w.destroy()
        if not items:
            ctk.CTkLabel(self.news_frame,
                         text=T("Could not load the news — check the "
                                "connection, or retry."),
                         font=F_SMALL, text_color=TEXT_DIM, anchor="w"
                         ).pack(anchor="w", pady=4)
            return
        for n in items:
            when = datetime.fromtimestamp(n["date"]).strftime("%d/%m")
            row = ctk.CTkFrame(self.news_frame, fg_color="transparent")
            row.pack(fill="x", pady=(6, 0))
            head = ctk.CTkLabel(
                row, text=f"📰 {n['title']}   ·   {when}",
                font=F_BODY_B, text_color=ACCENT, anchor="w", cursor="hand2",
                justify="left", wraplength=640)
            head.pack(anchor="w")
            if n.get("url"):
                head.bind("<Button-1>", lambda e, u=n["url"]: webbrowser.open(u))
                Tooltip(head, u"" + n["url"])
            ctk.CTkLabel(row, text=n.get("text", ""), font=F_SMALL,
                         text_color=TEXT_DIM, anchor="w", justify="left",
                         wraplength=660).pack(anchor="w", pady=(1, 0))

    def _open_palbox(self):
        data = self._last_guild_data or {}
        members = []
        for g in data.get("guilds") or []:
            for p in g.get("players") or []:
                members.append((p["name"], p["uid"], p["pals"], p["level"]))
        if not members:
            self._toast("Scan the world first (members list needed).", "🐾")
            return
        win = ctk.CTkToplevel(self)
        win.title(T("Pal boxes"))
        win.geometry("640x520")
        win.grab_set()
        body = ctk.CTkFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=14, pady=12)
        top = ctk.CTkFrame(body, fg_color="transparent")
        top.pack(fill="x", pady=(0, 8))
        self._pb_member = ctk.CTkOptionMenu(
            top, width=260, fg_color=SURFACE_2, button_color=BORDER,
            values=[f"{n}  ·  Lv{l}  ·  {p} Pals" for n, _u, p, l in members])
        self._pb_member.set(f"{members[0][0]}  ·  Lv{members[0][3]}  ·  "
                            f"{members[0][2]} Pals")
        self._pb_member.pack(side="left")
        self._pb_members = members
        self._pb_search = ctk.CTkEntry(top, width=170, placeholder_text="🔍 filter…",
                                       fg_color=SURFACE_2, border_width=0)
        self._pb_search.pack(side="right")
        self._pb_search.bind("<KeyRelease>", lambda e: self._pb_filter())
        self._pb_status = ctk.CTkLabel(body, text="", font=F_SMALL,
                                       text_color=TEXT_DIM, anchor="w")
        self._pb_status.pack(anchor="w")
        self._pb_list = ctk.CTkScrollableFrame(body, fg_color="transparent")
        self._pb_list.pack(fill="both", expand=True)
        ctk.CTkButton(top, text="🔍", width=40, corner_radius=8,
                      fg_color=BLUE, hover_color=BLUE_HOVER,
                      text_color="#ffffff",
                      command=self._pb_fetch).pack(side="left", padx=(8, 0))

    def _pb_fetch(self):
        idx = self._pb_member.get()
        try:
            i = [f"{n}  ·  Lv{l}  ·  {p} Pals"
                 for n, _u, p, l in self._pb_members].index(idx)
            uid = self._pb_members[i][1]
        except (ValueError, IndexError):
            return
        self._pb_status.configure(text="⏳ reading the Pal box (about a minute)…")

        def work():
            data = run_pal_box(uid)
            pals = (data or {}).get("pals") or []
            self.after(0, lambda: self._pb_render(pals))
        threading.Thread(target=work, daemon=True).start()

    def _pb_render(self, pals):
        try:
            self._pb_status.configure(text=f"{len(pals)} Pals (top 600 shown)")
            self._pb_data = pals
            self._pb_filter()
        except tk.TclError:
            pass

    def _pb_filter(self):
        q = self._pb_search.get().strip().lower()
        for w in self._pb_list.winfo_children():
            w.destroy()
        for p in getattr(self, "_pb_data", []):
            text = f"{'★' if p['boss'] else '👤'}  {p['sp']}"
            if q and q not in text.lower() and q not in " ".join(p["p"]).lower():
                continue
            row = ctk.CTkFrame(self._pb_list, fg_color=SURFACE_2, corner_radius=8)
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(row, text=text, font=F_BODY_B, anchor="w",
                         text_color=ACCENT if p["boss"] else TEXT).pack(
                side="left", padx=(10, 8), pady=4)
            ctk.CTkLabel(row, text=f"Lv {p['lv']}", font=F_BODY,
                         text_color=TEXT).pack(side="left", padx=6)
            if p["p"]:
                ctk.CTkLabel(row, text=" · ".join(p["p"]), font=("Segoe UI", 10),
                             text_color=TEXT_DIM, anchor="e", wraplength=240
                             ).pack(side="right", padx=10)

    # ===== Ctrl+K palette =====
    def _open_palette(self):
        win = ctk.CTkToplevel(self)
        win.title("⚡ " + T("Quick actions"))
        win.geometry("580x430")
        win.grab_set()
        ent = ctk.CTkEntry(win, height=42,
                           placeholder_text="Type to search actions and settings… "
                                            "(Enter = first, Esc = close)")
        ent.pack(fill="x", padx=14, pady=(14, 8))
        ent.focus()
        frame = ctk.CTkScrollableFrame(win, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        items = [(f"{icon}  " + T("Go to") + " " + T(label),
                  lambda p=pid: self._show_page(p))
                 for pid, icon, label, _sub in self.PAGES]
        items += [
            ("▶  " + T("Start"), self._do_start),
            ("⏹  " + T("Stop"), self._do_stop),
            ("↻  " + T("Restart"), self._do_restart),
            ("💾  " + T("Save world now"), self._save_world),
            ("📋  " + T("Copy invite message"), self._copy_invite),
            ("🗄  " + T("Backup now"), self._backup),
            ("🔍  " + T("Check for Palworld update now"), self._check_update_now),
            ("🔍  " + T("Scan world"), self._scan_world),
            ("🐾  " + T("Pal boxes"), self._open_palbox),
        ]

        def jump_setting(label):
            def go():
                self._show_page("settings")
                self._settings_search.delete(0, "end")
                self._settings_search.insert(0, label)
                self._filter_settings(label)
                self._settings_search.focus()
            return go
        for f in PLAYFIELDS:
            lbl, _h = tr_setting(f[1], f[2], f[3])
            items.append((f"⚙  {lbl}", jump_setting(lbl)))

        def build(q=""):
            for w in frame.winfo_children():
                w.destroy()
            ql = q.lower()
            shown = 0
            for label, fn in items:
                if ql and ql not in label.lower():
                    continue
                b = ctk.CTkButton(frame, text=label, anchor="w", height=34,
                                  corner_radius=8, fg_color=SURFACE_2,
                                  hover_color=BORDER,
                                  command=lambda f=fn, w=win: (w.destroy(), f()))
                b.pack(fill="x", pady=2)
                shown += 1
                if shown >= 16:
                    break
        build()

        def on_key(e):
            if e.keysym == "Return":
                for w in frame.winfo_children():
                    w.invoke()
                    break
                win.destroy()
            elif e.keysym == "Escape":
                win.destroy()
            else:
                build(ent.get())
        ent.bind("<KeyRelease>", on_key)

    # ===== world switcher =====
    def _worlds_refresh(self):
        worlds = self.cfg.get("worlds") or {}
        cur = world_dir()
        cur_guid = os.path.basename(cur) if cur else "—"
        active = self.cfg.get("active_label", "main")
        lines = [f"★ active ({active}):  {cur_guid[:20]}"]
        for label in sorted(set(list(worlds.keys()) +
                                [d.split("__")[0] for d in stored_worlds()])):
            if label == active and cur:
                continue
            guid = worlds.get(label)
            if guid:
                lines.append(f"   {label}:  {guid[:20]}")
        try:
            self.lbl_worlds.configure(text="\n".join(lines))
        except tk.TclError:
            pass

    def _create_test_world(self):
        if not messagebox.askyesno(
            T("Create test world"),
            "This creates a brand-new EMPTY world to experiment on "
            "(updates, settings, mods).\n\nYour current world is preserved and "
            "put back automatically. Takes a few minutes. Continue?",
        ):
            return

        def work():
            self._busy = True
            try:
                self._log_event("🌍 Creating test world…")
                cur = world_dir()
                if not cur:
                    return
                root0 = os.path.dirname(cur)
                guid = os.path.basename(cur)
                stop_server()
                os.makedirs(WORLDS_STORE, exist_ok=True)
                shutil.move(cur, os.path.join(WORLDS_STORE, f"main__{guid}"))
                self.cfg.setdefault("worlds", {})["main"] = guid
                self.cfg["active_label"] = "main"
                save_cfg(self.cfg)
                start_server()  # boots with an empty folder -> fresh world
                new = None
                deadline = time.time() + 200
                while time.time() < deadline:
                    time.sleep(5)
                    d = world_dir()
                    if d and os.path.basename(d) != guid:
                        new = d
                        break
                stop_server()
                if new:
                    nguid = os.path.basename(new)
                    shutil.move(new, os.path.join(WORLDS_STORE, f"test__{nguid}"))
                    self.cfg["worlds"]["test"] = nguid
                    save_cfg(self.cfg)
                shutil.move(os.path.join(WORLDS_STORE, f"main__{guid}"),
                            os.path.join(root0, guid))
                start_server()
                self._log_event("🌍 Test world created and stored — main world "
                                "is active again")
                self.after(0, lambda: self._toast("Test world ready 🌍", "✅"))
                self.after(0, self._worlds_refresh)
            finally:
                self._busy = False
        threading.Thread(target=work, daemon=True).start()

    def _switch_world(self, label):
        worlds = self.cfg.get("worlds") or {}
        if label not in worlds:
            self._toast(f"No stored “{label}” world — create it first.", "⚠")
            return
        if not messagebox.askyesno(
            "Switch world",
            f"Switch to the “{label}” world?\n\nThe server will stop and restart "
            "with that world.",
        ):
            return

        def work():
            self._busy = True
            try:
                cur = world_dir()
                cur_label = self.cfg.get("active_label", "main")
                stop_server()
                if cur and cur_label in worlds:
                    shutil.move(cur, os.path.join(
                        WORLDS_STORE,
                        f"{cur_label}__{worlds[cur_label]}"))
                src = os.path.join(WORLDS_STORE, f"{label}__{worlds[label]}")
                shutil.move(src, os.path.join(SAVES_DIR, "0", worlds[label]))
                self.cfg["active_label"] = label
                save_cfg(self.cfg)
                start_server()
                self._log_event(f"🌍 Switched to the “{label}” world")
                self.after(0, lambda: self._toast(f"Now on the “{label}” world",
                                                  "🌍"))
                self.after(0, self._worlds_refresh)
            finally:
                self._busy = False
        threading.Thread(target=work, daemon=True).start()

    def _delete_test_world(self):
        worlds = self.cfg.get("worlds") or {}
        if self.cfg.get("active_label") == "test" or "test" not in worlds:
            self._toast("No stored test world (or it is active).", "⚠")
            return
        if not messagebox.askyesno(T("Delete test world"),
                                   "Delete the stored test world forever?"):
            return
        shutil.rmtree(os.path.join(WORLDS_STORE,
                                   f"test__{worlds['test']}"),
                      ignore_errors=True)
        worlds.pop("test", None)
        self.cfg["worlds"] = worlds
        save_cfg(self.cfg)
        self._log_event("🗑 Test world deleted")
        self._worlds_refresh()

    # ===== players chart + reliability =====
    def _draw_players(self):
        c = self.canvas_players
        c.delete("all")
        w = max(400, c.winfo_width() or 640)
        days = {}
        for ts, n in self._players_hist:
            day = datetime.fromtimestamp(ts * 60).strftime("%d/%m")
            days[day] = max(days.get(day, 0), int(n))
        last7 = sorted(days.items())[-7:]
        if not last7:
            return
        mx = max([v for _d, v in last7] or [1]) or 1
        bw = (w - 40) / 7
        for i, (day, v) in enumerate(last7):
            x0 = 20 + i * bw + bw * 0.15
            x1 = 20 + (i + 1) * bw - bw * 0.15
            h = 42
            c.create_rectangle(x0, 8, x1, 8 + h, fill=self._hex(SURFACE_2),
                               outline="")
            c.create_rectangle(x0, 8 + h * (1 - v / mx), x1, 8 + h,
                               fill=self._hex(BLUE), outline="")
            c.create_text((x0 + x1) / 2, 8 + h + 8, text=str(v),
                          fill=self._hex(TEXT_DIM), font=("Segoe UI", 9))

    def _reliability_text(self):
        crashes = sum(1 for l in self._events if "💥" in l)
        watchdog = sum(1 for l in self._events if "🔧 Watchdog" in l)
        return f"reliability — crashes: {crashes} · watchdog restarts: {watchdog}"

    # ===== tray =====
    def _setup_tray(self):
        try:
            import pystray
            from PIL import Image
        except ImportError:
            self._tray = None
            return
        icon_path = os.path.join(BASE, "app.ico")
        try:
            image = Image.open(icon_path) if os.path.exists(icon_path) \
                else Image.new("RGBA", (64, 64), ACCENT[1])
            image = image.convert("RGBA")
            image.thumbnail((64, 64), Image.LANCZOS)  # crisp at tray size
        except OSError:
            image = Image.new("RGBA", (64, 64), ACCENT[1])
        menu = pystray.Menu(
            pystray.MenuItem(T("Open"), self._tray_cmd("open"), default=True),
            pystray.MenuItem(T("Start"), self._tray_cmd("start")),
            pystray.MenuItem(T("Stop"), self._tray_cmd("stop")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(T("Quit"), self._tray_cmd("quit")),
        )
        try:
            self._tray = pystray.Icon(APP_NAME, image, APP_TITLE, menu)
            self._tray.run_detached()
        except Exception:
            self._tray = None

    def _tray_cmd(self, action):
        def cb(*_a):
            self.q.put(("tray", action))
        return cb

    def _on_close(self):
        self.withdraw()
        self._notify(T("Still running in the tray"),
                     T("The window is closed but the app keeps managing the server. "
                       "Double-click the sheep icon near the clock to reopen."))

    def _confirm_quit_app(self):
        if messagebox.askyesno(
                T("Turn off the app"),
                T("Turn the app off completely?\n"
                  "It will stop watching the server — the server itself "
                  "keeps running.") + "\n\n" + T(
                      "Tip: closing the window with ✕ only hides it to the "
                      "tray."),
                parent=self):
            self._quit_app()

    def _quit_app(self):
        self._save_geometry()
        try:
            if self._tray:
                self._tray.stop()
        except Exception:
            pass
        self.destroy()

    def _resume_watchdog(self):
        self._crash_guard = False
        self._crash_times = []
        self._crash_banner.pack_forget()
        self._log_event("▶ Crash protection lifted — watchdog resumed")

    # ===== plumbing =====
    def _set_busy(self, txt):
        self._busy = True
        # the hero banner stays dark in both appearances — always use the
        # bright amber there so the text stays readable on the artwork
        self.lbl_status.configure(
            text=("⏳  " + txt) if txt else txt,
            text_color="#f59e0b" if getattr(self, "_art_hero", None)
            else ("#b45309", "#f59e0b"))
        self.pill.configure(text="  ● busy…  ", fg_color=("#b45309", "#92400e"))
        self.side_status.configure(text="● " + txt.lower() + "…",
                                   text_color=("#b45309", "#f59e0b"))
        for b in (self.btn_start, self.btn_stop, self.btn_restart):
            b.configure(state="disabled")

    def _flash(self, txt):
        self._busy = False
        for b in (self.btn_start, self.btn_stop, self.btn_restart):
            b.configure(state="normal")

    def _pulse_tick(self):
        if self._last_stats_running and not self._busy:
            self._pulse_hi = not self._pulse_hi
            if getattr(self, "_art_hero", None):
                col = "#ffffff" if self._pulse_hi else "#c9d4e0"
            else:
                col = ACCENT if self._pulse_hi else ACCENT_HOVER
            try:
                if getattr(self, "_art_hero", None):
                    light = ctk.get_appearance_mode().lower() != "dark"
                    self.pill.configure(
                        fg_color=("#15803d" if light else "#22c55e")
                        if self._pulse_hi
                        else ("#166534" if light else "#16a34a"))
                else:
                    self.pill.configure(
                        fg_color=ACCENT if self._pulse_hi else ACCENT_HOVER)
                self.lbl_status.configure(text_color=col)
            except tk.TclError:
                pass
        self.after(1300, self._pulse_tick)

    def _warn_and_wait(self):
        """In-game warning before an automatic stop/restart."""
        try:
            rcon_exec("Broadcast ⚠ Restart in 2 min — save your progress! "
                      "/ Redémarrage dans 2 min — sauvegardez !", timeout=5)
        except (RconError, OSError, ValueError):
            pass
        time.sleep(120)

    def _on_player_join(self, name, sid):
        disp = self._disp_name(name, sid)
        self._log_event(f"👤 {name} joined")
        self._notify("🎮 " + disp, "joined the server")
        self._discord(f"🎮 **{disp}** joined the server")
        if sid:  # remember name -> steam id (avatars, guild card)
            ids = self.cfg.get("player_ids") or {}
            if ids.get(name) != sid:
                ids[name] = sid
                self.cfg["player_ids"] = ids
                save_cfg(self.cfg)
            if self.cfg.get("steam_api_key"):
                def _av(s=sid):
                    if fetch_steam_avatars(self.cfg.get("steam_api_key"), [s]):
                        self.q.put(("avatars", s))
                threading.Thread(target=_av, daemon=True).start()
        if self.cfg.get("join_sound", True):
            self._chime("ok")
        # bouncer: kick anyone not approved
        if self.cfg.get("bouncer_enabled"):
            approved = {a.lower() for a in self.cfg.get("bouncer_approved") or []}
            if sid and sid.lower() not in approved:
                try:
                    rcon_exec("KickPlayer " + sid, timeout=5)
                    self._log_event(f"🚫 Bouncer: kicked {name} ({sid})")
                    self._notify("🚫 " + T("Friends-only lock"),
                                 f"{name} was kicked — not on the approved list.")
                except (RconError, OSError, ValueError):
                    pass
                return
        # welcome message, personalised with weekly playtime
        if self.cfg.get("motd_enabled") and self.cfg.get("motd"):
            pt = self._playtime_for(name)
            greet = (f"👋 {name} — {pt} this week! {self.cfg['motd']}"
                     if pt else f"👋 {name} — {self.cfg['motd']}")
            try:
                rcon_exec("Broadcast " + greet, timeout=5)
            except (RconError, OSError, ValueError):
                pass

    def _monitor(self):
        """Background loop: stats, players, watchdog, schedule. UI via queue."""
        while True:
            try:
                stats = server_stats()
                players = list_players() if stats["running"] else []
                now = datetime.now()

                # crash detection + crash-loop guard
                if self._was_running and not stats["running"] \
                        and not _stopping and not self._busy:
                    self._crash_times.append(time.time())
                    self._crash_times = [t for t in self._crash_times
                                         if time.time() - t < 600]
                    diag = diagnose_crash()
                    cause_en, cause_fr = CRASH_CAUSES[diag]
                    cause = cause_fr if LANG == "fr" else cause_en
                    self._log_event(f"💥 Server crashed — probable cause: {cause}")
                    self._notify(APP_TITLE, f"Server crashed — {cause}")
                    self._discord(f"💥 Server crashed — probable cause: "
                                  f"**{cause}**. Restarting it.")
                    self._chime("warn")
                    if len(self._crash_times) >= 5 and not self._crash_guard:
                        self._crash_guard = True
                        self._log_event("🛑 Crash protection: 5 crashes in 10 min "
                                        "— auto-restart paused")
                        self._notify("⚠ " + T("Crash protection active"),
                                     T("The server kept crashing — auto-restart paused."))
                self._was_running = stats["running"]

                # uptime + players sampling (once per minute)
                minute = int(time.time() // 60)
                if minute != self._up_last_min:
                    self._up_last_min = minute
                    self._uptime.append([minute, 1 if stats["running"] else 0])
                    self._uptime = self._uptime[-10080:]
                    save_uptime(self._uptime)
                    self._players_hist.append([minute, len(players)])
                    self._players_hist = self._players_hist[-10080:]
                    save_players_hist(self._players_hist)
                    self._profile_tick(now)

                # zombie probe: process alive but RCON unresponsive
                if stats["running"] and self.cfg.get("zombie_check", True) \
                        and not _stopping and not self._busy:
                    try:
                        rcon_exec("Info", timeout=4)
                        self._rcon_fails = 0
                    except (RconError, OSError, ValueError):
                        self._rcon_fails += 1
                        if self._rcon_fails >= 3 \
                                and time.time() - self._zombie_cd > 1800:
                            self._zombie_cd = time.time()
                            self._rcon_fails = 0
                            self._log_event("🧟 Server unresponsive — "
                                            "smart restart")
                            self._notify("🧟 " + T("Server unresponsive"),
                                         T("Restarting it automatically"))
                            self._discord("🧟 Server froze (no RCON answer) — "
                                          "smart restart")
                            self._warn_and_wait()
                            stop_server()
                            start_server()
                else:
                    self._rcon_fails = 0

                # weekly password rotation
                if rotation_due(self.cfg, now):
                    self.cfg["rotate_fired"] = "rot" + now.strftime("%Y-%m-%d")
                    save_cfg(self.cfg)
                    self._rotate_password()

                desired = desired_on(
                    now.time(), self.cfg["mode"],
                    _parse_hm(self.cfg["on_time"]), _parse_hm(self.cfg["off_time"]),
                )
                if desired and not stats["running"] and self.cfg["watchdog"] \
                        and not self._crash_guard and not _stopping \
                        and not self._busy \
                        and self._last_desired is not None:
                    self._log_event("🔧 Watchdog: starting the server")
                    start_server()
                if not desired and stats["running"] and not _stopping:
                    self._log_event("⏰ Schedule: stopping the server")
                    self._warn_and_wait()
                    stop_server()
                dr = self.cfg.get("daily_restart") or ""
                if dr and stats["running"]:
                    key = now.strftime("%Y-%m-%d")
                    if self.cfg.get("daily_fired_date") != key:
                        start_t = datetime.combine(now.date(), _parse_hm(dr))
                        end_t = start_t + timedelta(minutes=11)
                        if start_t <= now <= end_t:
                            self.cfg["daily_fired_date"] = key
                            save_cfg(self.cfg)
                            self._log_event("🔁 Daily restart")
                            self._warn_and_wait()
                            stop_server()
                            start_server()

                # scheduled announcements
                fired = self.cfg.get("ann_fired") or {}
                for i, ann in enumerate(self.cfg.get("announcements") or []):
                    if not ann.get("enabled", True) or not ann.get("text"):
                        continue
                    if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d",
                                        ann.get("time", "")):
                        continue
                    key = f"{i}|{now.strftime('%Y-%m-%d')}"
                    if fired.get(key):
                        continue
                    st = datetime.combine(now.date(), _parse_hm(ann["time"]))
                    if st <= now <= st + timedelta(minutes=11):
                        fired[key] = True
                        self.cfg["ann_fired"] = fired
                        save_cfg(self.cfg)
                        try:
                            rcon_exec("Broadcast 📣 " + ann["text"], timeout=5)
                            self._log_event(f"📣 Announcement: {ann['text']}")
                        except (RconError, OSError, ValueError):
                            pass

                # scheduled gift events (gold/items/Pal for the whole guild)
                gfired = self.cfg.get("gift_fired") or {}
                for i, evd in enumerate(self.cfg.get("gift_events") or []):
                    if not evd.get("enabled", True):
                        continue
                    t = evd.get("time", "")
                    if not re.fullmatch(r"([01]?\d|2[0-3]):[0-5]\d", t):
                        continue
                    key = f"{i}|{now.strftime('%Y-%m-%d')}"
                    if gfired.get(key):
                        continue
                    st = datetime.combine(now.date(), _parse_hm(t))
                    if st <= now <= st + timedelta(minutes=11):
                        gfired[key] = True
                        self.cfg["gift_fired"] = gfired
                        save_cfg(self.cfg)
                        gold = int(evd.get("gold") or 0)
                        items = self._parse_items_text(evd.get("items", ""))
                        pal = evd.get("pal", "").strip()
                        pal_lv = int(evd.get("pal_lv") or 30) \
                            if str(evd.get("pal_lv") or "").isdigit() else 30
                        if not gold and not items and not pal:
                            continue
                        gifts = [{"uid": u, "gold": gold, "items": items,
                                  "pals": [{"id": pal, "lv": pal_lv}]
                                  if pal else []}
                                 for _n, u in self._guild_members()]
                        self._log_event(f"🎁 Scheduled gift event: "
                                        f"+{gold} gold"
                                        + (f", {evd.get('items')}"
                                           if evd.get("items") else ""))
                        threading.Thread(
                            target=lambda g=gifts, n=f"event +{gold} gold":
                            self._apply_gift(g, n), daemon=True).start()

                # automatic updates at a chosen quiet time
                if self.cfg.get("auto_update_enabled") and self._update_pending:
                    au = self.cfg.get("auto_update_time", "05:30")
                    key = "au" + now.strftime("%Y-%m-%d")
                    if self.cfg.get("auto_update_fired") != key \
                            and re.fullmatch(r"[01]?\d:[0-5]\d", au):
                        st = datetime.combine(now.date(), _parse_hm(au))
                        if st <= now <= st + timedelta(minutes=11):
                            self.cfg["auto_update_fired"] = key
                            save_cfg(self.cfg)
                            self._log_event("🔄 Auto-update: applying update")
                            self._discord("🔄 Palworld update available — "
                                          "applying it now")
                            self._warn_and_wait()
                            steamcmd_update(lambda s: None)
                            self._update_pending = False

                # automatic backups
                ih = self.cfg.get("backup_interval_h") or 0
                if ih > 0 and stats["running"]:
                    last = self.cfg.get("last_backup_ts") or 0
                    if time.time() - last >= ih * 3600:
                        self.cfg["last_backup_ts"] = time.time()
                        save_cfg(self.cfg)
                        try:
                            dst = backup_now()
                            removed = clean_old_backups(
                                int(self.cfg.get("backup_keep", 20)))
                            extra = f" ({removed} old removed)" if removed else ""
                            self._log_event("🗄 Auto backup done" + extra)
                            if self.cfg.get("offsite_enabled") \
                                    and self.cfg.get("offsite_dir"):
                                offsite_copy(os.path.basename(dst),
                                             self.cfg["offsite_dir"],
                                             int(self.cfg.get("offsite_keep", 5)))
                                self._log_event("📤 Offsite copy synced")
                        except (OSError, subprocess.SubprocessError):
                            pass

                # weekly verification of the newest backup
                wk = now.strftime("%G-W%V")
                if self.cfg.get("last_verify_week") != wk:
                    self.cfg["last_verify_week"] = wk
                    save_cfg(self.cfg)
                    bks = list_backups()
                    if bks:
                        def _vfy(n=bks[0]):
                            ok, _t = verify_backup(n)
                            self._log_event(
                                "✅ Weekly backup check passed" if ok
                                else f"⚠ Weekly backup check FAILED ({n})")
                            if not ok:
                                self._notify("⚠ Backup problem",
                                             f"Newest backup {n} failed verification!")
                        threading.Thread(target=_vfy, daemon=True).start()

                # Sunday Discord recap
                if self.cfg.get("recap_enabled") \
                        and self.cfg.get("discord_webhook") \
                        and now.weekday() == 6:  # Sunday
                    rt = self.cfg.get("recap_time", "20:00")
                    key = "recap" + now.strftime("%G-W%V")
                    if self.cfg.get("recap_fired_week") != key \
                            and re.fullmatch(r"[01]?\d:[0-5]\d", rt):
                        st = datetime.combine(now.date(), _parse_hm(rt))
                        if st <= now <= st + timedelta(minutes=11):
                            self.cfg["recap_fired_week"] = key
                            save_cfg(self.cfg)
                            threading.Thread(target=self._weekly_recap,
                                             daemon=True).start()

                # gentle RAM advisor (once per day above 6 GB)
                if stats.get("ram_gb", 0) > 6 and \
                        self.cfg.get("last_ram_warn") != now.strftime("%Y-%m-%d"):
                    self.cfg["last_ram_warn"] = now.strftime("%Y-%m-%d")
                    save_cfg(self.cfg)
                    self._log_event(f"💾 Server RAM at {stats['ram_gb']} GB — "
                                    f"consider a restart")
                    self._notify("💾 Memory creeping",
                                 f"Server is using {stats['ram_gb']} GB.")

                cur = set(players)
                if stats["running"]:
                    for p in cur - self._prev_players:
                        self._on_player_join(p[0], p[2])
                    for p in self._prev_players - cur:
                        self._log_event(f"👤 {p[0]} left")
                        self._discord(f"👋 **{p[0]} left the server")
                self._prev_players = cur
                self._last_desired = desired
                self._last_stats_running = stats["running"]
                self.q.put(("stats", {
                    "stats": stats, "players": players,
                    "next": next_event_text(self.cfg, now),
                }))
            except Exception:  # never let the monitor die
                pass
            time.sleep(10)

    def _update_checker(self):
        while True:
            time.sleep(45)
            r = remote_buildid()
            l = local_buildid()
            if r and l:
                self.q.put(("update", r != l))
            time.sleep(86400)

    def _duckdns_loop(self):
        while True:
            time.sleep(300)
            dom, tok = self.cfg.get("duck_domain"), self.cfg.get("duck_token")
            if dom and tok and not duckdns_update(dom, tok):
                self._log_event("⚠ DuckDNS update failed — check internet/domain")

    def _ip_watchdog(self):
        known = self.cfg.get("last_public_ip") or ""
        while True:
            time.sleep(300)
            try:
                with urllib.request.urlopen("https://api.ipify.org", timeout=8) as r:
                    ip = r.read().decode().strip()
            except OSError:
                continue
            if not ip:
                continue
            if known and ip != known:
                self._log_event(f"🌐 Public IP changed: {known} → {ip}")
                self.q.put(("ipchg", ip))
            known = ip
            self.cfg["last_public_ip"] = ip
            save_cfg(self.cfg)

    def _poll_queue(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind, rest = msg[0], msg[1:]
                if kind == "stats":
                    self._render(rest[0])
                elif kind == "event":
                    self._append_event(rest[0])
                elif kind == "console":
                    self._append_console(rest[0])
                elif kind == "storage":
                    self._render_storage(rest[0])
                elif kind == "ipchg":
                    ip = rest[0]
                    self._public_ip = ip
                    self.lbl_pub.configure(text=f"{ip}:{GAME_PORT}",
                                           text_color=TEXT)
                    self._toast(f"Public IP changed → {ip}", "🌐")
                    self._notify("🌐 Public IP changed",
                                 "Invite address updated (DuckDNS refreshes "
                                 "itself if configured).")
                elif kind == "rotated":
                    self._copy_rotated(rest[0])
                elif kind == "avatars":
                    self._render_players(self._players)
                    cached = load_guild_cache() or {}
                    self._render_guild(self._last_guild_data
                                       or cached.get("data"))
                elif kind == "news":
                    self._render_news(rest[0])
                elif kind == "pubip":
                    data = rest[0]
                    if data:
                        self._public_ip = data
                        self.lbl_pub.configure(text=f"{data}:{GAME_PORT}",
                                               text_color=TEXT)
                    else:
                        self.lbl_pub.configure(text="unavailable — retry ↫",
                                               text_color=TEXT_DIM)
                    self._update_checklist(self._last_stats_running)
                elif kind == "tray":
                    action = rest[0]
                    if action == "open":
                        self.deiconify()
                        self.lift()
                    elif action == "start":
                        self._do_start()
                    elif action == "stop":
                        self._do_stop()
                    elif action == "quit":
                        self._quit_app()
                elif kind == "update":
                    data = rest[0]
                    if data:
                        self._update_pending = True
                        self.lbl_update.pack(side="right", padx=(0, 8))
                        self._notify("🔄 " + T("Update available!"),
                                     "Use “Update server” in Maintenance.")
                        self._log_event("🔄 Palworld server update available")
                    elif data is False and self.lbl_update.winfo_ismapped():
                        self.lbl_update.pack_forget()
                elif kind == "guild":
                    if len(rest) == 3:
                        self._render_guild(rest[0], rest[1], rest[2])
                    else:
                        self._render_guild(rest[0])
        except queue.Empty:
            pass
        self.after(700, self._poll_queue)

    def _render(self, data):
        stats, players = data["stats"], data["players"]
        if stats.get("running"):
            u = stats["uptime_s"]
            self.lbl_status.configure(text="●  " + T("Server is running"),
                                      text_color=ACCENT)
            self.pill.configure(text="  ● RUNNING  ", fg_color=ACCENT)
            self.side_status.configure(text="● " + T("Server is running").lower(),
                                       text_color=ACCENT)
            up = f"{u // 3600}h {u % 3600 // 60:02d}m" if u >= 3600 else f"{u // 60}m"
            self.t_uptime.configure(text=up)
            self.t_ram.configure(text=f"{stats['ram_gb']} GB")
            self.t_cpu.configure(text=f"{min(999, stats.get('cpu', 0)):.0f}%")
            self.t_players.configure(text=f"{len(players)}")
            self._hist_ram.append(stats.get("ram_gb", 0))
            self._hist_cpu.append(min(999, stats.get("cpu", 0)))
            self._draw_spark(self.cv_ram, self._hist_ram)
            self._draw_spark(self.cv_cpu, self._hist_cpu)
            self.lbl_console_state.configure(
                text=f"log {os.path.getsize(CONSOLE_LOG) // 1024} KB"
                if os.path.exists(CONSOLE_LOG) else "no log yet")
        else:
            self.lbl_status.configure(text="○  " + T("Server is stopped"),
                                      text_color=RED)
            self.pill.configure(text="  ● STOPPED  ", fg_color=RED)
            self.side_status.configure(text="○ " + T("Server is stopped").lower(),
                                       text_color=RED)
            for tile in (self.t_uptime, self.t_ram, self.t_cpu, self.t_players):
                tile.configure(text="—")
        if self._tray:
            try:
                self._tray.title = (APP_TITLE + " — " +
                                    ("RUNNING" if stats.get("running") else "STOPPED"))
            except Exception:
                pass
        if self._crash_guard:
            self._crash_banner.pack(fill="x", padx=6, pady=(2, 4),
                                    before=self.lbl_status.master.master)
        else:
            self._crash_banner.pack_forget()
        if not self._busy:
            self.lbl_next.configure(text=data["next"])
            self._update_checklist(stats.get("running", False))
            self._draw_week()
            self.lbl_weekrel.configure(text=self._reliability_text())
            self._draw_players()
        self._players = players
        if self._sel_player and self._sel_player not in players:
            self._sel_player = None
        if not self._busy:
            self._render_players(players)
        # tray hover tooltip + trophy evaluation (cheap, every ~10 s)
        try:
            if self._tray is not None:
                if players:
                    names = ", ".join(self._disp_name(p[0], p[2])
                                      for p in players[:4])
                    self._tray.title = f"Palworld — {len(players)} online: {names}"
                else:
                    self._tray.title = "Palworld — serveur en ligne"
        except Exception:
            pass
        self._trophy_check()

    def _render_players(self, players):
        for w in self.plr_frame.winfo_children():
            w.destroy()
        if not players:
            ctk.CTkLabel(
                self.plr_frame, font=F_SMALL, text_color=TEXT_DIM, anchor="w",
                text="Nobody online. Friends join Palworld → multiplayer → "
                     "“Connect via IP” → your-public-IP:8211 + password.",
                justify="left",
            ).pack(anchor="w", pady=6)
            return
        for p in players:
            sel = p == self._sel_player
            row = ctk.CTkFrame(self.plr_frame, fg_color=ACCENT_SOFT if sel
                               else SURFACE_2, corner_radius=10)
            row.pack(fill="x", pady=3)
            av = self._avatar(row, p[0], p[2])
            av.pack(side="left", padx=(8, 10), pady=6)
            ctk.CTkLabel(row, text=self._disp_name(p[0], p[2]), font=F_BODY_B,
                         anchor="w",
                         text_color=ACCENT if sel else TEXT).pack(
                side="left", fill="x", expand=True)
            ctk.CTkLabel(row, text=p[2], font=("Consolas", 10),
                         text_color=TEXT_DIM).pack(side="right", padx=12)
            menu = tk.Menu(self, tearoff=0)
            menu.add_command(label=T("Kick"), command=lambda pp=p: self._kick_p(pp))
            menu.add_command(label=T("Ban"), command=lambda pp=p: self._ban_p(pp))
            menu.add_command(label="🏷  " + T("Rename"), command=lambda pp=p:
                             self._rename_player(pp))

            def rcm(e, m=menu):
                try:
                    m.tk_popup(e.x_root, e.y_root)
                finally:
                    m.grab_release()
            row.bind("<Button-3>", rcm)
            row.bind("<Button-1>", lambda e, pp=p: self._pick_player(pp))
            Tooltip(row, "Right-click for Kick / Ban.")

    def _kick_p(self, p):
        if messagebox.askyesno(T("Kick"), f"Kick {p[0]}?"):
            try:
                rcon_exec("KickPlayer " + p[2])
                self._toast(f"Kicked {p[0]}.", "👢")
            except (RconError, OSError, ValueError) as e:
                self._toast(f"Kick failed: {e}", "⚠")

    def _ban_p(self, p):
        if messagebox.askyesno(T("Ban"), f"BAN {p[0]}?\n(They cannot come back.)"):
            try:
                rcon_exec("BanPlayer " + p[2])
                self._toast(f"Banned {p[0]}.", "🚫")
            except (RconError, OSError, ValueError) as e:
                self._toast(f"Ban failed: {e}", "⚠")

    # ===== QA harness (PWQA=1 python palworld_control.py) =====
    def _qa_walk(self):
        """Screenshot every page in both appearances, then exit. Used by the
        automated visual check — not part of normal operation."""
        try:
            from PIL import ImageGrab
        except ImportError:
            self.destroy()
            return

        def shot(name):
            try:
                # pin the window so screenshots can't capture what's behind it
                self.geometry("1020x720+60+40")
                self.deiconify()
                self.attributes("-topmost", True)
                self.lift()
                self.update_idletasks()
                self.update()
                ImageGrab.grab(bbox=(
                    self.winfo_rootx(), self.winfo_rooty(),
                    self.winfo_rootx() + self.winfo_width(),
                    self.winfo_rooty() + self.winfo_height(),
                )).save(os.path.join(BASE, "app", f"qa_{name}.png"))
            except Exception:
                pass

        def shot_win(win, name):
            try:
                win.attributes("-topmost", True)
                win.lift()
                self.update_idletasks()
                self.update()
                ImageGrab.grab(bbox=(
                    win.winfo_rootx(), win.winfo_rooty(),
                    win.winfo_rootx() + win.winfo_width(),
                    win.winfo_rooty() + win.winfo_height(),
                )).save(os.path.join(BASE, "app", f"qa_{name}.png"))
            except Exception:
                pass

        def pump(seconds):
            end = time.time() + seconds
            while time.time() < end:
                try:
                    self.update()
                except tk.TclError:
                    return
                time.sleep(0.03)

        for mode in ("Dark", "Light"):
            ctk.set_appearance_mode(mode)
            self._refresh_theme()
            for pid, *_rest in self.PAGES:
                self._show_page(pid)
                self.update_idletasks()
                self.update()
                shot(f"{pid}_{mode.lower()}")
        # gift wizard: pals grid, items grid, and a filled basket
        ctk.set_appearance_mode("Dark")
        self._refresh_theme()
        try:
            self._open_gift_wizard()
            pump(2.5)
            wiz = self.winfo_children()
            wiz = next((w for w in wiz if isinstance(w, ctk.CTkToplevel)), None)
            print("QA wizard entries(pals):", len(getattr(self, "_gw_entries", [])),
                  "| with art:", len(getattr(self, "_gw_has_img", {})))
            shot_win(wiz, "gift_wizard_pals")
            self._gw_tab.set("\U0001f392  " + T("Items"))
            self._gw_render(getattr(self, "_gw_pal_cat", []),
                            getattr(self, "_gw_item_cat", []),
                            getattr(self, "_gw_paldex", None))
            pump(2.5)
            print("QA wizard entries(items):",
                  len(getattr(self, "_gw_entries", [])),
                  "| with art:", len(getattr(self, "_gw_has_img", {})))
            shot_win(wiz, "gift_wizard_items")
            # simulate a selection to show the basket
            for sid, info in (("SheepBall", {"kind": "pal", "lv": 30}),
                              ("PalSphere", {"kind": "item", "qty": 10})):
                if sid in getattr(self, "_gw_buttons", {}):
                    self._gw_sel[sid] = info
                    self._gw_mark(sid, True)
            self._gw_refresh_basket()
            pump(0.6)
            shot_win(wiz, "gift_wizard_basket")
            try:
                wiz.destroy()
            except tk.TclError:
                pass
        except Exception as e:
            print("QA wizard phase failed:", e)
        self.after(600, lambda: (self.destroy(), os._exit(0)))


def main():
    # single-instance guard: a second launch (e.g. double-click twice) would
    # fight over settings.json and the tray — just focus the first one
    try:
        import ctypes
        ctypes.windll.kernel32.CreateMutexW(None, False,
                                            "PalworldControlSingleInstance")
        if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            messagebox.showinfo(
                APP_TITLE,
                T("The app is already running.\n"
                  "Look for its icon near the clock (or in the taskbar)."))
            return
    except Exception:
        pass
    if sys.platform != "win32":
        try:
            from tkinter import messagebox as _mb
            _mb.showerror(APP_TITLE,
                          "This manager drives the Windows Palworld "
                          "dedicated server.\nPalworld has no macOS "
                          "dedicated server \u2014 host the server on a "
                          "Windows PC.")
        except Exception:
            pass
        return
    cfg = load_cfg()
    if not cfg.get("accent_v10"):  # one-time: artwork palette became the default
        if cfg.get("accent") in ("green", "", None):
            cfg["accent"] = "sky"
        cfg["accent_v10"] = True
        save_cfg(cfg)
    apply_visual_prefs(cfg)
    ctk.set_appearance_mode(cfg.get("appearance", "Dark"))
    ctk.set_default_color_theme("green")
    app = App()
    if psutil is None:
        messagebox.showwarning(
            "Limited mode",
            "psutil is missing — start/stop and stats will not work. "
            "Reinstall the app.",
        )
    if os.environ.get("PWQA"):
        if os.environ.get("PWQA_LANG"):  # QA/manual screenshots in FR
            cfg["lang"] = os.environ["PWQA_LANG"]
            apply_visual_prefs(cfg)

        def _splash_shot():
            try:
                from PIL import ImageGrab
                sp = getattr(app, "_splash", None)
                if sp is not None and sp.winfo_exists():
                    ImageGrab.grab(bbox=(
                        sp.winfo_rootx(), sp.winfo_rooty(),
                        sp.winfo_rootx() + 780, sp.winfo_rooty() + 440,
                    )).save(os.path.join(BASE, "app", "qa_splash.png"))
            except Exception:
                pass
        app.after(900, _splash_shot)
        app.after(5000, app._qa_walk)
    app.mainloop()


if __name__ == "__main__":
    main()
