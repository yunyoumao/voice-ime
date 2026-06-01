@echo off
chcp 65001 >nul
REM 安装语音输入法运行环境（Windows）。需先装好 Python 3.12（python.org，安装时勾 Add to PATH）。
cd /d "%~dp0.."
echo === 创建 .venv（Python 3.12）===
py -3.12 -m venv .venv
if errorlevel 1 (
  echo [!] py -3.12 失败，尝试默认 python …
  python -m venv .venv || ( echo [X] 建 venv 失败，请确认已装 Python 3.12 ^&^& exit /b 1 )
)
echo === 升级 pip ===
".venv\Scripts\python.exe" -m pip install -U pip
echo === 安装依赖（可能要几分钟）===
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 ( echo [X] 依赖安装失败 ^&^& exit /b 1 )
echo.
echo [OK] 环境装好了。接下来：
echo   1) 下模型：  .venv\Scripts\python.exe scripts\download_model.py
echo   2) 配置：    copy config.example.yaml config.yaml   然后按需编辑
echo   3) 运行：    scripts\run.bat
