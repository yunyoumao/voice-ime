#!/usr/bin/env bash
# 下载本地引擎所需模型：sherpa-onnx SenseVoice（中英日韩粤）+ Silero VAD
# 用法： bash scripts/download_sensevoice.sh
set -e
cd "$(dirname "$0")/.."
mkdir -p models
cd models

BASE="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"
SV="sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09"

if [ ! -d "$SV" ]; then
  echo "==> 下载 SenseVoice 模型（约 230MB）"
  curl -L -O "${BASE}/${SV}.tar.bz2"
  tar xvf "${SV}.tar.bz2"
  rm -f "${SV}.tar.bz2"
else
  echo "✓ SenseVoice 模型已存在"
fi

if [ ! -f "silero_vad.onnx" ]; then
  echo "==> 下载 Silero VAD"
  curl -L -O "${BASE}/silero_vad.onnx"
else
  echo "✓ Silero VAD 已存在"
fi

echo ""
echo "✓ 模型就绪："
ls -la
