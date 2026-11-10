# =============================================================================
#  Insight by Milton — Windows setup program
#
#  build_installer.py turns this file into InsightByMilton-Setup.exe with the app
#  packed inside. People download that one file and double-click it: no Python,
#  no zip to extract and no administrator password.
#
#  Everything it does is for the current Windows user only:
#    1. copies the app to    %LOCALAPPDATA%\Programs\Insight by Milton
#    2. adds shortcuts to the Start menu and (if ticked) the desktop
#    3. lists the app under  Settings > Apps > Installed apps  so it can be removed
#
#  Running it again installs the new version over the old one. Watchlists,
#  portfolios and settings live in %APPDATA%\InsightByMilton and are never touched.
#
#  For computer labs:  InsightByMilton-Setup.exe --silent [--dir FOLDER] [--no-desktop]
# =============================================================================

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
from datetime import datetime

import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog

APP_NAME = "Insight by Milton"
EXE_NAME = "insightByMilton.exe"
PUBLISHER = "The Milton Review"
SITE_URL = "https://www.themiltonreview.net"
MANIFEST = "install.json"                         # left in the install folder; the app's uninstaller reads it
OUR_FILES = (EXE_NAME, "_internal", MANIFEST)     # the only things setup ever replaces
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\InsightByMilton"

# Automated tests set this so shortcuts and the Apps entry go to a scratch folder / registry key
# instead of the real desktop, Start menu and Settings > Apps list.
TEST_ROOT = os.environ.get("INSIGHT_SETUP_TEST_ROOT")
# Tests can't click the buttons, so with this also set the window presses Install and Finish by itself.
TEST_AUTO = bool(TEST_ROOT and os.environ.get("INSIGHT_SETUP_TEST_AUTO"))

# The Milton Review's colours
BG, SURFACE, SAND, BORDER = "#FDFBF7", "#FFFFFF", "#F3EFE7", "#E6E0D6"
INK, MUTED, FAINT = "#1C1C1C", "#595959", "#8C877F"
ACCENT, ACCENT_DARK, UP, DOWN = "#D47A5D", "#B9603F", "#2F7D4F", "#B4473A"


class SetupError(Exception):
    """Something went wrong that the person installing can understand and fix."""


class AppRunning(SetupError):
    def __init__(self):
        super().__init__(f"{APP_NAME} is open. Close it, then try again.")


# -----------------------------------------------------------------------------
# 1. Files packed into the setup program
# -----------------------------------------------------------------------------
PAYLOAD = None      # --payload PATH, used when running this file from source


def resource(name):
    """A file bundled into the setup program (or next to this script when run from source)."""
    for base in (getattr(sys, "_MEIPASS", None), os.path.dirname(os.path.abspath(__file__))):
        if base and os.path.exists(os.path.join(base, name)):
            return os.path.join(base, name)
    raise SetupError(f"Setup is missing a file it needs ({name}). Please download it again.")


def payload_path():
    return PAYLOAD or resource("payload.zip")


def setup_info():
    """{"version": "11.0"} written by build_installer.py."""
    try:
        with open(resource("setup.json"), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (SetupError, OSError, ValueError):
        return {}


# -----------------------------------------------------------------------------
# 2. Where things go
# -----------------------------------------------------------------------------
def default_folder():
    local = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(local, "Programs", APP_NAME)


def known_folder(csidl, fallback):
    """Ask Windows where a special folder is (the desktop is often redirected into OneDrive)."""
    try:
        buffer = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buffer) == 0 and buffer.value:
            return buffer.value
    except Exception:
        pass
    return fallback


def shortcut_folders():
    """(desktop, Start menu programs folder)."""
    if TEST_ROOT:
        return os.path.join(TEST_ROOT, "Desktop"), os.path.join(TEST_ROOT, "Start Menu")
    home = os.path.expanduser("~")
    roaming = os.environ.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
    return (known_folder(0x10, os.path.join(home, "Desktop")),
            known_folder(0x02, os.path.join(roaming, "Microsoft", "Windows", "Start Menu", "Programs")))


def registry_key():
    return r"Software\InsightByMiltonSetupTest\InsightByMilton" if TEST_ROOT else UNINSTALL_KEY


def read_manifest(folder):
    try:
        with open(os.path.join(folder, MANIFEST), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def installed_version(folder):
    """The version already in a folder, "" if it's there but unlabelled (a copied zip), None if absent."""
    if not os.path.exists(os.path.join(folder, EXE_NAME)):
        return None
    return str(read_manifest(folder).get("version") or "")


def is_ours(folder):
    """True if any of our files are in the folder (also covers an install that was interrupted half-way)."""
    return any(os.path.exists(os.path.join(folder, name)) for name in OUR_FILES)


def app_running(folder):
    """Windows won't let a program that is open be replaced; opening its file for writing shows that."""
    exe = os.path.join(folder, EXE_NAME)
    if not os.path.exists(exe):
        return False
    try:
        with open(exe, "ab"):
            return False
    except OSError:
        return True


# -----------------------------------------------------------------------------
# 3. Shortcuts (.lnk files) through the Windows shell's own COM object
# -----------------------------------------------------------------------------
class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, text):
        super().__init__()
        ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(self))


def _com(obj, index, restype, argtypes=(), *args):
    """Call method number `index` in a COM object's table of functions."""
    table = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(table[index])(obj, *args)


def _shortcut_com(path, target, folder, description):
    ole32 = ctypes.oledll.ole32          # oledll raises OSError when a call reports failure
    try:
        ole32.CoInitialize(None)
    except OSError:
        pass                             # already initialised differently on this thread: fine
    text, hresult = ctypes.c_wchar_p, ctypes.HRESULT
    link, persist = ctypes.c_void_p(), ctypes.c_void_p()
    ole32.CoCreateInstance(ctypes.byref(GUID("{00021401-0000-0000-C000-000000000046}")), None, 1,
                           ctypes.byref(GUID("{000214F9-0000-0000-C000-000000000046}")), ctypes.byref(link))
    try:
        _com(link, 20, hresult, (text,), target)                        # IShellLinkW::SetPath
        _com(link, 9, hresult, (text,), folder)                         # SetWorkingDirectory
        _com(link, 7, hresult, (text,), description)                    # SetDescription
        _com(link, 17, hresult, (text, ctypes.c_int), target, 0)        # SetIconLocation
        _com(link, 0, hresult, (ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)),
             ctypes.byref(GUID("{0000010B-0000-0000-C000-000000000046}")), ctypes.byref(persist))
        try:
            _com(persist, 6, hresult, (text, ctypes.c_int), path, 1)    # IPersistFile::Save
        finally:
            _com(persist, 2, ctypes.c_ulong)                            # Release
    finally:
        _com(link, 2, ctypes.c_ulong)


def _shortcut_powershell(path, target, folder, description):
    script = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK_PATH); "
              "$s.TargetPath = $env:LNK_TARGET; $s.WorkingDirectory = $env:LNK_FOLDER; "
              "$s.Description = $env:LNK_TEXT; $s.IconLocation = $env:LNK_TARGET + ',0'; $s.Save()")
    env = dict(os.environ, LNK_PATH=path, LNK_TARGET=target, LNK_FOLDER=folder, LNK_TEXT=description)
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], env=env, check=True,
                   timeout=40, creationflags=0x08000000)


def create_shortcut(folder, target):
    """Put an "Insight by Milton" shortcut in a folder. Returns its path, or None if Windows refused."""
    path = os.path.join(folder, APP_NAME + ".lnk")
    description = "Markets, news and your portfolio, from The Milton Review"
    for make in (_shortcut_com, _shortcut_powershell):
        try:
            os.makedirs(folder, exist_ok=True)
            make(path, target, os.path.dirname(target), description)
            if os.path.exists(path):
                return path
        except Exception:
            continue
    return None


# -----------------------------------------------------------------------------
# 4. Installing
# -----------------------------------------------------------------------------
def register(folder, version, size_kb):
    """List the app under Settings > Apps > Installed apps (for this user) with a working Uninstall button."""
    import winreg
    exe = os.path.join(folder, EXE_NAME)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, registry_key()) as key:
        for name, value in (("DisplayName", APP_NAME), ("DisplayVersion", version), ("Publisher", PUBLISHER),
                            ("DisplayIcon", exe), ("InstallLocation", folder), ("URLInfoAbout", SITE_URL),
                            ("UninstallString", f'"{exe}" --uninstall'),
                            ("QuietUninstallString", f'"{exe}" --uninstall --quiet')):
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
        for name, value in (("NoModify", 1), ("NoRepair", 1), ("EstimatedSize", int(size_kb))):
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, value)


def payload_size():
    with zipfile.ZipFile(payload_path()) as archive:
        return sum(item.file_size for item in archive.infolist())


def install(folder, desktop=True, progress=None):
    """Copy the app into `folder`, add shortcuts and the Apps entry.

    progress(fraction, text) is called as it goes. Returns (shortcut paths, warnings).
    """
    progress = progress or (lambda fraction, text: None)
    folder = os.path.abspath(folder)
    version = str(setup_info().get("version") or "")
    progress(0, "Getting ready…")
    if os.path.isdir(folder) and os.listdir(folder) and not is_ours(folder):
        raise SetupError("That folder already has other files in it. Please choose a different folder.")
    if app_running(folder):
        raise AppRunning()
    earlier = read_manifest(folder).get("shortcuts") or []      # read before the old files are cleared out
    try:
        os.makedirs(folder, exist_ok=True)
        with zipfile.ZipFile(payload_path()) as archive:
            items = archive.infolist()
            total = sum(item.file_size for item in items) or 1
            if shutil.disk_usage(folder).free < total + 50 * 1024 * 1024:
                raise SetupError(f"There isn't enough free disk space. {APP_NAME} needs about "
                                 f"{total / 1e6:.0f} MB.")
            for name in OUR_FILES:              # clear out the previous version (and nothing else)
                old = os.path.join(folder, name)
                if os.path.isdir(old):
                    shutil.rmtree(old)
                elif os.path.exists(old):
                    os.remove(old)
            done = 0
            for item in items:
                destination = os.path.abspath(os.path.join(folder, item.filename))
                if os.path.commonpath([folder, destination]) != folder:
                    raise SetupError("The setup file is damaged. Please download it again.")
                if item.is_dir():
                    os.makedirs(destination, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                with archive.open(item) as source, open(destination, "wb") as out:
                    while True:
                        chunk = source.read(1 << 20)
                        if not chunk:
                            break
                        out.write(chunk)
                        done += len(chunk)
                        progress(0.96 * done / total, "Copying files…")
    except PermissionError as exc:
        if app_running(folder):
            raise AppRunning() from exc
        raise SetupError(f"Windows wouldn't let setup write to that folder.\n({exc})") from exc
    except zipfile.BadZipFile as exc:
        raise SetupError("The setup file is damaged. Please download it again.") from exc
    except OSError as exc:
        raise SetupError(f"Setup couldn't copy the files.\n({exc})") from exc

    progress(0.97, "Adding shortcuts…")
    exe = os.path.join(folder, EXE_NAME)
    desktop_folder, menu_folder = shortcut_folders()
    shortcuts, warnings = [], []
    for wanted, where, label in ((True, menu_folder, "Start menu"), (desktop, desktop_folder, "desktop")):
        if wanted:
            made = create_shortcut(where, exe)
            if made:
                shortcuts.append(made)
            else:
                warnings.append(f"Setup couldn't add the {label} shortcut.")
    # shortcuts from an earlier install stay listed so uninstalling removes them too
    for old in earlier:
        if isinstance(old, str) and old not in shortcuts and os.path.exists(old):
            shortcuts.append(old)

    progress(0.99, "Finishing…")
    try:
        register(folder, version, total // 1024)
    except OSError:
        warnings.append("Setup couldn't add the app to the Settings > Apps list.")
    with open(os.path.join(folder, MANIFEST), "w", encoding="utf-8") as f:
        json.dump({"app": APP_NAME, "version": version, "folder": folder, "shortcuts": shortcuts,
                   "registry_key": registry_key(), "installed": datetime.now().isoformat(timespec="seconds")},
                  f, indent=2)
    progress(1, "Done")
    return shortcuts, warnings


def launch(folder):
    """Start the installed app as its own program, not as a child that shares setup's temporary files."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("_PYI", "_MEI")) and k not in ("TCL_LIBRARY", "TK_LIBRARY")}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    try:
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    except Exception:
        pass
    subprocess.Popen([os.path.join(folder, EXE_NAME)], cwd=folder, env=env, close_fds=True,
                     creationflags=0x00000008 | 0x00000200)      # detached, own process group


def close_splash():
    """The "getting setup ready" picture PyInstaller shows while this program unpacks itself."""
    try:
        import pyi_splash
        pyi_splash.close()
    except Exception:       # not built with a splash screen, or running from source
        pass


# -----------------------------------------------------------------------------
# 5. The window
# -----------------------------------------------------------------------------
class Button(tk.Canvas):
    """Pill-shaped button like the ones in the app."""

    def __init__(self, parent, text, command, font, scale, primary=True):
        self.text, self.command, self.font, self.primary = text, command, font, primary
        self.hover, self.enabled = False, True
        width = font.measure(text) + int(44 * scale)
        height = font.metrics("linespace") + int(20 * scale)
        super().__init__(parent, width=width, height=height, bg=parent.cget("bg"), highlightthickness=0, bd=0,
                         cursor="hand2")
        self.radius = int(11 * scale)
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self.bind("<ButtonRelease-1>", lambda e: self.enabled and self.command())
        self._draw()

    def _hover(self, on):
        self.hover = on
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h, r = int(self["width"]), int(self["height"]), self.radius
        if self.primary:
            fill, outline, ink = (ACCENT_DARK if self.hover else ACCENT), None, BG
        else:
            fill, outline, ink = (SAND if self.hover else self["bg"]), INK, INK
        points = [1 + r, 1, w - 2 - r, 1, w - 2, 1, w - 2, 1 + r, w - 2, h - 2 - r, w - 2, h - 2,
                  w - 2 - r, h - 2, 1 + r, h - 2, 1, h - 2, 1, h - 2 - r, 1, 1 + r, 1, 1]
        self.create_polygon(points, smooth=True, fill=fill, outline=outline or fill)
        self.create_text(w / 2, h / 2, text=self.text, fill=ink, font=self.font)


class Check(tk.Frame):
    """A tick box with a label."""

    def __init__(self, parent, text, font, scale, value=True):
        super().__init__(parent, bg=parent.cget("bg"), cursor="hand2")
        self.value, self.size = value, int(18 * scale)
        self.box = tk.Canvas(self, width=self.size, height=self.size, bg=self["bg"], highlightthickness=0)
        self.box.pack(side="left")
        words = tk.Label(self, text=text, font=font, fg=INK, bg=self["bg"])
        words.pack(side="left", padx=(int(10 * scale), 0))
        for widget in (self, self.box, words):
            widget.bind("<Button-1>", lambda e: self.toggle())
        self._draw()

    def toggle(self):
        self.value = not self.value
        self._draw()

    def _draw(self):
        s = self.size
        self.box.delete("all")
        self.box.create_rectangle(1, 1, s - 2, s - 2, fill=ACCENT if self.value else SURFACE,
                                  outline=ACCENT if self.value else FAINT)
        if self.value:
            self.box.create_line(s * 0.24, s * 0.52, s * 0.43, s * 0.70, s * 0.76, s * 0.30, fill=BG,
                                 width=max(2, s // 8), capstyle="round", joinstyle="round")


class SetupWindow(tk.Tk):
    def __init__(self, folder, desktop=True):
        super().__init__()
        self.scale = self.winfo_fpixels("1i") / 96
        self.folder, self.desktop = folder, desktop
        self.version = str(setup_info().get("version") or "")
        self.busy, self.state_now, self.outcome = False, (0.0, ""), None
        self.title(f"{APP_NAME} Setup")
        self.configure(bg=BG)
        self.resizable(False, False)
        try:
            self.iconbitmap(default=resource("icon.ico"))
        except Exception:
            pass
        families = set(tkfont.families(self))
        serif = next((f for f in ("Caudex", "Georgia", "Cambria", "Times New Roman") if f in families), "TkDefaultFont")
        sans = next((f for f in ("Segoe UI", "Helvetica", "Arial") if f in families), "TkDefaultFont")
        semi = "Segoe UI Semibold" if "Segoe UI Semibold" in families else sans
        self.fonts = {"title": tkfont.Font(self, family=serif, size=19, weight="bold"),
                      "body": tkfont.Font(self, family=sans, size=10),
                      "semi": tkfont.Font(self, family=semi, size=10),
                      "small": tkfont.Font(self, family=sans, size=9),
                      "eyebrow": tkfont.Font(self, family=semi, size=8)}
        self.width = self.S(560)

        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True, padx=self.S(34), pady=(self.S(26), self.S(24)))
        self._logo = self._load_logo()
        if self._logo:
            tk.Label(outer, image=self._logo, bg=BG).pack(anchor="w", pady=(0, self.S(14)))
        self.heading = self.text(outer, "", "title")
        self.heading.pack(anchor="w")
        self.sub = self.text(outer, "", "body", MUTED)
        self.sub.pack(anchor="w", pady=(self.S(4), self.S(16)))
        self.buttons = tk.Frame(outer, bg=BG)
        self.buttons.pack(fill="x", side="bottom", pady=(self.S(20), 0))
        self.content = tk.Frame(outer, bg=BG)
        self.content.pack(fill="x")

        self.protocol("WM_DELETE_WINDOW", lambda: None if self.busy else self.destroy())
        self.show_options()
        self.update_idletasks()
        w, h = self.width, self.winfo_reqheight()
        self.geometry(f"{w}x{h}+{(self.winfo_screenwidth() - w) // 2}+{max((self.winfo_screenheight() - h) // 3, 0)}")
        self.after(50, self._to_front)
        if TEST_AUTO:
            self.after(2500, self.start)

    # --- small helpers ------------------------------------------------------------------
    def S(self, px):
        return int(round(px * self.scale))

    def text(self, parent, words, font="body", color=INK, inset=0):
        """A left-aligned label that wraps inside the window (inset: extra indent of its container)."""
        return tk.Label(parent, text=words, font=self.fonts[font], fg=color, bg=parent.cget("bg"),
                        justify="left", anchor="w", wraplength=self.width - self.S(68 + inset))

    def _load_logo(self):
        """The logo, pre-rendered by the build script at a few sizes (Tk can't resize pictures smoothly)."""
        want = self.S(46)
        sizes = setup_info().get("logo_heights") or []
        if not sizes:
            return None
        try:
            return tk.PhotoImage(file=resource(f"logo-{min(sizes, key=lambda h: abs(h - want))}.png"))
        except Exception:
            return None

    def _fit(self):
        """Grow the window if a screen needs more room than the first one did (a long error message)."""
        self.update_idletasks()
        if self.winfo_reqheight() > self.winfo_height() > 1:
            self.geometry(f"{self.width}x{self.winfo_reqheight()}")

    def _to_front(self):
        close_splash()
        self.lift()
        self.focus_force()

    def _clear(self):
        for area in (self.content, self.buttons):
            for widget in area.winfo_children():
                widget.destroy()

    def _card(self):
        card = tk.Frame(self.content, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        card.pack(fill="x")
        inner = tk.Frame(card, bg=SURFACE)
        inner.pack(fill="x", padx=self.S(20), pady=self.S(18))
        return inner

    def _button(self, text, command, primary=True):
        button = Button(self.buttons, text, command, self.fonts["body"], self.scale, primary)
        button.pack(side="right", padx=(self.S(10), 0))
        return button

    # --- step 1: options ------------------------------------------------------------------
    def show_options(self):
        self._clear()
        current = installed_version(self.folder)
        updating = current is not None
        self.heading.configure(text=f"Update {APP_NAME}" if updating else f"Install {APP_NAME}")
        if updating and current and current != self.version:
            self.sub.configure(text=f"Version {current} is installed. This replaces it with version {self.version}.")
        elif updating:
            self.sub.configure(text=f"Version {self.version}  ·  installs over the copy you already have")
        else:
            self.sub.configure(text=f"Version {self.version}  ·  the markets companion to The Milton Review")
        card = self._card()
        self.desktop_check = Check(card, "Add a shortcut to the desktop", self.fonts["body"], self.scale, self.desktop)
        self.desktop_check.pack(anchor="w")
        tk.Frame(card, bg=BORDER, height=1).pack(fill="x", pady=self.S(14))
        self.text(card, "INSTALL LOCATION", "eyebrow", ACCENT, 44).pack(anchor="w")
        self.folder_label = self.text(card, self.folder, "small", MUTED, 44)
        self.folder_label.pack(anchor="w", pady=(self.S(4), self.S(6)))
        change = tk.Label(card, text="Change…", font=self.fonts["small"], fg=ACCENT, bg=SURFACE, cursor="hand2")
        change.pack(anchor="w")
        change.bind("<Button-1>", lambda e: self.choose_folder())
        try:
            size = f"About {payload_size() / 1e6:.0f} MB of disk space. "
        except Exception:
            size = ""
        note = (size + "Your watchlist, portfolio and settings are kept." if updating else
                size + "Installs just for you, so no administrator password is needed.")
        self.text(self.content, note, "small", FAINT).pack(anchor="w", pady=(self.S(14), 0))
        self._button("Update" if updating else "Install", self.start)
        self._button("Cancel", self.destroy, primary=False)
        self._fit()

    def choose_folder(self):
        start = self.folder if os.path.isdir(self.folder) else os.path.dirname(self.folder)
        chosen = filedialog.askdirectory(parent=self, title="Choose where to install", initialdir=start)
        if chosen:
            chosen = os.path.normpath(chosen)
            if os.path.basename(chosen).lower() != APP_NAME.lower():    # always its own folder, never loose files
                chosen = os.path.join(chosen, APP_NAME)
            self.folder = chosen
            self.show_options()

    # --- step 2: copying ------------------------------------------------------------------
    def start(self):
        self.desktop = self.desktop_check.value
        self._clear()
        self.busy, self.outcome, self.state_now = True, None, (0.0, "Getting ready…")
        self.heading.configure(text="Installing…")
        self.sub.configure(text="This takes less than a minute.")
        card = self._card()
        self.bar = tk.Canvas(card, height=self.S(10), bg=SURFACE, highlightthickness=0)
        self.bar.pack(fill="x", pady=(self.S(6), self.S(12)))
        self.status = self.text(card, "", "small", MUTED, 44)
        self.status.pack(anchor="w")
        threading.Thread(target=self._work, daemon=True).start()
        self._poll()

    def _work(self):
        try:
            self.outcome = ("done",) + install(self.folder, self.desktop,
                                               lambda fraction, text: setattr(self, "state_now", (fraction, text)))
        except SetupError as exc:
            self.outcome = ("failed", str(exc))
        except Exception as exc:        # anything unexpected still gets shown, never a silent crash
            self.outcome = ("failed", f"Something unexpected went wrong.\n({type(exc).__name__}: {exc})")

    def _poll(self):
        fraction, text = self.state_now
        width, height = max(self.bar.winfo_width(), 1), int(self.bar["height"])
        self.bar.delete("all")
        self.bar.create_rectangle(0, 0, width, height, fill=SAND, outline=SAND)
        self.bar.create_rectangle(0, 0, int(width * fraction), height, fill=ACCENT, outline=ACCENT)
        self.status.configure(text=f"{text}  {fraction * 100:.0f}%")
        if self.outcome is None:
            self.after(60, self._poll)
            return
        self.busy = False
        if self.outcome[0] == "done":
            self.show_done(*self.outcome[1:])
        else:
            self.show_failed(self.outcome[1])

    # --- step 3: finished ------------------------------------------------------------------
    def show_done(self, shortcuts, warnings):
        self._clear()
        self.heading.configure(text=f"{APP_NAME} is ready")
        on_desktop = any(os.path.dirname(s) == shortcut_folders()[0] for s in shortcuts)
        self.sub.configure(text="Open it any time from the Start menu" + (" or your desktop." if on_desktop else "."))
        card = self._card()
        self.open_check = Check(card, f"Open {APP_NAME} now", self.fonts["body"], self.scale, True)
        self.open_check.pack(anchor="w")
        for warning in warnings:
            self.text(self.content, warning, "small", DOWN).pack(anchor="w", pady=(self.S(10), 0))
        self._button("Finish", self.finish)
        self._fit()
        if TEST_AUTO:
            self.after(2500, self.finish)

    def finish(self):
        if self.open_check.value:
            try:
                launch(self.folder)
            except OSError:
                pass
        self.destroy()

    def show_failed(self, message):
        self._clear()
        self.heading.configure(text="Setup couldn't finish")
        self.sub.configure(text="Nothing else on this computer was changed.")
        card = self._card()
        self.text(card, message, "body", DOWN, 44).pack(anchor="w")
        self._button("Try again", self.show_options)
        self._button("Close", self.destroy, primary=False)
        self._fit()


# -----------------------------------------------------------------------------
# 6. Start
# -----------------------------------------------------------------------------
def main():
    global PAYLOAD
    if sys.stdout is None:      # windowed programs have nowhere to print
        sys.stdout = sys.stderr = open(os.devnull, "w")
    parser = argparse.ArgumentParser(prog="InsightByMilton-Setup",
                                     description=f"Install {APP_NAME} for the current Windows user.")
    parser.add_argument("--silent", action="store_true", help="install without showing a window")
    parser.add_argument("--dir", help="folder to install into")
    parser.add_argument("--no-desktop", action="store_true", help="don't add a desktop shortcut")
    parser.add_argument("--payload", help=argparse.SUPPRESS)
    options = parser.parse_args()
    PAYLOAD = options.payload
    folder = os.path.abspath(options.dir) if options.dir else default_folder()

    if options.silent:
        close_splash()
        try:
            _, warnings = install(folder, not options.no_desktop)
            problem, code = "\n".join(warnings), 0
        except AppRunning as exc:
            problem, code = str(exc), 2
        except Exception as exc:
            problem, code = f"{type(exc).__name__}: {exc}", 1
        if problem:             # there is no window to show it in, so leave a note
            try:
                with open(os.path.join(tempfile.gettempdir(), "InsightByMilton-Setup.log"), "a", encoding="utf-8") as f:
                    f.write(f"{datetime.now().isoformat(timespec='seconds')}  {problem}\n")
            except OSError:
                pass
        return code

    try:  # crisp text on high-DPI screens
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    SetupWindow(folder, not options.no_desktop).mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
