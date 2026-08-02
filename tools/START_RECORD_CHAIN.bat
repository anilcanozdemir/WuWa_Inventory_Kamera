@echo off
rem Record Resonance Chain S1-S6 click positions (once).
rem Open Resonators → Chain tab first, then Start on the floating window.
setlocal
cd /d "%~dp0.."

net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo Opening chain recorder (always on top)...
".venv\Scripts\python.exe" "tools\record_chain_clicks.py"
echo.
pause
