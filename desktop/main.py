"""桌面语音输入法入口（命令行版）。

按住热键说话 → 实时识别 → 松开上屏。阶段 1 用命令行打印中间/最终结果，
阶段 3 再叠加浮窗与托盘。

运行： python -m desktop.main   （需在项目根目录、已激活 .venv）
"""
from __future__ import annotations

import asyncio
import sys

from asr.factory import create_engine
from desktop.audio import AudioRecorder
from desktop.config import load_config
from desktop.hotkey import HotkeyListener
from desktop.output import OutputController


async def run() -> None:
    cfg = load_config()
    loop = asyncio.get_running_loop()
    out = OutputController(cfg)

    def on_partial(text: str) -> None:
        sys.stdout.write("\r… " + text)
        sys.stdout.flush()

    def on_final(text: str) -> None:
        sys.stdout.write("\r✓ " + text + "\n")
        sys.stdout.flush()
        out.put(text)

    engine = create_engine(cfg, on_partial=on_partial, on_final=on_final)

    events: asyncio.Queue = asyncio.Queue()

    def on_frame(pcm: bytes) -> None:
        loop.call_soon_threadsafe(events.put_nowait, ("audio", pcm))

    def on_start() -> None:
        loop.call_soon_threadsafe(events.put_nowait, ("ctrl", "START"))

    def on_stop() -> None:
        loop.call_soon_threadsafe(events.put_nowait, ("ctrl", "STOP"))

    audio = AudioRecorder(cfg, on_frame)
    hotkey = HotkeyListener(cfg, on_start, on_stop)
    hotkey.start()

    print(f"✅ 就绪：引擎={cfg.get('engine')}　热键=[{cfg.get('hotkey')}]")
    print("   按住热键说话，松开上屏。Ctrl+C 退出。\n")

    active = False
    try:
        while True:
            kind, data = await events.get()
            if kind == "ctrl":
                if data == "START" and not active:
                    active = True
                    await engine.start()
                    audio.start()
                elif data == "STOP" and active:
                    audio.stop()
                    await asyncio.sleep(0.08)        # 等残留音频帧入队
                    await _drain_audio(engine, events)
                    active = False
                    await engine.stop()
            elif kind == "audio" and active:
                await engine.feed(data)
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
