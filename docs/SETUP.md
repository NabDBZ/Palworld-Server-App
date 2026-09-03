# Setup guide — your own Palworld server in ~15 minutes

*Guide d'installation — votre serveur Palworld privé en ~15 minutes (FR ci-dessous).*

---

## English

### 1. Prepare the folder

Create a folder for everything, for example `C:\PalworldServer`. Unzip the
distribution into it so you have:

```
C:\PalworldServer\
├── PalworldControl.exe
├── app\            (source + save toolkit — keep it next to the exe)
├── docs\
└── screenshots\
```

### 2. Install SteamCMD (one time)

1. Download the SteamCMD Windows zip:
   <https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip>
2. Create `C:\PalworldServer\steamcmd\` and extract it there
   (you need `steamcmd.exe` inside that folder).

### 3. Install the Palworld dedicated server (two commands)

Open a command prompt and run:

```
cd C:\PalworldServer\steamcmd
steamcmd +force_install_dir C:\PalworldServer\server +login anonymous +app_update 2394010 validate +quit
```

This downloads the dedicated server (~8 GB) into `C:\PalworldServer\server`.
Re-run the same command whenever you want to update it (the app can also do
it for you from the Maintenance page).

### 4. First launch of the manager

Double-click `PalworldControl.exe`:

- it detects the server and shows a setup checklist;
- set your **server name**, **password** and options in *Settings*
  (save, then accept the restart — the app applies settings safely while
  the server is stopped);
- press **Start**.

Friends join from Palworld → *Join multiplayer game (IP address)* →
`your-address:8211` + the password. On your own PC, connect with
`127.0.0.1:8211`.

### 5. Open it to the world

1. **Windows firewall**: Maintenance → *Apply Windows fixes* (admin prompt) —
   opens UDP 8211 and keeps the PC awake.
2. **Your internet box**: forward **UDP 8211** to this PC's local IP
   (find it on the Server page, e.g. `192.168.0.x`). Every box brand does it
   differently: look for "port forwarding / redirection de ports".
3. Share your **public IP** (shown on the Server page) — or a DuckDNS domain.
4. **Crossplay** (Steam + Xbox + PS5 in the same world): enabled by default —
   console friends search the server **name** in the in-game community server
   list (consoles cannot type an IP) and enter the password.

### 6. Daily use

Leave the app running (it minimizes to the tray and watches the server):
daily 05:00 restart, crash auto-restart, zip backups, update badge, gift
wizard, scheduled gifts and announcements. The full manual is
`docs/Manuel_Utilisateur.pdf`.

---

## Français

### 1. Préparer le dossier

Créez un dossier, par exemple `C:\PalworldServer`, et dézippez la distribution
dedans (`PalworldControl.exe` à côté du dossier `app`).

### 2. Installer SteamCMD (une fois)

Téléchargez <https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip> et
extrayez-le dans `C:\PalworldServer\steamcmd\`.

### 3. Installer le serveur dédié Palworld

Dans une invite de commandes :

```
cd C:\PalworldServer\steamcmd
steamcmd +force_install_dir C:\PalworldServer\server +login anonymous +app_update 2394010 validate +quit
```

(~8 Go dans `C:\PalworldServer\server` ; la même commande sert de mise à jour.)

### 4. Premier lancement du gestionnaire

Double-cliquez sur `PalworldControl.exe` : liste de configuration guidée,
nom/mot de passe du serveur dans *Réglages* (Enregistrer puis accepter le
redémarrage), puis **Démarrer**. Vos amis rejoignent depuis Palworld via
l'adresse IP + mot de passe ; sur votre PC : `127.0.0.1:8211`.

### 5. Ouvrir le serveur à vos amis

1. **Pare-feu** : Maintenance → *Appliquer les correctifs Windows* (UAC).
2. **Box internet** : rediriger **UDP 8211** vers l'IP locale du PC
   (affichée sur la page Serveur).
3. Partagez votre IP publique (affichée sur la page Serveur) ou un domaine
   DuckDNS.
4. **Crossplay** (Steam + Xbox + PS5) : activé par défaut — vos amis console
   cherchent le **nom** du serveur dans la liste des serveurs communautaires
   (pas de champ IP sur console) + mot de passe.

### 6. Au quotidien

Laissez l'appli tourner (elle se réduit près de l'horloge) : redémarrage
quotidien 05 h, relance auto en cas de crash, sauvegardes zip, badge de mise à
jour, assistant de cadeaux. Manuel complet : `docs/Manuel_Utilisateur.pdf`.
