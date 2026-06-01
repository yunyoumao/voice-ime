@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
REM Set up the runtime env (Windows): create .venv + install deps.
REM Needs Python 3.11 or 3.12 on PATH (python.org; tick "Add python.exe to PATH").
REM Avoid 3.13/3.14: some C-extension wheels are not prebuilt yet.
cd /d "%~dp0.."

echo === Creating .venv ===
py -3.12 -m venv .venv 2>nul || py -3.11 -m venv .venv 2>nul || python -m venv .venv
if not exist ".venv\Scripts\python.exe" (
  echo [X] Failed to create venv. Install Python 3.11 or 3.12 first.
  exit /b 1
)

echo === Upgrading pip ===
".venv\Scripts\python.exe" -m pip install -U pip

echo === Installing dependencies, may take a few minutes ===
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [X] Dependency install failed.
  exit /b 1
)

echo.
echo [OK] Environment ready. Next steps:
echo   1. Download model:  .venv\Scripts\python.exe scripts\download_model.py
echo   2. Make config:     copy config.example.yaml config.yaml
echo   3. Run:             scripts\run.bat
