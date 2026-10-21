# Installers

| Platform | Status | Notes |
|---|---|---|
| **Windows 10/11** | ✅ Pre-built | Download the `.zip` from [Releases](../../releases) — no Python needed |
| **Linux** | 🔧 Build from source | See [`linux/`](linux/README.md) |
| **macOS** | 🔧 Build from source | See [`mac/`](mac/README.md) |

Pre-built Windows installers are attached to each [GitHub Release](../../releases) starting with v10.
Older versions and Linux/macOS must be built from source using PyInstaller (see the platform folders).

---

## Windows (quick start)

1. Go to [Releases](../../releases) and download `insightByMilton-vXX-windows.zip`
2. Extract the zip anywhere
3. Double-click **`insightByMilton.exe`**

Requires Windows 10 or 11. No Python installation needed.

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

Or see [`windows/README.md`](windows/README.md) for the full command.

### Linux

```bash
bash installers/linux/build.sh
```

### macOS

```bash
bash installers/mac/build.sh
```
