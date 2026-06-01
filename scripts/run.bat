@echo off
chcp 65001 >nul
REM 一键运行语音输入法（Windows）。自动定位项目根、用 .venv 的 Python 运行。
REM   scripts\run.bat         启动输入法
REM   scripts\run.bat probe   探测键名（按一下键看该填什么热键）
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo [X] 没找到 .venv\Scripts\python.exe
  echo     请先运行： scripts\setup_env.bat
  exit /b 1
)
if /i "%~1"=="probe" (
  ".venv\Scripts\python.exe" scripts\probe_key.py
) else (
  ".venv\Scripts\python.exe" -m desktop.main
)
