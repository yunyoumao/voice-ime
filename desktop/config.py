"""配置加载。

优先读取项目根目录的 config.yaml；不存在则回退到 config.example.yaml
（默认 engine: local，方便开箱即用）。注入 _root 供各模块拼接相对路径。
"""
from __future__ import annotations

import os
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config(path: str | None = None) -> dict:
    if path is None:
        user = os.path.join(ROOT, "config.yaml")
        path = user if os.path.exists(user) else os.path.join(ROOT, "config.example.yaml")
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg["_root"] = ROOT
    cfg["_config_path"] = path
    return cfg
