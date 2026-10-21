# Windows Installer

## Download (no Python required)

1. Go to [Releases](../../../releases)
2. Download `insightByMilton-vXX-windows.zip`
3. Extract the zip anywhere (keep `insightByMilton.exe` and `_internal/` together)
4. Double-click `insightByMilton.exe`

Requires **Windows 10 or 11**. The zip includes every dependency — Python is not needed.

---

## Build from source

### Prerequisites

- Python 3.10+
- All dependencies installed: `pip install -r requirements.txt`
- PyInstaller: `pip install pyinstaller`

### One-click build

Double-click **`build.bat`** in the project root.

### Manual command

```bat
python -m PyInstaller ^
    --noconfirm ^
    --windowed ^
    --name insightByMilton ^
    --icon icon.ico ^
    --add-data "assets;assets" ^
    --add-data "icon.ico;." ^
    insightByMilton.py
```

Output: `dist\insightByMilton\insightByMilton.exe`

Keep `insightByMilton.exe` and `_internal\` in the same folder — the app needs both.

---

## Notes

- The app stores its data (watchlist, portfolio, settings, alerts) in `%APPDATA%\InsightByMilton`
- Windows notifications (`win11toast`) require Windows 10 Build 1903 or later
- Drag-and-drop CSV import requires `tkinterdnd2` (included in the pre-built installer)
