#!/usr/bin/env bash
# 搭建隔离的 Python 3.12 环境并安装依赖。
# 用法： bash scripts/setup_env.sh
set -e
cd "$(dirname "$0")/.."

PREFIX=$(brew --prefix python@3.12 2>/dev/null)
PY="$PREFIX/bin/python3.12"
if [ -z "$PREFIX" ] || [ ! -x "$PY" ]; then
  echo "✗ 未找到 python@3.12。请先运行： brew install python@3.12"
  exit 1
fi
echo "==> 使用 $PY"

echo "==> 创建虚拟环境 .venv（Python 3.12）"
"$PY" -m venv .venv

echo "==> 升级 pip"
.venv/bin/python -m pip install --upgrade pip

echo "==> 安装依赖（requirements.txt）"
.venv/bin/pip install -r requirements.txt

echo ""
echo "✓ 环境就绪。激活方式： source .venv/bin/activate"
echo "  下载本地模型： bash scripts/download_sensevoice.sh"
