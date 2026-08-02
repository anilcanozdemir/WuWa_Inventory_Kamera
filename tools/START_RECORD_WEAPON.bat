@echo off
rem Always-on-top Weapon ROI recorder. Open Weapon tab first, then Start.
setlocal
cd /d "%~dp0.."

net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo Opening Weapon ROI recorder...
".venv\Scripts\python.exe" "tools\record_weapon_rois.py"
echo.
pause
