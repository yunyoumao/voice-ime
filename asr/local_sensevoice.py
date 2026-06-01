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

        from desktop.config import get_model_base
        root = get_model_base(cfg)               # 模型基目录(dev=项目根 / 打包=用户目录)，与首启下载窗解析一致
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
                    f"请先运行： python scripts/download_model.py"
                )

        # sherpa-onnx 在 Windows 读不了非 ASCII 路径（中文目录会让词表加载失败）→ 转成 ASCII 安全路径
        model_file = self._sherpa_path(model_file)
        tokens = self._sherpa_path(tokens)
        vad_path = self._sherpa_path(vad_path)
        for p in (model_file, tokens, vad_path):
            if os.name == "nt" and not p.isascii():
                raise RuntimeError(
                    f"sherpa-onnx 无法加载非 ASCII 路径的模型：{p}\n"
                    f"   解决：① 用 scripts\\run.bat 从项目根目录启动；"
                    f"或 ② 把项目移到纯英文路径（如 C:\\voice-input）。"
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
        self._drain_task: asyncio.Future | None = None   # 后台识别任务：feed 不等它，长语音断句不卡录音

    @staticmethod
    def _find_model_file(model_dir: str) -> str:
        for name in ("model.int8.onnx", "model.onnx"):
            p = os.path.join(model_dir, name)
            if os.path.exists(p):
                return p
        return ""

    @staticmethod
    def _sherpa_path(p: str) -> str:
        """转成 sherpa-onnx 能打开的 ASCII 路径（仅 Windows 需要）。

        sherpa-onnx 在 Windows 用窄字符 C++ API 读 model/tokens，路径含非 ASCII
        （如中文目录名「语音输入法」）会静默读不到词表 → 解码时抛
        `IndexError: invalid unordered_map<K, T> key`。优先用相对当前工作目录的
        路径（启动脚本已把 cwd 切到项目根，models/… 段是纯 ASCII），其次试 8.3 短路径。"""
        if os.name != "nt":
            return p
        ap = os.path.abspath(p)
        if ap.isascii():
            return ap
        try:
            rel = os.path.relpath(ap)
            if rel.isascii() and os.path.exists(rel):
                return rel
        except ValueError:
            pass
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(1024)
            if ctypes.windll.kernel32.GetShortPathNameW(ap, buf, 1024) and buf.value.isascii():
                return buf.value
        except Exception:
            pass
        return ap

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
        self._vad.accept_waveform(samples)        # 快、同步：仅入 VAD 缓冲
        self._kick_drain()                         # 识别放后台任务，feed 立即返回 → 不阻塞录音/浮窗

    def _kick_drain(self) -> None:
        # 同时只允许一个识别任务在跑；feed 不等它 → 长语音在停顿处断句识别时，录音与声波浮窗不再卡顿。
        if self._drain_task is None or self._drain_task.done():
            self._drain_task = asyncio.ensure_future(self._drain())

    async def stop(self) -> None:
        self._vad.flush()                          # 把尾段推入队列
        t = self._drain_task                       # 先等后台识别(若在跑)结束，避免并发 pop
        if t is not None and not t.done():
            try:
                await t
            except Exception:
                pass
        await self._drain()                        # 再把 flush 出来的尾段识别完(此刻无并发 feed)

    async def _drain(self) -> None:
        while not self._vad.empty():
            samples = self._vad.front.samples
            self._vad.pop()
            try:
                text = await asyncio.to_thread(self._recognize, samples)
            except Exception:
                continue                           # 单段识别失败 → 跳过，不拖垮整个后台任务
            self.emit_final(text)

    def _recognize(self, samples) -> str:  # noqa: ANN001
        stream = self._recognizer.create_stream()
        stream.accept_waveform(16000, samples)
        self._recognizer.decode_stream(stream)
        return stream.result.text
