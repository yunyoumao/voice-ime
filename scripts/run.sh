#!/usr/bin/env bash
# 一键运行语音输入法：自动定位项目目录、用项目 .venv(Python 3.12) 运行，
# 无需手动 cd / source activate。
#   bash scripts/run.sh          启动输入法
#   bash scripts/run.sh probe    探测键名（按一下键看该填什么热键）
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"
if [ ! -x ".venv/bin/python" ]; then
  echo "❌ 未找到 .venv/bin/python —— 请先在项目目录运行 scripts/setup_env.sh"
  exit 1
fi
case "${1:-run}" in
  probe) exec .venv/bin/python scripts/probe_key.py ;;
  *)     exec .venv/bin/python -m desktop.main ;;
esac
