@echo off
rem Click Aalto portrait on the roster (Taoqi/Aalto/Chixia visible).
setlocal
cd /d "%~dp0.."

net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo Opening Aalto click recorder...
".venv\Scripts\python.exe" "tools\record_aalto_click.py"
echo.
pause
