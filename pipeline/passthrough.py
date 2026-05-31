"""直通：原样返回，不做任何 AI 处理（写代码/聊天要原话时用）。"""
from __future__ import annotations

from .base import Processor


class PassthroughProcessor(Processor):
    mode = "raw"

    async def process(self, text: str) -> str:
        return text
