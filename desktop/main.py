"""桌面语音输入法入口（命令行版）。

按住/点按热键说话 → 实时识别 → 上屏。阶段 1 用命令行打印中间/最终结果，
阶段 3 再叠加浮窗与托盘。

运行： python -m desktop.main   （需在项目根目录、已激活 .venv）
"""
from __future__ import annotations

import asyncio
import collections
import sys

import numpy as np

from asr.factory import create_engine
from desktop.audio import AudioRecorder
from desktop.config import load_config
from desktop.hotkey import HotkeyListener
from desktop.output import OutputController
from pipeline import build_pipeline
from pipeline.base import Result
from sink import build_sinks


async def run() -> None:
    cfg = load_config()
    loop = asyncio.get_running_loop()
    out = OutputController(cfg)
    pipeline = build_pipeline(cfg)
    sinks = build_sinks(cfg, out)
    mode = str(cfg.get("hotkey_mode", "hold")).lower()

    def on_partial(text: str) -> None:
        sys.stdout.write("\r… " + text)
        sys.stdout.flush()

    async def handle_final(text: str) -> None:
        try:
            result = await pipeline.run(text)
        except Exception as exc:  # 处理失败 → 回退原文上屏，绝不吞字
            sys.stdout.write(f"   [处理失败，回退原文] {exc}\n")
            sys.stdout.flush()
            result = Result(text=text, mode="raw", sink="type")
        if result.mode != "raw":
            sys.stdout.write(f"   → [{result.mode}] {result.text}\n")
            sys.stdout.flush()
        sink = sinks.get(result.sink) or sinks["type"]
        await sink.emit(result)

    last_final = {"text": "", "t": 0.0}

    def on_final(text: str) -> None:
        now = loop.time()
        if text and text == last_final["text"] and now - last_final["t"] < 1.5:
            return  # 去重：1.5 秒内完全相同的识别结果只保留一次（防重复上屏）
        last_final["text"], last_final["t"] = text, now
        sys.stdout.write("\r✓ 识别原文：" + text + "\n")
        sys.stdout.flush()
        asyncio.run_coroutine_threadsafe(handle_final(text), loop)

    engine = create_engine(cfg, on_partial=on_partial, on_final=on_final)

    events: asyncio.Queue = asyncio.Queue()

    def on_frame(pcm: bytes) -> None:
        loop.call_soon_threadsafe(events.put_nowait, ("audio", pcm))

    start_hint = "🎤 开始录音…（再按一下结束）" if mode == "toggle" else "🎤 录音中…（按住说话）"

    def on_start() -> None:
        sys.stdout.write(start_hint + "\n")
        sys.stdout.flush()
        loop.call_soon_threadsafe(events.put_nowait, ("ctrl", "START"))

    def on_stop() -> None:
        sys.stdout.write("⏹  结束，处理中…\n")
        sys.stdout.flush()
        loop.call_soon_threadsafe(events.put_nowait, ("ctrl", "STOP"))

    audio = AudioRecorder(cfg, on_frame)
    hotkey = HotkeyListener(cfg, on_start, on_stop)
    hotkey.start()
    try:
        audio.start()                   # 麦克风常开：消除每次按键的冷启动延迟（吞字主因）
    except Exception as exc:
        print(f"❌ 麦克风打开失败：{exc}\n"
              f"   请到 系统设置→隐私与安全性→麦克风 给运行的终端授权后重试。")
        hotkey.stop()
        await engine.close()
        return

    # 预缓冲：把"按下热键前"的最近若干帧补给引擎，连按下瞬间的起音也不丢
    acfg = cfg.get("audio", {})
    frame_ms = max(1, int(acfg.get("blocksize", 1600)) * 1000 // int(acfg.get("samplerate", 16000)))
    preroll_frames = max(1, 500 // frame_ms)          # 约 500ms 的回补（再防吞字）
    preroll: collections.deque = collections.deque(maxlen=preroll_frames)

    label = "点按开始 / 再点一下结束" if mode == "toggle" else "按住说话、松开上屏"
    print(f"✅ 就绪：引擎={cfg.get('engine')}　热键=[{cfg.get('hotkey')}]　模式={mode}")
    print(f"   {label}（预缓冲 {preroll_frames * frame_ms}ms 防吞字）。Ctrl+C 退出。\n")

    active = False
    seg_frames = 0
    seg_peak = 0
    try:
        while True:
            kind, data = await events.get()
            if kind == "audio":
                preroll.append(data)                  # 始终滚动缓冲最近若干帧
                if active:
                    await engine.feed(data)
                    seg_frames += 1
                    arr = np.frombuffer(data, dtype=np.int16)
                    if arr.size:
                        seg_peak = max(seg_peak, int(np.abs(arr).max()))
            elif kind == "ctrl":
                if data == "START" and not active:
                    await engine.start()
                    for frame in preroll:             # 先补按下前的音频，再录实时
                        await engine.feed(frame)
                    active = True
                    seg_frames, seg_peak = 0, 0
                elif data == "STOP" and active:
                    active = False
                    await asyncio.sleep(0.08)         # 等残留音频帧入队
                    await _drain_audio(engine, events)
                    await engine.stop()
                    preroll.clear()                   # 清空，避免话尾混入下次开头
                    level = int(seg_peak * 100 / 32768)
                    hint = "⚠️ 几乎没收到声音 → 查麦克风权限/设备" if level < 2 else "麦克风正常"
                    sys.stdout.write(f"   [诊断] 本段 {seg_frames} 帧、峰值电平 {level}%（{hint}）\n")
                    sys.stdout.flush()
    except asyncio.CancelledError:
        pass
    finally:
        hotkey.stop()
        try:
            audio.stop()
        except Exception:
            pass
        await engine.close()


async def _drain_audio(engine, events: asyncio.Queue) -> None:
    """把队列中残留的音频帧喂完，保留并回填控制事件。"""
    keep = []
    while not events.empty():
        kind, data = events.get_nowait()
        if kind == "audio":
            await engine.feed(data)
        else:
            keep.append((kind, data))
    for e in keep:
        events.put_nowait(e)


def main() -> None:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n再见。")


if __name__ == "__main__":
    main()
