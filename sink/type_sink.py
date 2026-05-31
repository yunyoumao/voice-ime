"""上屏 Sink：把文字粘贴到当前光标处（复用 desktop/output.py）。"""
from __future__ import annotations

import asyncio

from .base import Sink


class TypeSink(Sink):
    name = "type"

    def __init__(self, output_controller) -> None:
        self._out = output_controller

    async def emit(self, result) -> None:
        if result.text:
            await asyncio.to_thread(self._out.put, result.text)
