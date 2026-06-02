"""麦克风录音。

用 sounddevice 以 16kHz / 单声道 / int16 采集，每帧通过 on_frame 回调
回传裸 PCM 字节。回调在 PortAudio 的线程中执行，调用方需自行做线程转移
（例如 loop.call_soon_threadsafe）。

支持 audio.device 选输入设备、audio.gain 软件增益（远程桌面/RDP 麦克风
往往偏小声，靠增益把电平拉起来，否则识别会乱）。
"""
from __future__ import annotations

from typing import Callable

import numpy as np
import sounddevice as sd


def _resolve_device(device):  # noqa: ANN001, ANN201
    """把 config 的 audio.device 规整成 sounddevice 能用的单一设备索引。

    - None / "" → None（系统默认）
    - int 或纯数字串 → 当索引用
    - 名字（同一支麦常在 MME/DirectSound/WASAPI/WDM-KS 下重名）→ 收集所有匹配的
      输入设备取第一个（通常是 MME，最稳）。**撞名不再抛 "Multiple input devices"**。
    - 名字匹配不到 → 回退系统默认，至少不崩。
    """
    if device is None or device == "" or isinstance(device, bool):
        return None
    if isinstance(device, int):
        return device
    s = str(device).strip()
    if s.lstrip("-").isdigit():
        return int(s)
    try:
        devs = list(sd.query_devices())
    except Exception:
        return None
    ins = [i for i, d in enumerate(devs) if (d.get("max_input_channels") or 0) > 0]
    exact = [i for i in ins if (devs[i].get("name") or "") == s]
    sub = [i for i in ins if s in (devs[i].get("name") or "")]
    hit = exact or sub
    return hit[0] if hit else None


class AudioRecorder:
    def __init__(self, cfg: dict, on_frame: Callable[[bytes], None]) -> None:
        a = cfg.get("audio", {})
        self.samplerate = int(a.get("samplerate", 16000))
        self.channels = int(a.get("channels", 1))
        self.blocksize = int(a.get("blocksize", 1600))
        self._device = a.get("device")            # None=系统默认；int 索引 或 str 名字片段
        self._gain = float(a.get("gain", 1.0))    # 软件增益：RDP/远程麦偏小声时调大
        self._on_frame = on_frame
        self._stream: sd.InputStream | None = None

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        # indata: int16 ndarray, shape (frames, channels)，单声道时 C 连续
        if self._gain != 1.0:
            indata = np.clip(indata.astype(np.float32) * self._gain, -32768, 32767).astype(np.int16)
        self._on_frame(indata.tobytes())

    def start(self) -> None:
        if self._stream is not None:
            return
        self._stream = sd.InputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            blocksize=self.blocksize,
            dtype="int16",
            device=_resolve_device(self._device),
            callback=self._callback,
        )
        self._stream.start()
        try:
            name = sd.query_devices(self._stream.device, "input")["name"]
        except Exception:
            name = str(self._device)
        print(f"🎙  录音设备：{name}（增益 ×{self._gain:g}）")

    def stop(self) -> None:
        if self._stream is None:
            return
        self._stream.stop()
        self._stream.close()
        self._stream = None
