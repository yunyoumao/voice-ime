"""阿里百炼 qwen3-asr-flash-realtime 实时语音识别（DashScope SDK）。

用 OmniRealtimeConversation（注意不是 Recognition）。SDK 以回调方式返回结果：
- 中间结果：event 'conversation.item.input_audio_transcription.text' → response['stash']
- 最终结果：event 'conversation.item.input_audio_transcription.completed' → response['transcript']
音频以 base64 字符串经 append_audio 发送。需 dashscope SDK ≥ 1.25.6。

回调在 SDK 内部线程触发，这里直接 emit；阶段 3 接 GUI 时需改为 loop.call_soon_threadsafe。
参考：https://help.aliyun.com/zh/model-studio/qwen-asr-realtime-python-sdk
"""
from __future__ import annotations

import asyncio
import base64

from .base import StreamingASR


class AliyunASR(StreamingASR):
    def __init__(self, cfg: dict, on_partial=None, on_final=None) -> None:  # noqa: ANN001
        super().__init__(cfg, on_partial, on_final)
        ec = (cfg.get("engines") or {}).get("aliyun", {})
        self._api_key = ec.get("api_key", "")
        self._model = ec.get("model", "qwen3-asr-flash-realtime")
        region = ec.get("region", "beijing")
        self._url = (
            "wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime"
            if region == "singapore"
            else "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
        )
        hints = ec.get("language_hints") or ["zh"]
        self._language = hints[0] if hints else "zh"
        self._sample_rate = int(cfg.get("audio", {}).get("samplerate", 16000))
        self._conversation = None

    @property
    def supports_partial(self) -> bool:
        return True

    async def start(self) -> None:
        from dashscope.audio.qwen_omni import (
            AudioFormat,
            MultiModality,
            OmniRealtimeCallback,
            OmniRealtimeConversation,
        )
        from dashscope.audio.qwen_omni.omni_realtime import TranscriptionParams

        if not self._api_key:
            raise RuntimeError("阿里 api_key 未配置（config.yaml → engines.aliyun.api_key）")

        engine = self

        class _Callback(OmniRealtimeCallback):
            def on_open(self) -> None:
                pass

            def on_close(self, code, msg) -> None:  # noqa: ANN001
                pass

            def on_event(self, response) -> None:  # noqa: ANN001
                try:
                    etype = response.get("type")
                except AttributeError:
                    return
                if etype == "conversation.item.input_audio_transcription.text":
                    engine.emit_partial(response.get("stash") or "")
                elif etype == "conversation.item.input_audio_transcription.completed":
                    engine.emit_final(response.get("transcript") or "")

        self._conversation = OmniRealtimeConversation(
            model=self._model,
            url=self._url,
            callback=_Callback(),
            api_key=self._api_key,
        )
        self._conversation.connect()
        self._conversation.update_session(
            output_modalities=[MultiModality.TEXT],
            input_audio_format=AudioFormat.PCM_16000HZ_MONO_16BIT,
            enable_input_audio_transcription=True,
            enable_turn_detection=True,
            turn_detection_type="server_vad",
            turn_detection_silence_duration_ms=400,
            transcription_params=TranscriptionParams(
                language=self._language,
                sample_rate=self._sample_rate,
                input_audio_format="pcm",
            ),
        )

    async def feed(self, pcm: bytes) -> None:
        if self._conversation is not None:
            self._conversation.append_audio(base64.b64encode(pcm).decode("ascii"))

    async def stop(self) -> None:
        conv = self._conversation
        self._conversation = None
        if conv is not None:
            await asyncio.to_thread(self._finish, conv)

    @staticmethod
    def _finish(conv) -> None:  # noqa: ANN001
        try:
            conv.end_session(timeout=20)
        except Exception:
            pass
        try:
            conv.close()
        except Exception:
            pass
