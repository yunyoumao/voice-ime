"""Soniox 实时语音识别（WebSocket，逐字流式）。

协议：连接 wss://stt-rt.soniox.com/transcribe-websocket，首帧发 JSON 配置，
其后直接发送 raw PCM 二进制帧；服务端持续返回带 is_final 标志的 token 流；
发送空帧 b'' 结束，服务端回 finished:true 后关闭。

Soniox 单模型自动多语言混合（中英日句中切换免指定），延迟 <200ms。
参考：https://soniox.com/docs/stt/api-reference/websocket-api
"""
from __future__ import annotations

import asyncio
import json

import websockets

from .base import StreamingASR

SONIOX_WS_URL = "wss://stt-rt.soniox.com/transcribe-websocket"


class SonioxASR(StreamingASR):
    def __init__(self, cfg: dict, on_partial=None, on_final=None) -> None:  # noqa: ANN001
        super().__init__(cfg, on_partial, on_final)
        ec = (cfg.get("engines") or {}).get("soniox", {})
        self._api_key = ec.get("api_key", "")
        self._model = ec.get("model", "stt-rt-preview")
        self._language_hints = ec.get("language_hints")  # 可选；不填则自动
        self._sample_rate = int(cfg.get("audio", {}).get("samplerate", 16000))
        self._ws = None
        self._recv_task: asyncio.Task | None = None
        self._final_parts: list[str] = []

    async def start(self) -> None:
        if not self._api_key:
            raise RuntimeError("Soniox api_key 未配置（config.yaml → engines.soniox.api_key）")
        self._final_parts = []
        self._ws = await websockets.connect(SONIOX_WS_URL)
        config = {
            "api_key": self._api_key,
            "model": self._model,
            "audio_format": "s16le",
            "sample_rate": self._sample_rate,
            "num_channels": 1,
        }
        if self._language_hints:
            config["language_hints"] = self._language_hints
        await self._ws.send(json.dumps(config))
        self._recv_task = asyncio.create_task(self._recv_loop())

    async def feed(self, pcm: bytes) -> None:
        if self._ws is not None:
            await self._ws.send(pcm)

    async def stop(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.send(b"")  # 空帧 = 结束流
            except Exception:
                pass
        if self._recv_task is not None:
            try:
                await asyncio.wait_for(self._recv_task, timeout=10)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._recv_task.cancel()
            self._recv_task = None
        if self._ws is not None:
            try:
                await self._ws.close()
            finally:
                self._ws = None
        final = "".join(self._final_parts).strip()
        if final:
            self.emit_final(final)

    async def _recv_loop(self) -> None:
        try:
            async for message in self._ws:
                res = json.loads(message)
                if res.get("error_code") is not None:
                    self.emit_partial(f"[Soniox错误 {res['error_code']}: {res.get('error_message','')}]")
                    break
                non_final: list[str] = []
                for tok in res.get("tokens", []):
                    text = tok.get("text", "")
                    if tok.get("is_final"):
                        self._final_parts.append(text)
                    else:
                        non_final.append(text)
                preview = "".join(self._final_parts) + "".join(non_final)
                if preview:
                    self.emit_partial(preview)
                if res.get("finished"):
                    break
        except websockets.ConnectionClosed:
            pass
