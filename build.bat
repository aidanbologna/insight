@echo off
REM Builds the Windows downloads into the release\ folder:
REM   release\InsightByMilton-Setup.exe          one-file installer (what people download)
REM   release\insightByMilton-vNN-windows.zip    portable copy
REM Needs:  pip install -r requirements.txt pyinstaller
cd /d "%~dp0"
python installers\windows\build_installer.py
if errorlevel 1 (
  echo.
  echo The build failed. Scroll up for the reason.
) else (
  echo.
  echo Done. Upload both files in the release\ folder to a GitHub release.
)
pause
