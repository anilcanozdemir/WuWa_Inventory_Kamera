@echo off
rem Single-resonator detail smoke (Weapon / Forte / RC / Echo).
rem Select Luuk (or any char) on Resonator Overview, then double-click this.
setlocal
cd /d "%~dp0.."

net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ONE CHAR — upstream Weapon/Forte/Chain (no tab discover). F12 aborts.
echo Log: debug_out\one_char_*\scan.log
".venv\Scripts\python.exe" "tools\scan_one_character.py"
echo.
echo Finished. Latest: debug_out\_latest_one_char.txt
pause
