# Third-party components & credits

This project bundles or downloads the following community components:

- **PalworldSaveTools** (MIT) — save parsing/compression
  https://github.com/cheahjs/palworld-save-tools
  (bundled under app/tools/PST and app/tools/PalworldSaveTools-main, trimmed:
  GUI parts removed)
- **Palworld-Pal-Editor** asset set — item/pal icons and localized names used
  by the gift wizard. https://github.com/KrisCris/Palworld-Pal-Editor
  Downloaded automatically on first use of the gift wizard (~90 MB, once);
  not redistributed inside this archive.
- **palworld-paldex-api** by mlg404 — fallback Pal artwork.
  https://github.com/mlg404/palworld-paldex-api (downloaded at runtime)
- **CustomTkinter**, **pystray**, **Pillow**, **qrcode**, **psutil** (their
  respective licenses, all permissive).
- Python 3.12 embeddable distribution (Python Software Foundation license)
  under app/tools/py312, used only by the save toolkit.

Palworld game content (icons, names) is © Pocketpair; this is a fan-made,
non-affiliated tool. Game assets are fetched at runtime from the community
repositories above for personal use.
