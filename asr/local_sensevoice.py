"""本地 SenseVoice（sherpa-onnx）+ Silero VAD 引擎。

离线整段识别：feed 进来的音频经 VAD 断句，每个完整语音段识别后立即
emit_final。不产生逐字中间结果，故 supports_partial = False。
模型覆盖中/英/日/韩/粤，RTF≈0.1（远快于实时），零成本、纯离线。
"""
from __future__ import annotations

import asyncio
import os

import numpy as np

from .base import StreamingASR


class LocalSenseVoiceASR(StreamingASR):
    def __init__(self, cfg: dict, on_partial=None, on_final=None) -> None:  # noqa: ANN001
        super().__init__(cfg, on_partial, on_final)
        import sherpa_onnx  # 延迟导入（重依赖）

        root = cfg.get("_root", ".")
        ec = (cfg.get("engines") or {}).get("local", {})
        model_dir = os.path.join(root, ec.get("model_dir", ""))
        vad_path = os.path.join(root, ec.get("vad_model", ""))
        num_threads = int(ec.get("num_threads", 2))
        language = ec.get("language", "auto")
        language = "" if language in ("auto", "", None) else language

        model_file = self._find_model_file(model_dir)
        tokens = os.path.join(model_dir, "tokens.txt")
        for p in (model_file, tokens, vad_path):
            if not p or not os.path.exists(p):
                raise FileNotFoundError(
                    f"本地模型缺失：{p or model_dir}\n"
                    f"请先运行： bash scripts/download_sensevoice.sh"
                )

        self._recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=model_file,
            tokens=tokens,
            num_threads=num_threads,
            use_itn=True,
            language=language,
        )

        vad_cfg = sherpa_onnx.VadModelConfig()
        vad_cfg.silero_vad.model = vad_path
        vad_cfg.silero_vad.threshold = 0.35           # 调灵敏：少吞"沁/嘶"这类弱清辅音开头
        vad_cfg.silero_vad.min_silence_duration = 0.25
        vad_cfg.silero_vad.min_speech_duration = 0.10  # 允许更短促的字，避免漏掉单字
        vad_cfg.sample_rate = 16000
        self._vad = sherpa_onnx.VoiceActivityDetector(vad_cfg, buffer_size_in_seconds=30)

    @staticmethod
    def _find_model_file(model_dir: str) -> str:
        for name in ("model.int8.onnx", "model.onnx"):
            p = os.path.join(model_dir, name)
            if os.path.exists(p):
                return p
        return ""

    @property
    def supports_partial(self) -> bool:
        return False

    async def start(self) -> None:
        try:
            self._vad.reset()
        except Exception:
            pass

    async def feed(self, pcm: bytes) -> None:
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        self._vad.accept_waveform(samples)
        await self._drain()

    async def stop(self) -> None:
        self._vad.flush()
        await self._drain()

    async def _drain(self) -> None:
        while not self._vad.empty():
            samples = self._vad.front.samples
            self._vad.pop()
            text = await asyncio.to_thread(self._recognize, samples)
            self.emit_final(text)

    def _recognize(self, samples) -> str:  # noqa: ANN001
        stream = self._recognizer.create_stream()
        stream.accept_waveform(16000, samples)
        self._recognizer.decode_stream(stream)
        return stream.result.text
