@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
REM 麦克风自检：看哪个输入设备有信号（远程桌面排查 / 选对麦）
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo [X] .venv\Scripts\python.exe not found. Run scripts\setup_env.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\mic_check.py
echo.
pause
