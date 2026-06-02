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

from desktop.config import ROOT, get_model_base, load_config, save_config  # noqa: E402

HTML = os.path.join(ROOT, "desktop", "settings_ui.html")   # dev=项目根 / 打包=_MEIPASS，均含 desktop/


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

    # ---- 阶段1 新增：麦克风枚举 / 开机自启 / 打开数据目录 ----
    def list_input_devices(self):
        """枚举可用输入设备 [{index, name}]，供麦克风下拉（按名字去重）。"""
        try:
            import sounddevice as sd
        except Exception:
            return []
        out, seen = [], set()
        try:
            for i, d in enumerate(sd.query_devices()):
                if (d.get("max_input_channels") or 0) <= 0:
                    continue
                name = (d.get("name") or f"设备 {i}").strip()
                if name in seen:
                    continue
                seen.add(name)
                out.append({"index": i, "name": name})
        except Exception:
            return []
        return out

    def set_autostart(self, enabled):
        from desktop.autostart import set_autostart as _set
        return _set(bool(enabled))

    def is_autostart_enabled(self):
        from desktop.autostart import is_enabled
        return is_enabled()

    def open_data_dir(self):
        """在文件管理器里打开用户数据目录（%APPDATA%\\VoiceInput）。"""
        from desktop.config import get_user_data_dir
        d = get_user_data_dir()
        try:
            os.makedirs(d, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(d)                      # type: ignore[attr-defined]
            else:
                import subprocess
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", d])
            return True
        except Exception:
            return False

    # ---- 阶段2 新增：用户词典读写 ----
    def get_dict_terms(self):
        from desktop.user_dict import get_terms
        return get_terms()

    def save_dict_terms(self, terms):
        from desktop.user_dict import save_terms
        return save_terms(terms)

    # ---- 阶段3 新增：历史 / 统计 ----
    def get_history(self, page=0, limit=20):
        from desktop import history
        return history.read(page, limit)            # read() 内部已做 int/边界归一

    def get_stats(self):
        from desktop import stats
        return stats.load()

    def clear_history(self):
        from desktop import history
        return history.clear()


def main():
    import webview
    api = SettingsAPI()
    webview.create_window("语音输入法 · 设置", HTML, js_api=api,
                          width=960, height=640, background_color="#0d0f13")
    webview.start()


if __name__ == "__main__":
    main()
