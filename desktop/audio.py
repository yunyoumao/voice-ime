"""麦克风录音。

用 sounddevice 以 16kHz / 单声道 / int16 采集，每帧通过 on_frame 回调
回传裸 PCM 字节。回调在 PortAudio 的线程中执行，调用方需自行做线程转移
（例如 loop.call_soon_threadsafe）。
"""
from __future__ import annotations

from typing import Callable

import sounddevice as sd


class AudioRecorder:
    def __init__(self, cfg: dict, on_frame: Callable[[bytes], None]) -> None:
        a = cfg.get("audio", {})
        self.samplerate = int(a.get("samplerate", 16000))
        self.channels = int(a.get("channels", 1))
        self.blocksize = int(a.get("blocksize", 1600))
        self._on_frame = on_frame
        self._stream: sd.InputStream | None = None

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        # indata: int16 ndarray, shape (frames, channels)，单声道时 C 连续
        self._on_frame(indata.tobytes())

    def start(self) -> None:
        if self._stream is not None:
            return
        self._stream = sd.InputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            blocksize=self.blocksize,
            dtype="int16",
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is None:
            return
        self._stream.stop()
        self._stream.close()
        self._stream = None
