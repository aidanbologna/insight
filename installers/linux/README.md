# Linux Build

No pre-built Linux binary is provided. Build from source using PyInstaller.

## Prerequisites

- Python 3.10+
- Tkinter: `sudo apt install python3-tk` (Debian/Ubuntu) or `sudo dnf install python3-tkinter` (Fedora)
- Git: `sudo apt install git`

## Platform notes

The app was developed on Windows. Two things need attention before building on Linux:

1. **`win11toast`** — Windows-only notifications library. Remove it from `requirements.txt`
   before installing, or install it and the app will run without notifications (the import
   is guarded by a try/except in v7+).

2. **`tkinterdnd2`** — drag-and-drop CSV import. Works on Linux but may require an
   extra system package (`sudo apt install python3-xlib` on Debian/Ubuntu).

## Build

```bash
bash installers/linux/build.sh
```

Or manually:

```bash
pip install -r requirements.txt
pip install pyinstaller

python -m PyInstaller \
    --noconfirm \
    --windowed \
    --name insightByMilton \
    --icon icon.ico \
    --add-data "assets:assets" \
    --add-data "icon.ico:." \
    insightByMilton.py
```

> **Note:** Linux uses `:` as the `--add-data` separator; Windows uses `;`.

Output: `dist/insightByMilton/insightByMilton`

## Run without building

```bash
pip install -r requirements.txt
python insightByMilton.py
```
