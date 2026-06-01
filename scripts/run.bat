@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
REM Run the voice input method (Windows). Auto-locates project root, uses .venv python.
REM   scripts\run.bat         start the app
REM   scripts\run.bat probe   probe key names: press a key to see its hotkey string
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo [X] .venv\Scripts\python.exe not found.
  echo     Run first: scripts\setup_env.bat
  exit /b 1
)
if /i "%~1"=="probe" (
  ".venv\Scripts\python.exe" scripts\probe_key.py
) else (
  ".venv\Scripts\python.exe" -m desktop.main
)
