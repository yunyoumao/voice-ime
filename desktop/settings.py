"""独立设置窗口（pywebview，苹果玻璃风）。

主程序经托盘/热键 subprocess 拉起它——pywebview.start() 要占主线程，与主程序的
asyncio+tkinter 主循环冲突，独立子进程彻底绕开。读写 config.yaml；保存后主程序需重启生效。

运行： python -m desktop.settings
"""
from __future__ import annotations

import os
import sys
import threading

import yaml

# 兼容 `python desktop/settings.py` 直跑：把项目根加进 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from desktop.config import get_model_base, load_config, save_config  # noqa: E402

HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings_ui.html")


def _strip(cfg: dict) -> dict:
    """去掉 _* 内部字段，供 JSON 序列化给 JS。"""
    return {k: v for k, v in (cfg or {}).items() if not k.startswith("_")}


def _deep_merge(base: dict, upd: dict) -> dict:
    """把 upd 深合并进 base（嵌套 dict 合并而非整体替换），返回 base。"""
    for k, v in (upd or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


class SettingsAPI:
    """pywebview js_api：JS 调 window.pywebview.api.<方法>()。"""

    def get_config(self):
        return _strip(load_config())

    def get_default_config(self):
        root = load_config().get("_root", ".")
        with open(os.path.join(root, "config.example.yaml"), "r", encoding="utf-8") as f:
            return _strip(yaml.safe_load(f) or {})

    def save_config(self, new_cfg):
        cfg = load_config()                 # 当前配置(含其他未在界面里的字段)
        _deep_merge(cfg, new_cfg or {})     # 只覆盖界面改的，保留 audio/remote/mouse_menu/sinks 等
        save_config(cfg)                    # save_config 会剔除 _* 内部字段
        return True

    def test_engine(self, name):
        ec = (load_config().get("engines") or {}).get(name, {})
        if name == "local":
            return "本地引擎：模型缺失会在启动时自动下载"
        if name in ("soniox", "aliyun"):
            return "✓ API Key 已填" if ec.get("api_key") else "✗ 缺 API Key"
        if name == "volcano":
            return "✓ 凭证已填" if (ec.get("app_id") and ec.get("access_token")) else "✗ 缺 App ID / Access Token"
        return "未知引擎"

    def download_models(self):
        from scripts.download_model import main as dl
        base = get_model_base(load_config())
        threading.Thread(target=lambda: dl(os.path.join(base, "models")), daemon=True).start()
        return "已在后台开始下载，完成后重启生效"


def main():
    import webview
    api = SettingsAPI()
    webview.create_window("语音输入法 · 设置", HTML, js_api=api,
                          width=560, height=780, background_color="#15161e")
    webview.start()


if __name__ == "__main__":
    main()
