"""输出层抽象：把 Result 落地（上屏 / 写文件 / 剪贴板 / 触发动作）。"""
from __future__ import annotations

from abc import ABC, abstractmethod


class Sink(ABC):
    name = "base"

    @abstractmethod
    async def emit(self, result) -> None:
        ...
