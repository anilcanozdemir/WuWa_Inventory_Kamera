@echo off
rem Runs only the echo scan, elevated (the game ignores input from a normal process).
rem Double-click it; it asks for elevation itself and then minimises its own window.
setlocal
cd /d "%~dp0.."

net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo Scanning echoes. Do not touch the mouse or keyboard until it finishes.
echo Progress: debug_out\scan_*\scan.log
".venv\Scripts\python.exe" "tools\scan_echoes.py"
echo.
echo Finished. Report: debug_out\scan_*\report.json
pause
