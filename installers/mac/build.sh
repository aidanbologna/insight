#!/usr/bin/env bash
# Build Insight by Milton for macOS using PyInstaller.
# Run from the project root: bash installers/mac/build.sh
#
# Note: macOS uses ':' as the --add-data separator (Windows uses ';').
# Note: win11toast is Windows-only — remove it from requirements.txt first.

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
echo "Build complete: dist/insightByMilton.app"
echo "Run with: open dist/insightByMilton.app"
