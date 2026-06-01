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
from desktop.mouse_gesture import MouseGestureListener
from desktop.output import OutputController
from desktop.radial_menu import LABELS, MODES, RadialMenu, StatusHud, cursor_xy
from pipeline import build_pipeline
from pipeline.base import Result
from sink import build_sinks

_CANCEL = object()   # 鼠标手势在中心/环外松开 → 取消，丢弃不上屏


async def run() -> None:
    cfg = load_config()
    loop = asyncio.get_running_loop()
    out = OutputController(cfg)
    pipeline = build_pipeline(cfg)
    sinks = build_sinks(cfg, out)
    mode = str(cfg.get("hotkey_mode", "hold")).lower()
    forced = {"mode": None}   # 手势选定模式：None=走前缀路由, 模式串=强制该模式, _CANCEL=取消
    rec = {"on": False}       # 是否正在录音（worker 据此决定状态浮窗何时隐藏）
    hud = None                # 状态浮窗 StatusHud；在菜单块里按需创建

    def set_status(s: str) -> None:
        # s: listen(听写中) | process(处理中) | off(隐藏)。仅在主线程调用（tk 非线程安全）。
        if hud is None:
            return
        if s == "listen":
            hud.show("🎧 听写中…")
        elif s == "process":
            hud.show("✍ 处理中…")
        else:
            hud.hide()

    def on_partial(text: str) -> None:
        sys.stdout.write("\r… " + text)
        sys.stdout.flush()

    finals: asyncio.Queue = asyncio.Queue()   # 识别结果按序处理队列（杜绝并发乱序）

    async def _compute_result(text: str, fmode):
        if fmode is _CANCEL:               # 手势在中心/环外松开 → 取消，丢弃
            return None
        try:
            return await pipeline.run(text, force_mode=fmode)
        except Exception as exc:  # 处理失败 → 回退原文上屏，绝不吞字
            sys.stdout.write(f"   [处理失败，回退原文] {exc}\n")
            sys.stdout.flush()
            return Result(text=text, mode="raw", sink="type")

    async def _emit_result(result) -> None:
        if result is None:
            return
        if result.mode != "raw":
            sys.stdout.write(f"   → [{result.mode}] {result.text}\n")
            sys.stdout.flush()
        sink = sinks.get(result.sink) or sinks["type"]
        await sink.emit(result)

    async def _final_worker() -> None:
        # 并发处理、按序上屏：多句同时调 GLM（并发上限 4），但严格按识别顺序上屏，
        # 兼顾速度与顺序——连说多句不再「一句等一句」地排队（修复"润色超级慢"）。
        sem = asyncio.Semaphore(4)
        ordered: asyncio.Queue = asyncio.Queue()

        async def _compute(text, fmode):
            async with sem:
                return await _compute_result(text, fmode)

        async def _launcher() -> None:
            while True:
                text, fmode = await finals.get()
                ordered.put_nowait(asyncio.ensure_future(_compute(text, fmode)))
                finals.task_done()

        async def _emitter() -> None:
            while True:
                task = await ordered.get()
                try:
                    await _emit_result(await task)   # 按入队顺序逐个等待 → 上屏严格保序
                except Exception as exc:
                    sys.stdout.write(f"   [处理异常] {exc}\n")
                    sys.stdout.flush()
                finally:
                    ordered.task_done()
                if finals.empty() and ordered.empty() and not rec["on"]:
                    set_status("off")        # 全部处理完且已停录 → 收起状态浮窗

        await asyncio.gather(_launcher(), _emitter())

    last_final = {"text": "", "t": 0.0}

    def on_final(text: str) -> None:
        now = loop.time()
        if text and text == last_final["text"] and now - last_final["t"] < 1.5:
            return  # 去重：1.5 秒内完全相同的识别结果只保留一次（防重复上屏）
        last_final["text"], last_final["t"] = text, now
        sys.stdout.write("\r✓ 识别原文：" + text + "\n")
        sys.stdout.flush()
        # 快照当前手势模式后入队，由单 worker 按序处理（防乱序）。on_final 在引擎线程 → threadsafe 入队。
        loop.call_soon_threadsafe(finals.put_nowait, (text, forced["mode"]))

    engine = create_engine(cfg, on_partial=on_partial, on_final=on_final)

    events: asyncio.Queue = asyncio.Queue()

    def on_frame(pcm: bytes) -> None:
        loop.call_soon_threadsafe(events.put_nowait, ("audio", pcm))

    start_hint = "🎤 开始录音…（再按一下结束）" if mode == "toggle" else "🎤 录音中…（按住说话）"

    def on_start() -> None:
        sys.stdout.write(start_hint + "\n")
        sys.stdout.flush()
        def _begin() -> None:
            forced["mode"] = None        # 热键开录：清掉上次手势选定，走前缀路由
            set_status("listen")
            events.put_nowait(("ctrl", "START"))
        loop.call_soon_threadsafe(_begin)

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

    # ---- 鼠标中键环形菜单（可选）：手势回调在 pynput 线程，所有 tk 操作经
    #      loop.call_soon_threadsafe 回到本事件循环主线程执行（tkinter 非线程安全）----
    menu = None
    gesture = None
    pump_task = None
    if (cfg.get("mouse_menu") or {}).get("enabled", False):
        try:
            menu = RadialMenu(cfg)
        except Exception as exc:
            print(f"⚠️ 环形菜单初始化失败，已禁用：{exc}")
            menu = None
        if menu is not None:
            try:
                hud = StatusHud(menu.root)      # 状态浮窗复用菜单的 tk root
            except Exception:
                hud = None
            # toggle 状态机：IDLE →(按住中键)SELECTING →(松在某瓣)RECORDING →(再点中键)IDLE
            gstate = {"s": "IDLE"}

            def g_press(x: int, y: int) -> None:
                if gstate["s"] == "RECORDING":     # 免持录音中，再点中键 = 停止并上屏
                    gstate["s"] = "IDLE"
                    events.put_nowait(("ctrl", "STOP"))
                    return
                gstate["s"] = "SELECTING"          # 开始一次新选择 + 录音
                forced["mode"] = None
                print(f"   [菜单] 已弹出 @ ({x},{y}) — 移到某一瓣后松开选择")
                menu.show(x, y)
                events.put_nowait(("ctrl", "START"))

            def g_move(x: int, y: int) -> None:
                if gstate["s"] == "SELECTING":
                    menu.highlight(menu.hit_test(x, y))

            def g_release(x: int, y: int) -> None:
                if gstate["s"] != "SELECTING":     # 停止那次按下的松开 → 忽略
                    return
                seg = menu.hit_test(x, y)
                menu.hide()
                if seg is None:                    # 中心死区/环外松开 = 取消
                    forced["mode"] = _CANCEL
                    gstate["s"] = "IDLE"
                    set_status("off")
                    events.put_nowait(("ctrl", "STOP"))
                else:                              # 选中 → 锁模式，菜单消失，继续免持录音
                    forced["mode"] = MODES[seg]
                    gstate["s"] = "RECORDING"
                    set_status("listen")
                    print(f"🔒 已选 [{LABELS[seg]}]，继续说话；再点一下中键停止上屏。")

            btn = str((cfg.get("mouse_menu") or {}).get("button", "middle")).lower()
            if btn in ("middle", "right", "left"):     # 鼠标键触发（move 即时更新高亮）
                gesture = MouseGestureListener(
                    cfg,
                    on_press=lambda x, y: loop.call_soon_threadsafe(g_press, x, y),
                    on_move=lambda x, y: loop.call_soon_threadsafe(g_move, x, y),
                    on_release=lambda x, y: loop.call_soon_threadsafe(g_release, x, y),
                )
                gesture.start()

            mk = (cfg.get("mouse_menu") or {}).get("hotkey")
            if mk:                                     # 键盘键触发（零冲突）：挂到同一个键盘监听(add_binding)
                def _menu_down() -> None:
                    print("   [键诊断] 菜单键 on_start 触发", flush=True)
                    loop.call_soon_threadsafe(g_press, *cursor_xy())
                hotkey.add_binding(
                    mk, "hold", _menu_down,
                    lambda: loop.call_soon_threadsafe(g_release, *cursor_xy()),
                )
                print(f"   [键诊断] 已注册热键目标 = {[sorted(b['target']) for b in hotkey._binds]}", flush=True)

            async def _pump_tk() -> None:
                while True:
                    if gstate["s"] == "SELECTING":     # 键盘触发无鼠标move → 轮询光标刷新高亮
                        menu.highlight(menu.hit_test(*cursor_xy()))
                    menu.pump()
                    await asyncio.sleep(0.025)
            pump_task = asyncio.create_task(_pump_tk())
            trig = ([f"{btn}键"] if btn in ("middle", "right", "left") else []) + ([f"快捷键{mk}"] if mk else [])
            print(f"🖱  环形菜单已启用：{' / '.join(trig) or '未配置触发'}"
                  f"（按住选 → 松开锁定免持 → 再触发一次停止）")

    # 预缓冲：把"按下热键前"的最近若干帧补给引擎，连按下瞬间的起音也不丢
    acfg = cfg.get("audio", {})
    frame_ms = max(1, int(acfg.get("blocksize", 1600)) * 1000 // int(acfg.get("samplerate", 16000)))
    preroll_frames = max(1, 500 // frame_ms)          # 约 500ms 的回补（再防吞字）
    preroll: collections.deque = collections.deque(maxlen=preroll_frames)

    label = "点按开始 / 再点一下结束" if mode == "toggle" else "按住说话、松开上屏"
    print(f"✅ 就绪：引擎={cfg.get('engine')}　热键=[{cfg.get('hotkey')}]　模式={mode}")
    print(f"   {label}（预缓冲 {preroll_frames * frame_ms}ms 防吞字）。Ctrl+C 退出。\n")

    worker_task = asyncio.create_task(_final_worker())   # 串行处理识别结果，严格保序
    seg_frames = 0
    seg_peak = 0
    try:
        while True:
            kind, data = await events.get()
            if kind == "audio":
                preroll.append(data)                  # 始终滚动缓冲最近若干帧
                if rec["on"]:
                    await engine.feed(data)
                    seg_frames += 1
                    arr = np.frombuffer(data, dtype=np.int16)
                    if arr.size:
                        seg_peak = max(seg_peak, int(np.abs(arr).max()))
            elif kind == "ctrl":
                if data == "START" and not rec["on"]:
                    await engine.start()
                    for frame in preroll:             # 先补按下前的音频，再录实时
                        await engine.feed(frame)
                    rec["on"] = True
                    seg_frames, seg_peak = 0, 0
                elif data == "STOP" and rec["on"]:
                    rec["on"] = False
                    set_status("process")            # 停录 → 显示「处理中」，worker 处理完再隐藏
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
        worker_task.cancel()
        if gesture is not None:
            gesture.stop()
        if pump_task is not None:
            pump_task.cancel()
        if menu is not None:
            menu.close()
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
