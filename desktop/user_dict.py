"""用户词典读写（user_dict.json，存用户数据目录）。

设置界面经 SettingsAPI 增删；润色阶段（pipeline/prompts.load_user_terms）读它注入提示词。
读逻辑复用 pipeline.prompts.load_user_terms（单一来源），这里只补「整表保存」。
"""
from __future__ import annotations

import json
import os

from desktop.config import get_user_data_dir
from pipeline.prompts import USER_DICT_FILE, load_user_terms


def get_terms() -> list:
    return load_user_terms(get_user_data_dir())


def save_terms(terms) -> bool:
    """整表覆盖保存（去空白/去重，原子写）。成功返回 True。"""
    clean, seen = [], set()
    for t in terms or []:
        t = str(t).strip()
        if t and t not in seen:
            seen.add(t)
            clean.append(t)
    try:
        base = get_user_data_dir()
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, USER_DICT_FILE)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"terms": clean}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        return False
