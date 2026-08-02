@echo off
rem Resonator roster recorder: page1 (top) then page2 (next page).
setlocal
cd /d "%~dp0.."

net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo Opening roster click recorder (2 pages)...
".venv\Scripts\python.exe" "tools\record_roster_clicks.py"
echo.
pause
