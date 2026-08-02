@echo off
rem Always-on-top Forte click recorder (Start button UI).
setlocal
cd /d "%~dp0.."

net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo Opening recorder window (always on top)...
".venv\Scripts\python.exe" "tools\record_forte_clicks.py"
echo.
pause
