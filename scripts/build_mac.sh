#!/usr/bin/env bash
# macOS 打包(不签名)。用法：
#   bash scripts/build_mac.sh          # 只打 .app
#   bash scripts/build_mac.sh --dmg    # 额外打 .dmg 便于分发
# 产物：dist/VoiceInput.app（首启自动下载模型到 ~/Library/Application Support/VoiceInput）
set -euo pipefail
cd "$(dirname "$0")/.."                      # → 项目根
ROOT="$(pwd)"
PYI="$ROOT/.venv/bin/pyinstaller"

if [ ! -x "$PYI" ]; then
  echo "✗ 找不到 $PYI"
  echo "  先装：.venv/bin/pip install pyinstaller"
  exit 1
fi

echo "==> 1/4 生成 .icns 图标（从 assets/icon.png）"
SRC="assets/icon.png"
ICONSET="assets/icon.iconset"
rm -rf "$ICONSET"; mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z "$s" "$s"             "$SRC" --out "$ICONSET/icon_${s}x${s}.png"     >/dev/null
  sips -z $((s * 2)) $((s * 2)) "$SRC" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o assets/icon.icns
rm -rf "$ICONSET"
echo "    ✓ assets/icon.icns"

echo "==> 2/4 PyInstaller 构建（首次较慢：pyobjc/sherpa-onnx 体积大）"
"$PYI" voice_input_mac.spec --noconfirm

echo "==> 3/4 去隔离（让自己能直接 open，不被 Gatekeeper 拦）"
xattr -cr dist/VoiceInput.app || true

echo "==> 4/4 可选打 DMG"
if [ "${1:-}" = "--dmg" ]; then
  rm -f dist/VoiceInput.dmg
  hdiutil create -volname "VoiceInput" -srcfolder dist/VoiceInput.app \
    -ov -format UDZO dist/VoiceInput.dmg >/dev/null
  echo "    ✓ dist/VoiceInput.dmg"
fi

echo ""
echo "✓ 完成：dist/VoiceInput.app"
echo "  自测：open dist/VoiceInput.app"
echo "  首启会下载模型(~520MB) 到 ~/Library/Application Support/VoiceInput/"
echo "  发给别人：连同 docs/Mac安装.md（教绕 Gatekeeper + 授权三项）"
