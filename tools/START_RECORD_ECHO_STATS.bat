@echo off
rem Record Echo STAT name/value columns only. Equip UI open first, then Start.
setlocal
cd /d "%~dp0.."

net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo Opening Echo STAT ROI recorder...
".venv\Scripts\python.exe" "tools\record_echo_stats_rois.py"
echo.
pause
