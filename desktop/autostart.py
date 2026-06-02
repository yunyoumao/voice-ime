"""Windows 开机自启：写 HKCU\\...\\Run 注册表项。非 Windows 平台 no-op。

- 打包 exe：登记 exe 自身路径（sys.executable）。
- 开发态：登记 `python -m desktop.main`（带项目根 cwd），主要供调试。
设置界面经 SettingsAPI 调 set_autostart()/is_enabled()。
"""
from __future__ import annotations

import os
import sys

APP_NAME = "VoiceInput"
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _command() -> str:
    """开机要执行的命令行字符串。"""
    if getattr(sys, "frozen", False):                 # 打包 exe：它自己
        return f'"{sys.executable}"'
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 项目根
    return f'cmd /c cd /d "{root}" && "{sys.executable}" -m desktop.main'


def set_autostart(enabled: bool) -> bool:
    """开/关开机自启。成功返回 True；非 Windows 或失败返回 False。"""
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _command())
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass                              # 本来就没登记，忽略
        return True
    except OSError:
        return False


def is_enabled() -> bool:
    """当前是否已登记开机自启。"""
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_QUERY_VALUE) as key:
            winreg.QueryValueEx(key, APP_NAME)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False
