"""使用统计：累计 总次数 / 总录音秒数 / 总字数，存 用户数据目录/stats.json。

后台主程序 bump()，设置窗 load()。原子写（临时文件 + os.replace）。单写者无需锁。
失败一律静默——不影响主链路。
"""
from __future__ import annotations

import json
import os

from desktop.config import get_user_data_dir

STATS_FILE = "stats.json"


def _path() -> str:
    return os.path.join(get_user_data_dir(), STATS_FILE)


def _read_raw() -> dict:
    try:
        with open(_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def bump(secs: float, chars: int) -> None:
    """累加一次输入。"""
    d = _read_raw()
    d["count"] = int(d.get("count", 0)) + 1
    d["total_secs"] = round(float(d.get("total_secs", 0.0)) + max(0.0, float(secs)), 2)
    d["total_chars"] = int(d.get("total_chars", 0)) + max(0, int(chars))
    try:
        os.makedirs(get_user_data_dir(), exist_ok=True)
        tmp = _path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, _path())
    except OSError:
        pass


def load() -> dict:
    """读统计 + 计算平均语速（字/分）。"""
    d = _read_raw()
    count = int(d.get("count", 0))
    total_secs = float(d.get("total_secs", 0.0))
    total_chars = int(d.get("total_chars", 0))
    cpm = round(total_chars / (total_secs / 60), 1) if total_secs >= 1 else 0.0
    return {"count": count, "total_secs": round(total_secs, 1),
            "total_chars": total_chars, "avg_cpm": cpm}


def reset() -> bool:
    """清零统计。"""
    try:
        if os.path.exists(_path()):
            os.remove(_path())
        return True
    except OSError:
        return False
