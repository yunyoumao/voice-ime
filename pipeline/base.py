"""处理层核心：Result 数据结构、Processor 抽象、Pipeline 调度。

数据流：识别得到的原始文字 → Router 判定模式 → 对应 Processor 处理
→ 产出 Result（成品文字 + 模式 + 输出去向）。Sink 负责把 Result 落地。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Result:
    text: str
    mode: str = "raw"
    sink: str = "type"
    title: Optional[str] = None      # 供 file sink 命名
    meta: dict = field(default_factory=dict)


class Processor(ABC):
    """把原始文字加工成成品文字。"""
    mode: str = "raw"

    @abstractmethod
    async def process(self, text: str) -> str:
        ...


class Pipeline:
    def __init__(self, router, processors: dict, mode_to_sink: dict, default_mode: str) -> None:
        self._router = router
        self._processors = processors
        self._mode_to_sink = mode_to_sink
        self._default_mode = default_mode if default_mode in processors else "raw"

    async def run(self, raw_text: str, force_mode: str | None = None) -> Result:
        # force_mode（鼠标手势选定的模式）命中则跳过前缀路由，直接用它处理原文；
        # 默认 None → 维持前缀词路由（热键/口述路径不受影响）。
        if force_mode is not None and force_mode in self._processors:
            mode, text = force_mode, raw_text
        else:
            mode, text = self._router.route(raw_text)
        processor = self._processors.get(mode)
        if processor is None:
            # 路由到尚未实现的模式 → 回退默认模式，处理原始整句
            mode = self._default_mode
            text = raw_text
            processor = self._processors.get(mode)
        if processor is None:
            return Result(text=raw_text, mode="raw", sink="type")
        out = await processor.process(text)
        sink = self._mode_to_sink.get(mode, "type")
        return Result(text=out, mode=mode, sink=sink)
