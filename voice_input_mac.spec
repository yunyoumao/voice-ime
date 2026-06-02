# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（macOS，不签名 .app）。

模型不打进来(首启下载到 ~/Library/Application Support/VoiceInput)。
构建： scripts/build_mac.sh   （先生成 assets/icon.icns 再调本 spec）
或直接： .venv/bin/pyinstaller voice_input_mac.spec --noconfirm
产物： dist/VoiceInput.app
"""
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

datas = [
    ("config.example.yaml", "."),
    ("desktop/settings_ui.html", "desktop"),
    ("assets", "assets"),
]
binaries = []
for pkg in ("sherpa_onnx", "sounddevice", "webview"):
    datas += collect_data_files(pkg)
    binaries += collect_dynamic_libs(pkg)

hiddenimports = [
    # 引擎/管线/上屏 按 config 动态导入，PyInstaller 静态扫不到 → 显式声明
    "asr.local_sensevoice", "asr.soniox_engine", "asr.aliyun_engine", "asr.volcano_engine",
    "pipeline.polish", "pipeline.summarize", "pipeline.translate", "pipeline.passthrough", "pipeline.prompts",
    "sink.type_sink",
    "desktop.settings", "desktop.tray", "desktop.download_prompt", "scripts.download_model",
    "desktop.history", "desktop.stats", "desktop.user_dict", "desktop.autostart",
    "desktop.mac_radial",            # ★macOS 原生转盘/浮窗(平台分流 import，静态扫不到)
]
hiddenimports += collect_submodules("sherpa_onnx")
hiddenimports += collect_submodules("webview")             # pywebview 后端(cocoa/WKWebView)
for _fw in ("objc", "Foundation", "AppKit", "Quartz", "WebKit"):   # ★pyobjc framework(转盘+设置窗依赖)
    hiddenimports += collect_submodules(_fw)

a = Analysis(
    ["desktop/main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter.test", "test"],   # 保留 tkinter 主体(download_prompt 下载窗用)，仅排测试
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="VoiceInput",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,           # GUI 应用：无终端(输出走日志文件，见 main._open_log_sink)
    disable_windowed_traceback=False,
    target_arch="arm64",     # Apple Silicon；如需兼容 Intel 改 "universal2"(依赖需有 universal wheel)
    codesign_identity=None,  # 不签名
    entitlements_file=None,
    icon="assets/icon.icns",
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False,
    name="VoiceInput",
)
app = BUNDLE(
    coll,
    name="VoiceInput.app",
    icon="assets/icon.icns",
    bundle_identifier="com.yunyoumao.voiceinput",
    info_plist={
        "NSMicrophoneUsageDescription": "语音识别需要使用麦克风录音。",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "LSUIElement": True,             # 后台工具(托盘+转盘常驻)，不在 Dock 显示
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        "CFBundleName": "VoiceInput",
        "CFBundleDisplayName": "语音输入法",
    },
)
