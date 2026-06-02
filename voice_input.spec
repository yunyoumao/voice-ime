# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（onedir 单 exe；带 --settings 复用自身跑设置窗）。
模型不打进来(首启下载)。构建： .venv/Scripts/pyinstaller voice_input.spec --noconfirm
产物： dist/VoiceInput/VoiceInput.exe
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
    # 引擎/管线/上屏 是按 config 动态导入的，PyInstaller 静态扫不到 → 显式声明
    "asr.local_sensevoice", "asr.soniox_engine", "asr.aliyun_engine", "asr.volcano_engine",
    "pipeline.polish", "pipeline.summarize", "pipeline.translate", "pipeline.passthrough", "pipeline.prompts",
    "sink.type_sink",
    "desktop.settings", "desktop.tray", "desktop.download_prompt", "scripts.download_model",
    # 阶段2/3 新增：均为函数内懒加载(main._record / settings 各方法)，静态扫不到 → 显式声明
    "desktop.history", "desktop.stats", "desktop.user_dict", "desktop.autostart",
]
hiddenimports += collect_submodules("sherpa_onnx")
hiddenimports += collect_submodules("webview")     # pywebview 后端(winforms/edgechromium)

a = Analysis(
    ["desktop/main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter.test", "test"],
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
    upx=False,               # 关 UPX：压缩后更易被杀软误报
    console=False,           # 隐藏黑窗(GUI 应用)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico',
    version='version_info.txt',   # exe 版本/公司/产品元数据：填上(非空)可降杀软误报
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False,
    name="VoiceInput",
)
