# Windows installer

## Install (no Python required)

1. Download **[InsightByMilton-Setup.exe](https://github.com/aidanbologna/insight/releases/latest/download/InsightByMilton-Setup.exe)**
2. Open the downloaded file
3. Click **Install**

That's it. The app opens when setup finishes, and afterwards it is in the Start menu and on the desktop.

Requires **Windows 10 or 11**. Everything the app needs is inside the setup file.

### What setup does

Everything is for the signed-in Windows user only, so **no administrator password is needed**.

| | |
|---|---|
| Program files | `%LOCALAPPDATA%\Programs\Insight by Milton` (you can choose another folder) |
| Shortcuts | Start menu, and the desktop if the box is ticked |
| Uninstall entry | Settings > Apps > Installed apps > Insight by Milton |
| Your data | `%APPDATA%\InsightByMilton` (watchlist, portfolio, alerts, settings, colors) |

Setup never touches your data folder, so updating keeps everything.

### Update

Download the newest `InsightByMilton-Setup.exe` and run it. It replaces the old version in place.
Close the app first; setup tells you if it is still open.

### Uninstall

**Settings > Apps > Installed apps > Insight by Milton > Uninstall.**
It asks whether to also delete your watchlist, portfolio and settings (the default is to keep them).

---

## "Windows protected your PC"

The setup file is not code-signed yet, so Windows may warn about it the first time.

- **Browser:** if the download bar says the file "isn't commonly downloaded", choose **Keep** (Edge: **⋯ > Keep > Show more > Keep anyway**).
- **Blue SmartScreen box:** click **More info**, then **Run anyway**.

SmartScreen shows this for every unsigned program until it has been downloaded by enough people.
Some school-managed computers block unsigned installers completely. In that case use the portable
copy below, or ask IT to run the silent install.

---

## Portable copy (no installing)

1. On the [latest release](https://github.com/aidanbologna/insight/releases/latest), download `insightByMilton-vNN-windows.zip`
2. Right-click the zip > **Extract All**
3. Open the extracted folder and double-click **`insightByMilton.exe`**

Keep `insightByMilton.exe` and the `_internal` folder together.

---

## Computer labs: silent install

```bat
InsightByMilton-Setup.exe --silent
```

| Option | Effect |
|---|---|
| `--silent` | Install without showing a window |
| `--dir "D:\Apps\Insight by Milton"` | Install somewhere else |
| `--no-desktop` | Skip the desktop shortcut |

The install is per-user, so run it as the student's account (for example from a logon script).
Exit code `0` means success, `2` means the app was open, `1` is any other failure; problems are
written to `%TEMP%\InsightByMilton-Setup.log`.

Silent uninstall: `"%LOCALAPPDATA%\Programs\Insight by Milton\insightByMilton.exe" --uninstall --quiet`

---

## Build it yourself

```bat
pip install -r requirements.txt pyinstaller
python installers\windows\build_installer.py
```

or double-click **`build.bat`** in the project root. The two downloads appear in `release\`:

| File | What it is |
|---|---|
| `InsightByMilton-Setup.exe` | The one-file installer |
| `insightByMilton-vNN-windows.zip` | The portable copy |

Upload both to a GitHub release. Keep the installer's file name exactly as it is: the README's
download button points at `releases/latest/download/InsightByMilton-Setup.exe`, so it always
fetches the newest release.

### How it works

| File | Role |
|---|---|
| [`build_installer.py`](build_installer.py) | Builds the app with PyInstaller, zips it, then builds the installer around that zip |
| [`setup_app.py`](setup_app.py) | The setup program itself: a small Tkinter window styled like the app |
| `insightByMilton.py --uninstall` | The uninstaller lives in the app, so no second program is needed |

The build leaves out libraries the app never uses (`scipy`, `gevent`) and ships a small copy of the
icon, which makes the download a little over half the size of the v10 zip.

---

## Notes

- Windows notifications (`win11toast`) need Windows 10 build 1903 or later
- Drag-and-drop CSV import uses `tkinterdnd2` (included)
- To make the SmartScreen warning go away for everyone, the two `.exe` files would need to be
  signed with a code-signing certificate
