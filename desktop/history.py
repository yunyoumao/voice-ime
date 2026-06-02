"""输入历史：每次出结果追加一行到 用户数据目录/history.jsonl。

后台主程序 append()，设置窗 read()/clear()。JSONL 逐行追加、单写者，无需锁。
失败一律静默——历史记录绝不能影响主链路（识别→上屏）。
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from desktop.config import get_user_data_dir

HISTORY_FILE = "history.jsonl"


def _path() -> str:
    return os.path.join(get_user_data_dir(), HISTORY_FILE)


def append(text: str, result: str, mode: str, secs: float) -> None:
    """追加一条历史（含本地时间戳）。"""
    rec = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "secs": round(float(secs), 2),
        "chars": len(result or ""),
        "text": text,
        "result": result,
    }
    try:
        os.makedirs(get_user_data_dir(), exist_ok=True)
        with open(_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def read(page: int = 0, limit: int = 20) -> dict:
    """倒序分页读（最新在前）。返回 {items, total, page, pages}。"""
    try:
        with open(_path(), encoding="utf-8") as f:
            lines = [ln for ln in f if ln.strip()]
    except (FileNotFoundError, OSError):
        lines = []
    recs = []
    for ln in lines:
        try:
            recs.append(json.loads(ln))
        except ValueError:
            pass
    recs.reverse()
    total = len(recs)
    page = max(0, int(page))
    limit = max(1, int(limit))
    start = page * limit
    return {
        "items": recs[start:start + limit],
        "total": total,
        "page": page,
        "pages": max(1, (total + limit - 1) // limit),
    }


def clear() -> int:
    """清空历史，返回删除条数。"""
    try:
        with open(_path(), encoding="utf-8") as f:
            n = sum(1 for ln in f if ln.strip())
    except (FileNotFoundError, OSError):
        return 0
    try:
        os.remove(_path())
    except OSError:
        pass
    return n
