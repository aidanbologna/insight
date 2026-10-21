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

## Windows SmartScreen warning

When you first run the exe, Windows may show a blue SmartScreen dialog saying
*"Windows protected your PC"*. This happens because the app isn't code-signed yet.

**To bypass it:**
1. Click **"More info"** (below the warning text)
2. Click **"Run anyway"**

This is a one-time step per machine. The app is safe — SmartScreen blocks all unsigned
executables, including clean PyInstaller builds, until they accumulate enough "reputation."

---

## Notes

- The app stores its data (watchlist, portfolio, settings, alerts) in `%APPDATA%\InsightByMilton`
  — this is your personal data folder; it is **not** bundled in the exe and is never shared
- Windows notifications (`win11toast`) require Windows 10 Build 1903 or later
- Drag-and-drop CSV import requires `tkinterdnd2` (included in the pre-built installer)
