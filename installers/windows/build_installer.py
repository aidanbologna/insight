"""Builds the Windows downloads for Insight by Milton.

    python installers/windows/build_installer.py        (or double-click build.bat)

Puts two files in the release/ folder at the top of the project:

    InsightByMilton-Setup.exe          the one-file installer people download and double-click
    insightByMilton-vNN-windows.zip    a portable copy: extract anywhere, run insightByMilton.exe

Needs:  pip install -r requirements.txt pyinstaller

The building happens in a temporary folder outside the project, because OneDrive and antivirus
programs like to lock freshly built files. Upload both files to a GitHub release; the README's
download button points at releases/latest/download/InsightByMilton-Setup.exe.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
APP_NAME = "Insight by Milton"
PUBLISHER = "The Milton Review"
BG, BORDER, MUTED = "#FDFBF7", "#E6E0D6", "#595959"

# Big libraries that other packages *can* use but this app never does (yfinance's optional price
# repair, curl_cffi's optional gevent mode). Leaving them out makes the download much smaller.
EXCLUDE = ("scipy", "gevent", "greenlet", "eventlet", "zope")

# The setup window's logo at 100 %, 125 %, 150 %, 200 % and 250 % display scaling.
LOGO_HEIGHTS = (46, 58, 69, 92, 115)


def app_version():
    with open(os.path.join(ROOT, "insightByMilton.py"), encoding="utf-8") as f:
        return re.search(r'^VERSION = "([^"]+)"', f.read(), re.M).group(1)


def run(*command):
    print("\n>", " ".join(os.path.basename(part) if os.path.isabs(part) else part for part in command), flush=True)
    subprocess.run(command, check=True)


def pyinstaller(*options):
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN", *options)


def data(source, destination="."):
    return ("--add-data", f"{source}{os.pathsep}{destination}")


def write_version_info(path, version, description, filename):
    """The details Windows shows under Properties > Details and in Task Manager."""
    numbers = [int(n) for n in re.findall(r"\d+", version)][:4]
    numbers += [0] * (4 - len(numbers))
    strings = {"CompanyName": PUBLISHER, "FileDescription": description, "FileVersion": version,
               "InternalName": os.path.splitext(filename)[0], "LegalCopyright": f"(c) {PUBLISHER}",
               "OriginalFilename": filename, "ProductName": APP_NAME, "ProductVersion": version}
    rows = ",\n        ".join(f"StringStruct({key!r}, {value!r})" for key, value in strings.items())
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={tuple(numbers)}, prodvers={tuple(numbers)}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
        {rows}])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""")


def flat_logo(height):
    """The logo on the cream page colour, resized smoothly."""
    logo = Image.open(os.path.join(ROOT, "assets", "logo.png")).convert("RGBA")
    logo = Image.alpha_composite(Image.new("RGBA", logo.size, BG), logo).convert("RGB")
    return logo.resize((round(logo.width * height / logo.height), height), Image.LANCZOS)


def stage_assets(folder):
    """Only what the app loads while running. (The repository's icon.png is a 15 MB original; the app
    only ever shows it at 128 px, in notifications.)"""
    os.makedirs(folder)
    shutil.copy(os.path.join(ROOT, "assets", "logo.png"), folder)
    icon = Image.open(os.path.join(ROOT, "assets", "icon.png"))
    icon.thumbnail((256, 256), Image.LANCZOS)
    icon.save(os.path.join(folder, "icon.png"), optimize=True)
    fonts = os.path.join(ROOT, "assets", "fonts")
    if os.path.isdir(fonts):
        shutil.copytree(fonts, os.path.join(folder, "fonts"))


def make_splash(path):
    """Shown the instant the installer is double-clicked, while it unpacks itself."""
    width, height = 500, 240
    image = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, width - 1, height - 1], outline=BORDER)
    logo = flat_logo(80)
    image.paste(logo, ((width - logo.width) // 2, 58))
    try:
        font = ImageFont.truetype("segoeui.ttf", 17)
    except OSError:
        font = ImageFont.load_default()
    draw.text((width / 2, 178), "Getting setup ready…", fill=MUTED, font=font, anchor="mm")
    image.save(path)


def zip_folder(folder, path, compression, level=None):
    with zipfile.ZipFile(path, "w", compression, compresslevel=level) as archive:
        for base, _, files in os.walk(folder):
            for name in files:
                full = os.path.join(base, name)
                archive.write(full, os.path.relpath(full, folder))
    return path


def megabytes(path):
    if os.path.isdir(path):
        size = sum(os.path.getsize(os.path.join(base, name)) for base, _, files in os.walk(path) for name in files)
    else:
        size = os.path.getsize(path)
    return f"{size / 1e6:.1f} MB"


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Build the Windows installer and portable zip.")
    parser.add_argument("--work", default=os.path.join(tempfile.gettempdir(), "insight-by-milton-build"),
                        help="scratch folder for the build (default: in your temp folder)")
    parser.add_argument("--out", default=os.path.join(ROOT, "release"), help="where to put the finished files")
    parser.add_argument("--setup-only", action="store_true",
                        help="reuse the app already built in the work folder and rebuild just the installer")
    options = parser.parse_args()
    work, out = os.path.abspath(options.work), os.path.abspath(options.out)
    version = app_version()
    icon = os.path.join(ROOT, "icon.ico")
    print(f"Building {APP_NAME} {version}\n  work folder: {work}\n  output:      {out}")
    app = os.path.join(work, "dist", "insightByMilton")
    os.makedirs(out, exist_ok=True)

    # 1. the app itself: a folder with insightByMilton.exe and _internal
    if options.setup_only:
        if not os.path.isfile(os.path.join(app, "insightByMilton.exe")):
            sys.exit(f"--setup-only needs an app already built in {app}")
    else:
        shutil.rmtree(work, ignore_errors=True)
        os.makedirs(work)
        assets = os.path.join(work, "stage", "assets")
        stage_assets(assets)
        app_info = os.path.join(work, "app_version.txt")
        write_version_info(app_info, version, APP_NAME, "insightByMilton.exe")
        excludes = [part for module in EXCLUDE for part in ("--exclude-module", module)]
        pyinstaller("--windowed", "--name", "insightByMilton", "--icon", icon, "--version-file", app_info,
                    *data(assets, "assets"), *data(icon), *excludes,
                    "--distpath", os.path.join(work, "dist"), "--workpath", os.path.join(work, "build-app"),
                    "--specpath", work, os.path.join(ROOT, "insightByMilton.py"))
    leftovers = [name for name in os.listdir(os.path.join(app, "_internal")) if name.split(".")[0] in EXCLUDE]
    if leftovers:
        sys.exit(f"These were meant to be left out but got bundled: {leftovers}")
    print(f"\nApp folder: {megabytes(app)}")

    # 2. portable zip (plain "deflate" so Windows' own Extract All can open it)
    portable = zip_folder(app, os.path.join(out, f"insightByMilton-v{version.split('.')[0]}-windows.zip"),
                          zipfile.ZIP_DEFLATED, 9)
    print(f"Portable zip: {megabytes(portable)}")

    # 3. the installer: setup_app.py with the app packed inside (LZMA squeezes it noticeably smaller)
    payload = zip_folder(app, os.path.join(work, "payload.zip"), zipfile.ZIP_LZMA)
    print(f"Installer payload: {megabytes(payload)}")
    setup_json = os.path.join(work, "setup.json")
    with open(setup_json, "w", encoding="utf-8") as f:
        json.dump({"version": version, "logo_heights": list(LOGO_HEIGHTS)}, f)
    logos = []
    for height in LOGO_HEIGHTS:
        logo = os.path.join(work, f"logo-{height}.png")
        flat_logo(height).save(logo)
        logos += data(logo)
    splash = os.path.join(work, "splash.png")
    make_splash(splash)
    setup_info = os.path.join(work, "setup_version.txt")
    write_version_info(setup_info, version, f"{APP_NAME} Setup", "InsightByMilton-Setup.exe")
    pyinstaller("--onefile", "--windowed", "--name", "InsightByMilton-Setup", "--icon", icon,
                "--version-file", setup_info, "--splash", splash,
                *data(payload), *data(setup_json), *data(icon), *logos,
                "--distpath", os.path.join(work, "dist"), "--workpath", os.path.join(work, "build-setup"),
                "--specpath", work, os.path.join(HERE, "setup_app.py"))
    setup = os.path.join(out, "InsightByMilton-Setup.exe")
    shutil.copy(os.path.join(work, "dist", "InsightByMilton-Setup.exe"), setup)

    print(f"\nDone. {APP_NAME} {version}")
    for path in (setup, portable):
        print(f"  {megabytes(path):>9}  {path}\n             sha256 {sha256(path)}")


if __name__ == "__main__":
    main()
