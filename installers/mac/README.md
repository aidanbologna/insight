# macOS Build

No pre-built macOS binary is provided. Build from source using PyInstaller.

## Prerequisites

- Python 3.10+ (install via [Homebrew](https://brew.sh): `brew install python`)
- Tkinter: included with Python from Homebrew; if missing, `brew install python-tk`

## Platform notes

The app was developed on Windows. Two things need attention before building on macOS:

1. **`win11toast`** — Windows-only notifications library. Remove it from `requirements.txt`
   before installing. The app will run without Windows-style notifications.

2. **`tkinterdnd2`** — drag-and-drop CSV import. Works on macOS.

## Build

```bash
bash installers/mac/build.sh
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

> **Note:** macOS uses `:` as the `--add-data` separator; Windows uses `;`.

Output: `dist/insightByMilton.app`

To run: `open dist/insightByMilton.app`

## Signing (optional)

Unsigned apps will show a Gatekeeper warning on first launch. Right-click the `.app`
and choose **Open** to bypass it, or sign with your Apple Developer certificate:

```bash
codesign --deep --force --verify --verbose \
    --sign "Developer ID Application: Your Name (TEAMID)" \
    dist/insightByMilton.app
```

## Run without building

```bash
pip install -r requirements.txt
python insightByMilton.py
```
