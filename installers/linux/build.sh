#!/usr/bin/env bash
# Build Insight by Milton for Linux using PyInstaller.
# Run from the project root: bash installers/linux/build.sh
#
# Note: Linux uses ':' as the --add-data separator (Windows uses ';').
# Note: win11toast is Windows-only — remove it from requirements.txt first,
#       or ignore the warning (the app runs without Windows notifications).

set -e

cd "$(dirname "$0")/../.."

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

echo ""
echo "Build complete: dist/insightByMilton/insightByMilton"
