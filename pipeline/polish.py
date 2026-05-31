"""润色：把口语化的语音转写整理成通顺规范的书面文字。"""
from __future__ import annotations

from .base import Processor


class PolishProcessor(Processor):
    mode = "polish"
    SYSTEM = (
        "你是中文文字润色助手。把语音转写的口语整理成通顺规范的书面文字："
        "去掉口水词和重复、补全标点、理顺语序、纠正明显的识别错别字。"
        "保持原意和语气，不要扩写或添加内容。"
        "只输出整理后的文字，不要解释、不要引号、不要 markdown。"
    )

    def __init__(self, llm) -> None:
        self._llm = llm

    async def process(self, text: str) -> str:
        if not text.strip():
            return text
        return await self._llm.chat(self.SYSTEM, text)
