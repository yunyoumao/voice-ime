"""翻译：把语音转写翻译成目标语言。

译中 / 译日 / 译英共用一个类，按 target 区分；走 LLM。
build_pipeline 里实例化 translate_zh / translate_ja / translate_en 三个模式。
"""
from __future__ import annotations

from .base import Processor


class TranslateProcessor(Processor):
    def __init__(self, llm, mode: str, target_name: str) -> None:
        self._llm = llm
        self.mode = mode
        self.SYSTEM = (
            f"你是专业翻译助手。把用户输入的全部内容翻译成{target_name}，"
            f"只输出{target_name}译文，不要原文、不要解释、不要引号、不要 markdown，"
            f"保持原意和语气。"
        )

    async def process(self, text: str) -> str:
        if not text.strip():
            return text
        return await self._llm.chat(self.SYSTEM, text)
