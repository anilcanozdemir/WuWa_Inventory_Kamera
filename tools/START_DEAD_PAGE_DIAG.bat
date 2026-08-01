@echo off
rem Targeted dead-page debug ONLY (default pages 4 12 13). No full inventory scan.
rem Example: START_DEAD_PAGE_DIAG.bat 4
rem Example: START_DEAD_PAGE_DIAG.bat 4 12 13
setlocal
cd /d "%~dp0.."

net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs -ArgumentList '%*'"
    exit /b
)

echo Dead-page TARGET diag. Args: %*
echo Default targets: 4 12 13. F12 aborts.
".venv\Scripts\python.exe" "tools\diagnose_dead_pages.py" %*
echo.
echo Done. Screenshots: debug_out\dead_*
pause
