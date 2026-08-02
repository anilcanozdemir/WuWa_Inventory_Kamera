@echo off
rem Click each Resonance Chain node and OCR Activated.
rem Open Resonators, select Aalto (S6) or Taoqi (S1) on Overview first.
setlocal
cd /d "%~dp0.."

net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo Chain probe starting in 3s — focus game on Overview...
timeout /t 3 /nobreak >nul
".venv\Scripts\python.exe" "tools\probe_chain.py"
echo.
pause
