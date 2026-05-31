"""离线验证本地 SenseVoice 引擎。

用模型自带的 test_wavs（中/英/日/韩）喂给 LocalSenseVoiceASR，确认
模型加载、VAD 断句、识别（front.samples / result.text）整条链路正常，
不依赖麦克风。运行： .venv/bin/python scripts/test_local_engine.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import wave

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

from asr.local_sensevoice import LocalSenseVoiceASR  # noqa: E402
from desktop.config import load_config  # noqa: E402


def read_wav_pcm16(path: str):
    with wave.open(path, "rb") as w:
        return w.getframerate(), w.getnchannels(), w.getsampwidth(), w.readframes(w.getnframes())


async def main() -> None:
    cfg = load_config()
    model_dir = os.path.join(PROJ, cfg["engines"]["local"]["model_dir"])
    wav_dir = os.path.join(model_dir, "test_wavs")

    collected: list[str] = []
    engine = LocalSenseVoiceASR(cfg, on_final=collected.append)
    print("✓ 引擎初始化成功（模型已加载）\n")

    for name in ["zh.wav", "en.wav", "ja.wav", "ko.wav", "yue.wav"]:
        path = os.path.join(wav_dir, name)
        if not os.path.exists(path):
            print(f"  skip {name}（不存在）")
            continue
        rate, ch, width, pcm = read_wav_pcm16(path)
        collected.clear()
        await engine.start()
        step = 3200  # ~100ms @16k mono int16
        for i in range(0, len(pcm), step):
            await engine.feed(pcm[i:i + step])
        await engine.stop()
        flag = "" if (rate == 16000 and ch == 1 and width == 2) else "  ⚠️非16k/mono/16bit"
        print(f"  [{name}] {rate}Hz/{ch}ch/{width*8}bit{flag}  →  {' | '.join(collected) or '(无结果)'}")

    await engine.close()
    print("\n✓ 本地引擎链路验证完成")


if __name__ == "__main__":
    asyncio.run(main())
