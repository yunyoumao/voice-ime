"""总结：把口述内容整理成简洁要点/小结。

起步上屏（type sink）；后续可接 FileSink 写 ~/VoiceNotes/时间戳.md（见蓝图阶段B）。
"""
from __future__ import annotations

from .base import Processor


class SummarizeProcessor(Processor):
    mode = "summary"
    SYSTEM = (
        "你是中文摘要助手。把用户口述的内容整理成简洁清晰的要点小结："
        "提炼关键信息、合并重复、按逻辑顺序组织，必要时用短横线列点。"
        "保持原意，不要扩写或编造。只输出整理后的内容，不要解释、不要前后缀。"
    )

    def __init__(self, llm) -> None:
        self._llm = llm

    async def process(self, text: str) -> str:
        if not text.strip():
            return text
        return await self._llm.chat(self.SYSTEM, text)
