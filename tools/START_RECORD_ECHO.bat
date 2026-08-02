@echo off
rem Always-on-top Echo ROI recorder. Open Resonator Echo tab first, then Start.
setlocal
cd /d "%~dp0.."

net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo Opening Echo ROI recorder...
".venv\Scripts\python.exe" "tools\record_echo_rois.py"
echo.
pause
