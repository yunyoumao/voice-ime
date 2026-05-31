"""ASR 引擎抽象层。

所有识别引擎（云端真流式 / 本地伪流式）都实现 StreamingASR 接口，
桌面端与（将来的）安卓端共享同一套契约，从而做到引擎可插拔。

统一约定
--------
- 音频：16 kHz、单声道、16-bit PCM（小端）字节流。
- 一次"说话"= 一个会话：start() → 多次 feed() → stop()。
- 结果通过两个回调返回：
    on_partial(text)  中间结果，会被后续结果覆盖（用于浮窗实时显示）
    on_final(text)    最终结果，用于上屏
  · 云引擎：feed 过程中持续触发 on_partial，stop() 给出 on_final。
  · 本地 SenseVoice：离线整段识别，靠 VAD 断句，每段直接给 on_final
    （可不触发 on_partial），supports_partial 返回 False。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Optional

PartialCallback = Callable[[str], None]
FinalCallback = Callable[[str], None]


class StreamingASR(ABC):
    """流式语音识别引擎统一接口。"""

    def __init__(
        self,
        cfg: dict,
        on_partial: Optional[PartialCallback] = None,
        on_final: Optional[FinalCallback] = None,
    ) -> None:
        self.cfg = cfg or {}
        self._on_partial = on_partial or (lambda text: None)
        self._on_final = on_final or (lambda text: None)

    # ---------------- 生命周期 ----------------
    @abstractmethod
    async def start(self) -> None:
        """开始一次识别会话：建立连接 / 重置内部状态。"""

    @abstractmethod
    async def feed(self, pcm: bytes) -> None:
        """送入一段 16k / mono / PCM16 音频。"""

    @abstractmethod
    async def stop(self) -> None:
        """结束本次会话，刷出最终结果（触发 on_final）。"""

    async def close(self) -> None:
        """释放长期资源（连接 / 模型）。默认无操作，子类按需覆盖。"""
        return None

    # ------------- 供子类调用的回调封装 -------------
    def emit_partial(self, text: str) -> None:
        if text:
            self._on_partial(text)

    def emit_final(self, text: str) -> None:
        text = (text or "").strip()
        if text:
            self._on_final(text)

    # 引擎是否支持逐字中间结果（UI 据此决定浮窗是否实时刷新）
    @property
    def supports_partial(self) -> bool:
        return True
