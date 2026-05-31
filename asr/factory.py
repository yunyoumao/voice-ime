"""按配置创建识别引擎实例。

各引擎模块延迟导入：只在选中某引擎时才 import 它，避免因未安装的可选
依赖（如某云 SDK）影响其他引擎使用。
"""
from __future__ import annotations

from typing import Callable, Optional

from .base import StreamingASR


def create_engine(
    cfg: dict,
    on_partial: Optional[Callable[[str], None]] = None,
    on_final: Optional[Callable[[str], None]] = None,
) -> StreamingASR:
    name = (cfg.get("engine") or "local").lower()

    if name == "local":
        from .local_sensevoice import LocalSenseVoiceASR
        return LocalSenseVoiceASR(cfg, on_partial, on_final)
    if name == "soniox":
        from .soniox_engine import SonioxASR
        return SonioxASR(cfg, on_partial, on_final)
    if name == "aliyun":
        from .aliyun_engine import AliyunASR
        return AliyunASR(cfg, on_partial, on_final)
    if name == "volcano":
        from .volcano_engine import VolcanoASR
        return VolcanoASR(cfg, on_partial, on_final)

    raise ValueError(f"未知引擎: {name!r}（可选 local | soniox | aliyun | volcano）")
