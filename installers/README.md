# Installers

| Platform | Status | Notes |
|---|---|---|
| **Windows 10/11** | ✅ One-click installer | [Download `InsightByMilton-Setup.exe`](https://github.com/aidanbologna/insight/releases/latest/download/InsightByMilton-Setup.exe) — no Python needed |
| **Linux** | 🔧 Build from source | See [`linux/`](linux/README.md) |
| **macOS** | 🔧 Build from source | See [`mac/`](mac/README.md) |

The Windows installer is attached to each [GitHub Release](../../releases) starting with v11, next to a
portable `.zip` (v10 and later). Linux and macOS are built from source with PyInstaller.

---

## Windows (quick start)

1. Download **[InsightByMilton-Setup.exe](https://github.com/aidanbologna/insight/releases/latest/download/InsightByMilton-Setup.exe)**
2. Open it. If Windows shows "Windows protected your PC", click **More info** then **Run anyway**
3. Click **Install**

Requires Windows 10 or 11. No Python and no administrator password needed.
Details, the portable zip and silent installs for computer labs: [`windows/README.md`](windows/README.md).

---

## Build from source (all platforms)

```bash
pip install -r requirements.txt
pip install pyinstaller
```

Then use the platform-specific script in `windows/`, `linux/` or `mac/`.

### Windows

```bat
build.bat
```

Builds `release\InsightByMilton-Setup.exe` and the portable zip. See [`windows/README.md`](windows/README.md).

### Linux

```bash
bash installers/linux/build.sh
```

### macOS

```bash
bash installers/mac/build.sh
```
