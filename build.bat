@echo off
REM Builds dist\insightByMilton\insightByMilton.exe with the assets bundled inside.
cd /d "%~dp0"
python -m PyInstaller --noconfirm --windowed --name insightByMilton --icon icon.ico ^
  --add-data "assets;assets" --add-data "icon.ico;." insightByMilton.py
echo.
echo Done. Your app is in dist\insightByMilton\insightByMilton.exe
pause
