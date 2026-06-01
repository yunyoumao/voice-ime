"""配置加载与保存（跨平台）。

开发态优先读项目根 config.yaml；打包态读用户数据目录(可写)的 config.yaml，
首次从 config.example.yaml 播种。注入下列内部字段供各模块用：
  _root         项目根/打包资源根
  _config_path  当前配置文件路径
  _user_data_dir 用户可写数据目录
  _model_base   模型基目录(其下含 models/…)：dev=项目根 / 打包=用户数据目录
"""
from __future__ import annotations

import os
import shutil
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_user_data_dir() -> str:
    """用户可写数据目录（打包后配置/模型存这里，Program Files 不可写）。"""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "VoiceInput")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/VoiceInput")
    return os.path.expanduser("~/.config/voice-input")


def get_model_base(cfg: dict) -> str:
    """模型基目录(其下含 models/…)。由 load_config 注入 _model_base；缺省回退项目根。
    各处(local 引擎、首启下载窗)统一用它解析，避免各算各的。"""
    return cfg.get("_model_base") or cfg.get("_root", ".")


def load_config(path: str | None = None) -> dict:
    """加载配置。优先级：指定 path > 项目根 config.yaml(dev) > 用户目录 config.yaml(打包，首启播种)。"""
    user_data = get_user_data_dir()
    if path is None:
        dev = os.path.join(ROOT, "config.yaml")
        if os.path.exists(dev):                       # 开发态：项目根 config.yaml 优先
            path = dev
        else:                                         # 打包态：用户可写目录(首启从示例播种)
            path = os.path.join(user_data, "config.yaml")
            if not os.path.exists(path):
                os.makedirs(user_data, exist_ok=True)
                example = os.path.join(ROOT, "config.example.yaml")
                if os.path.exists(example):
                    shutil.copy(example, path)
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg["_root"] = ROOT
    cfg["_config_path"] = path
    cfg["_user_data_dir"] = user_data
    # 模型基目录：仓库有 models/ → 项目根(dev)；否则用户目录。
    # 打包(frozen)态 ROOT=只读资源根、不含 models/ → 检查失败自动落到用户目录(首启下载到这)。
    cfg["_model_base"] = ROOT if os.path.isdir(os.path.join(ROOT, "models")) else user_data
    return cfg


def save_config(cfg: dict, path: str | None = None) -> None:
    """保存配置到 config.yaml（剔除 _* 内部字段，UTF-8 + 保留中文 + 不排序键）。"""
    path = path or cfg.get("_config_path")
    if not path:
        raise ValueError("save_config: 缺少保存路径（提供 path 或确保 cfg 含 _config_path）")
    safe = {k: v for k, v in cfg.items() if not k.startswith("_")}
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(safe, f, allow_unicode=True, sort_keys=False)
