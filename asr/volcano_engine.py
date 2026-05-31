"""火山豆包 大模型流式语音识别（双向流式 sauc，WebSocket + 自定义二进制协议）。

每条消息 = 4 字节 header + sequence(4) + payload_size(4) + payload(gzip)。
- full client request：msg_type=0b0001，JSON+gzip，发送配置
- audio only request：msg_type=0b0010，raw+gzip，最后一包用 NEG_WITH_SEQUENCE + 负 seq
- full server response：msg_type=0b1001，解析 gzip(JSON)，文本在 result.text
鉴权走 HTTP header：X-Api-App-Key / X-Api-Access-Key / X-Api-Resource-Id / X-Api-Connect-Id。

⚠️ 协议常量与字段路径据火山官方文档 + 社区 demo 整理（docs/6561/1354869）。
   连接 URL、result 文本路径建议用真实 appid/token 验证；官方另有 Client Demo 可对照。
"""
from __future__ import annotations

import asyncio
import gzip
import json
import struct
import uuid

import websockets

from .base import StreamingASR

# ---- 协议常量 ----
PROTOCOL_VERSION = 0b0001
HEADER_SIZE = 0b0001
FULL_CLIENT_REQUEST = 0b0001
AUDIO_ONLY_REQUEST = 0b0010
FULL_SERVER_RESPONSE = 0b1001
ERROR_RESPONSE = 0b1111
POS_SEQUENCE = 0b0001
NEG_WITH_SEQUENCE = 0b0011
NO_SERIALIZATION = 0b0000
JSON_SERIALIZATION = 0b0001
NO_COMPRESSION = 0b0000
GZIP = 0b0001

VOLCANO_WS_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
RESOURCE_ID = "volc.bigasr.sauc.duration"


def _header(message_type: int, flags: int, serialization: int, compression: int = GZIP) -> bytes:
    return bytes([
        (PROTOCOL_VERSION << 4) | HEADER_SIZE,
        (message_type << 4) | flags,
        (serialization << 4) | compression,
        0x00,
    ])


def _parse(data: bytes) -> dict:
    header_size = data[0] & 0x0F
    msg_type = data[1] >> 4
    flags = data[1] & 0x0F
    serialization = data[2] >> 4
    compression = data[2] & 0x0F
    body = data[header_size * 4:]
    result: dict = {"msg_type": msg_type, "is_last": bool(flags & 0b0010)}
    if msg_type == FULL_SERVER_RESPONSE:
        payload_size = struct.unpack(">I", body[4:8])[0]
        payload = body[8:8 + payload_size]
    elif msg_type == ERROR_RESPONSE:
        result["error_code"] = struct.unpack(">I", body[:4])[0]
        payload_size = struct.unpack(">I", body[4:8])[0]
        payload = body[8:8 + payload_size]
    else:
        return result
    if compression == GZIP and payload:
        try:
            payload = gzip.decompress(payload)
        except Exception:
            pass
    if serialization == JSON_SERIALIZATION and payload:
        try:
            payload = json.loads(payload)
        except Exception:
            pass
    result["payload"] = payload
    return result


def _extract_text(payload) -> str:  # noqa: ANN001
    if not isinstance(payload, dict):
        return ""
    r = payload.get("result")
    if isinstance(r, dict):
        return r.get("text", "") or ""
    if isinstance(r, list) and r and isinstance(r[0], dict):
        return r[0].get("text", "") or ""
    return payload.get("text", "") or ""


class VolcanoASR(StreamingASR):
    def __init__(self, cfg: dict, on_partial=None, on_final=None) -> None:  # noqa: ANN001
        super().__init__(cfg, on_partial, on_final)
        ec = (cfg.get("engines") or {}).get("volcano", {})
        self._app_id = ec.get("app_id", "")
        self._access_token = ec.get("access_token", "")
        self._sample_rate = int(cfg.get("audio", {}).get("samplerate", 16000))
        self._ws = None
        self._recv_task: asyncio.Task | None = None
        self._seq = 0
        self._last_text = ""

    async def start(self) -> None:
        if not self._app_id or not self._access_token:
            raise RuntimeError("火山 app_id/access_token 未配置（config.yaml → engines.volcano）")
        self._seq = 1
        self._last_text = ""
        headers = [
            ("X-Api-App-Key", self._app_id),
            ("X-Api-Access-Key", self._access_token),
            ("X-Api-Resource-Id", RESOURCE_ID),
            ("X-Api-Connect-Id", str(uuid.uuid4())),
        ]
        self._ws = await websockets.connect(VOLCANO_WS_URL, additional_headers=headers)

        config = {
            "user": {"uid": "voice-input-method"},
            "audio": {"format": "pcm", "rate": self._sample_rate, "bits": 16, "channel": 1, "codec": "raw"},
            "request": {"model_name": "bigmodel", "enable_itn": True, "enable_punc": True},
        }
        payload = gzip.compress(json.dumps(config).encode("utf-8"))
        msg = _header(FULL_CLIENT_REQUEST, POS_SEQUENCE, JSON_SERIALIZATION)
        msg += struct.pack(">i", self._seq) + struct.pack(">I", len(payload)) + payload
        await self._ws.send(msg)

        self._recv_task = asyncio.create_task(self._recv_loop())

    async def feed(self, pcm: bytes) -> None:
        if self._ws is None:
            return
        self._seq += 1
        await self._ws.send(self._audio_packet(pcm, self._seq, last=False))

    async def stop(self) -> None:
        if self._ws is not None:
            try:
                self._seq += 1
                await self._ws.send(self._audio_packet(b"", self._seq, last=True))
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
        if self._last_text.strip():
            self.emit_final(self._last_text)

    def _audio_packet(self, pcm: bytes, seq: int, last: bool) -> bytes:
        payload = gzip.compress(pcm)
        flags = NEG_WITH_SEQUENCE if last else POS_SEQUENCE
        seq_val = -seq if last else seq
        msg = _header(AUDIO_ONLY_REQUEST, flags, NO_SERIALIZATION)
        msg += struct.pack(">i", seq_val) + struct.pack(">I", len(payload)) + payload
        return msg

    async def _recv_loop(self) -> None:
        try:
            async for message in self._ws:
                if not isinstance(message, (bytes, bytearray)):
                    continue
                res = _parse(message)
                if res.get("msg_type") == ERROR_RESPONSE:
                    self.emit_partial(f"[火山错误 {res.get('error_code')}]")
                    break
                text = _extract_text(res.get("payload"))
                if text:
                    self._last_text = text
                    self.emit_partial(text)
                if res.get("is_last"):
                    break
        except websockets.ConnectionClosed:
            pass
