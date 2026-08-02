@echo off
rem Full characters scan with Weapon / Forte / Chain / Echo details (elevated).
rem Double-click; asks for elevation. F12 aborts. ~20–30 min for ~20 resonators.
setlocal
cd /d "%~dp0.."

net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo Full characters scan: name/level + Weapon + Forte + Chain + Echo.
echo Expect ~20–30 minutes. F12 aborts.
echo Progress prints here; log in debug_out\characters_*\scan.log
".venv\Scripts\python.exe" "tools\scan_characters.py"
echo.
echo Finished. Latest: debug_out\_latest_characters.txt
pause
