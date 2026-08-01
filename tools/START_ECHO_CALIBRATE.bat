@echo off
rem Short elevated calibration: 3 pages, screenshots, scroll + OCR checks.
rem The game ignores mouse input from a non-elevated process.
setlocal
cd /d "%~dp0.."

net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo Calibrating echo scroll (3 pages). Do not touch mouse/keyboard.
echo Progress: debug_out\calib_*\calib.log
".venv\Scripts\python.exe" "tools\calibrate_echo_scroll.py" %*
echo.
echo Finished. Report: debug_out\calib_*\report.json
pause
