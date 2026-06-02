"""桌面语音输入法入口（命令行版）。

按住/点按热键说话 → 实时识别 → 上屏。阶段 1 用命令行打印中间/最终结果，
阶段 3 再叠加浮窗与托盘。

运行： python -m desktop.main   （需在项目根目录、已激活 .venv）
"""
from __future__ import annotations

import asyncio
import collections
import os
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
    inflight = {"n": 0}       # 处理管线中未完成的句数（判断"处理中"何时收起）
    hud = None                # 状态浮窗 StatusHud；在菜单块里按需创建

    def set_status(s: str, est: float = 1.3) -> None:
        # s: listen(声波) | process(进度条,est=预估秒) | done(完成跳满) | off(隐藏)。仅主线程调用(tk 非线程安全)。
        if hud is None:
            return
        if s == "listen":
            hud.show_listen()
        elif s == "process":
            hud.show_process(est)
        elif s == "done":
            hud.finish()
        else:
            hud.hide()

    def on_partial(text: str) -> None:
        sys.stdout.write("\r… " + text)
        sys.stdout.flush()

    finals: asyncio.Queue = asyncio.Queue()   # 处理通道：("seg",文本)累积本段片段 / ("flush",模式)停录后整段发一次
    proc_avg = {"s": 1.3}                      # 处理耗时滚动均值(秒)：驱动「处理中」进度条的估计

    async def _compute_result(text: str, fmode):
        if fmode is _CANCEL:               # 手势在中心/环外松开 → 取消，丢弃
            return None
        t0 = loop.time()
        try:
            res = await pipeline.run(text, force_mode=fmode)
        except Exception as exc:  # 处理失败 → 回退原文上屏，绝不吞字
            sys.stdout.write(f"   [处理失败，回退原文] {exc}\n")
            sys.stdout.flush()
            res = Result(text=text, mode="raw", sink="type")
        proc_avg["s"] = proc_avg["s"] * 0.7 + (loop.time() - t0) * 0.3   # 滚动均值 → 进度条估时
        return res

    async def _emit_result(result) -> None:
        if result is None:
            return
        if result.mode != "raw":
            sys.stdout.write(f"   → [{result.mode}] {result.text}\n")
            sys.stdout.flush()
        sink = sinks.get(result.sink) or sinks["type"]
        await sink.emit(result)

    def _record(raw: str, res, secs: float) -> None:
        # 写历史 + 统计（后台进程独占写）；失败静默，绝不影响识别→上屏主链路。
        try:
            from desktop import history, stats
            history.append(raw, res.text, res.mode, secs)
            stats.bump(secs, len(res.text or ""))
        except Exception as exc:
            sys.stdout.write(f"   [历史记录失败] {exc}\n")
            sys.stdout.flush()

    async def _final_worker() -> None:
        # 整段聚合：识别片段(seg)累积到 buf，停录后收到 flush → 整段拼成一句发 GLM 一次。
        # 一段一次调用：上下文完整(润色/翻译更连贯、总结才成立)，且零并发 → 不触发智谱限流。
        buf: list[str] = []
        while True:
            kind, payload = await finals.get()            # 取消时抛 CancelledError 退出(不进 finally)
            try:
                if kind == "seg":
                    if payload:
                        buf.append(payload)
                elif kind == "flush":                     # payload = (本段锁定模式, 录音秒数)
                    fmode, secs = payload
                    text = " ".join(s for s in buf if s).strip()
                    buf.clear()
                    if not text or fmode is _CANCEL:      # 没识别出内容 / 取消 → 直接收起
                        set_status("off")
                    else:
                        inflight["n"] += 1
                        try:
                            res = await _compute_result(text, fmode)
                            await _emit_result(res)
                            if res is not None:
                                _record(text, res, secs)   # 写历史+统计(失败不影响主链路)
                        except Exception as exc:
                            sys.stdout.write(f"   [处理异常] {exc}\n")
                            sys.stdout.flush()
                        finally:
                            inflight["n"] = max(0, inflight["n"] - 1)
                        set_status("done")                # 处理完 → 进度跳满 100% 后收起
            except Exception as exc:                       # worker 永不退出(吞异常会卡死后续)
                sys.stdout.write(f"   [worker 异常] {exc}\n")
                sys.stdout.flush()
            finally:
                finals.task_done()

    def _clear_hud_if_idle() -> None:
        # 兜底：这次没识别出任何内容(静音/麦没收到音频)时，没有结果触发 worker 收起浮窗 → 这里清，
        # 避免"处理中"卡住。仅在确无待处理(队列空+无在途)且已停录时才清。
        if finals.empty() and inflight["n"] == 0 and not rec["on"]:
            set_status("off")

    last_final = {"text": "", "t": 0.0}

    def on_final(text: str) -> None:
        now = loop.time()
        if text and text == last_final["text"] and now - last_final["t"] < 1.5:
            return  # 去重：1.5 秒内完全相同的识别结果只保留一次（防重复上屏）
        last_final["text"], last_final["t"] = text, now
        sys.stdout.write("\r✓ 识别原文：" + text + "\n")
        sys.stdout.flush()
        # 只累积本段片段(不立即发)；停录后由 STOP 投一个 flush，worker 整段拼一次发 GLM。
        # on_final 可能在引擎线程 → threadsafe 入队，与 flush 保持 FIFO 顺序。
        loop.call_soon_threadsafe(finals.put_nowait, ("seg", text))

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
    rcfg = cfg.get("remote") or {}          # 蓝牙遥控器(如 CheerTok)：音量键当触发，拦截其调音量副作用
    if rcfg.get("talk_hotkey"):             # 音量+ = toggle 点按说话(默认模式)
        hotkey.add_binding(rcfg["talk_hotkey"], "toggle", on_start, on_stop,
                           suppress=bool(rcfg.get("suppress", True)))

    def open_settings() -> None:                # 拉起设置窗(独立 pywebview 子进程)；F9 与托盘共用
        import subprocess
        try:
            if getattr(sys, "frozen", False):       # 打包态：复用本 exe，带 --settings 跑设置窗
                subprocess.Popen([sys.executable, "--settings"])
            else:                                    # 开发态：子进程跑 desktop.settings
                subprocess.Popen([sys.executable, "-m", "desktop.settings"], cwd=cfg.get("_root", "."))
        except Exception as exc:
            print(f"⚠️ 打开设置失败：{exc}")

    settings_key = cfg.get("settings_hotkey", "<f9>")
    if settings_key:
        hotkey.add_binding(settings_key, "tap", open_settings, None)
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
                hud = StatusHud(menu.root, menu.theme,   # 浮窗玻璃跟随菜单开关：菜单玻璃成功→浮窗也用同款原生玻璃；否则回退 v3
                                glass=menu.use_glass(),
                                glass_tint=getattr(menu, "_glass_tint", (22, 24, 42, 78)))
            except Exception:
                hud = None
            # toggle 状态机：IDLE →(按住中键)SELECTING →(松在某瓣)RECORDING →(再点中键)IDLE
            gstate = {"s": "IDLE", "tap": False, "dz": None, "dn": 0}
            dwell_ms = int((cfg.get("mouse_menu") or {}).get("dwell_ms", 1200))

            def _apply_selection(z, stop_hint: str) -> None:
                # 判区落子(g_release/menu_tap 共用，仅停止提示不同；调用前已 menu.hide())：
                # "outside"=取消丢弃 | int(瓣)=强制该模式 | "center"=不选→走默认(default_mode 现为润色)+前缀路由。
                if z == "outside":
                    forced["mode"] = _CANCEL
                    gstate["s"] = "IDLE"
                    set_status("off")
                    events.put_nowait(("ctrl", "STOP"))
                    return
                if isinstance(z, int):
                    forced["mode"], label = MODES[z], LABELS[z]
                else:                              # 中心不选 → None，不再硬塞 raw
                    forced["mode"], label = None, "默认（润色）"
                gstate["s"] = "RECORDING"
                set_status("listen")
                print(f"🔒 已选 [{label}]，继续说话；{stop_hint}")

            def g_press(x: int, y: int) -> None:
                if gstate["s"] == "RECORDING":     # 免持录音中，再点中键 = 停止并上屏
                    gstate["s"] = "IDLE"
                    events.put_nowait(("ctrl", "STOP"))
                    return
                gstate["s"] = "SELECTING"          # 开始一次新选择 + 录音
                gstate["tap"] = False              # 按住拖选：靠松开确认，不走悬停 dwell
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
                z = menu.zone(x, y)                # int(瓣) | "center"(默认润色) | "outside"(取消)
                menu.hide()
                _apply_selection(z, "再按一下右 Ctrl 停止上屏。")

            btn = str((cfg.get("mouse_menu") or {}).get("button", "middle")).lower()
            if btn in ("middle", "right", "left"):     # 鼠标键触发（按住拖→松开选，move 即时更新高亮）
                gesture = MouseGestureListener(
                    cfg,
                    on_press=lambda x, y: loop.call_soon_threadsafe(g_press, x, y),
                    on_move=lambda x, y: loop.call_soon_threadsafe(g_move, x, y),
                    on_release=lambda x, y: loop.call_soon_threadsafe(g_release, x, y),
                )
                gesture.start()

            mk = (cfg.get("mouse_menu") or {}).get("hotkey")
            if mk:                                     # 键盘键触发（零冲突）：挂到同一个键盘监听(add_binding)
                hotkey.add_binding(
                    mk, "hold",
                    lambda: loop.call_soon_threadsafe(g_press, *cursor_xy()),
                    lambda: loop.call_soon_threadsafe(g_release, *cursor_xy()),
                )

            def menu_tap(x: int, y: int) -> None:
                # 遥控器"点按"开轮盘的三步循环(tap)，复用 gstate + 同套选择逻辑：
                # IDLE→开菜单+录(SELECTING)；SELECTING→锁高亮瓣+免持续录(RECORDING)；RECORDING→停止上屏。
                s = gstate["s"]
                if s == "IDLE":
                    gstate["s"] = "SELECTING"
                    gstate["tap"] = True               # 悬停自动确认：移到某瓣停约 dwell_ms 即选中，无需点击→不抢焦点
                    gstate["dz"], gstate["dn"] = None, 0
                    forced["mode"] = None
                    print(f"   [菜单] 已弹出 @ ({x},{y}) — 移到某一瓣悬停约 {dwell_ms}ms 自动选中")
                    menu.show(x, y)
                    events.put_nowait(("ctrl", "START"))
                elif s == "SELECTING":
                    z = menu.zone(x, y)
                    menu.hide()
                    _apply_selection(z, "再点一下停止上屏。")
                elif s == "RECORDING":
                    gstate["s"] = "IDLE"
                    events.put_nowait(("ctrl", "STOP"))

            if rcfg.get("menu_hotkey"):                # 音量- = tap 点按开轮盘
                hotkey.add_binding(
                    rcfg["menu_hotkey"], "tap",
                    lambda: loop.call_soon_threadsafe(menu_tap, *cursor_xy()), None,
                    suppress=bool(rcfg.get("suppress", True)),
                )

            dwell_ticks = max(1, int(dwell_ms / 25))   # 悬停自动确认所需 tick 数(每 tick ~25ms)

            async def _pump_tk() -> None:
                while True:
                    if gstate["s"] == "SELECTING":     # 键盘/遥控器触发无鼠标move → 轮询光标刷新高亮
                        x, y = cursor_xy()
                        menu.highlight(menu.hit_test(x, y))
                        if gstate.get("tap"):          # tap/遥控器开的菜单：移到某瓣"悬停"自动确认(免点击→不抢焦点)
                            z = menu.zone(x, y)
                            if z != "center" and z == gstate.get("dz"):
                                gstate["dn"] += 1
                                if gstate["dn"] >= dwell_ticks:
                                    g_release(x, y)    # 悬停够久 → 确认(瓣=锁模式 / 环外=取消)
                            else:
                                gstate["dz"], gstate["dn"] = z, 0
                    if hud is not None:
                        hud.tick()                     # 推进状态浮窗动效
                    menu.pump()
                    await asyncio.sleep(0.016)           # ~60fps：高亮跟手更快(原 25ms 偏慢)
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

    worker_task = asyncio.create_task(_final_worker())   # 累积识别片段，停录后整段拼一次发 GLM
    tray = tray_task = None
    try:                                                  # 系统托盘(打开设置/退出)：阻塞的 run() 放后台线程
        from desktop.tray import TrayIcon
        tray = TrayIcon(loop, open_settings, lambda: events.put_nowait(("quit", None)))
        tray_task = asyncio.create_task(asyncio.to_thread(tray.run))
    except Exception as exc:
        print(f"⚠️ 托盘启动失败(不影响使用)：{exc}")
    seg_frames = 0
    seg_peak = 0
    try:
        while True:
            kind, data = await events.get()
            if kind == "quit":                            # 托盘"退出" → 跳出主循环走清理
                break
            if kind == "audio":
                preroll.append(data)                  # 始终滚动缓冲最近若干帧
                if rec["on"]:
                    await engine.feed(data)
                    seg_frames += 1
                    arr = np.frombuffer(data, dtype=np.int16)
                    if arr.size:
                        peak = int(np.abs(arr).max())
                        seg_peak = max(seg_peak, peak)
                        if hud is not None:
                            hud.feed_level(min(1.0, peak / 10000.0))   # 归一化喂浮窗声波(10000≈说话峰值,可调)
            elif kind == "ctrl":
                if data == "START" and not rec["on"]:
                    await engine.start()
                    for frame in preroll:             # 先补按下前的音频，再录实时
                        await engine.feed(frame)
                    rec["on"] = True
                    rec["t0"] = loop.time()           # 录音起点(算时长用)
                    seg_frames, seg_peak = 0, 0
                elif data == "STOP" and rec["on"]:
                    rec["on"] = False
                    set_status("process", proc_avg["s"])   # 停录 → 进度条(按滚动均值估时)，处理完跳满
                    await asyncio.sleep(0.08)         # 等残留音频帧入队
                    await _drain_audio(engine, events)
                    await engine.stop()
                    # 整段一次发：把本段所有识别片段拼成一句发 GLM(call_soon 排在所有 seg 之后→FIFO)。
                    secs = max(0.0, loop.time() - rec.get("t0", loop.time()))   # 本段录音时长
                    loop.call_soon(finals.put_nowait, ("flush", (forced["mode"], secs)))
                    loop.call_later(2.5, _clear_hud_if_idle)   # 没识别出内容时兜底收起"处理中"
                    preroll.clear()                   # 清空，避免话尾混入下次开头
                    level = int(seg_peak * 100 / 32768)
                    hint = "⚠️ 几乎没收到声音 → 查麦克风权限/设备" if level < 2 else "麦克风正常"
                    sys.stdout.write(f"   [诊断] 本段 {seg_frames} 帧、峰值电平 {level}%（{hint}）\n")
                    sys.stdout.flush()
    except asyncio.CancelledError:
        pass
    finally:
        hotkey.stop()
        if tray is not None:
            tray.stop()
        if tray_task is not None:
            tray_task.cancel()
        worker_task.cancel()
        if gesture is not None:
            gesture.stop()
        if pump_task is not None:
            pump_task.cancel()
        if hud is not None:
            hud.close()
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


def _open_log_sink():
    """windowed exe 无控制台时的日志去向：按 log_enabled 返回日志文件句柄，否则丢弃 sink(不崩)。"""
    import io
    log_enabled = True
    try:
        from desktop.config import load_config
        log_enabled = bool(load_config().get("log_enabled", True))
    except Exception:
        pass
    if log_enabled:
        try:
            from desktop.config import get_user_data_dir
            d = get_user_data_dir()
            os.makedirs(d, exist_ok=True)
            return open(os.path.join(d, "voiceinput.log"), "a", encoding="utf-8", buffering=1)
        except Exception:
            pass
    return io.StringIO()


def main() -> None:
    if sys.stdout is None or sys.stderr is None:   # 打包成 windowed exe 无控制台→stdout/stderr 为 None，
        _logf = _open_log_sink()                    # 任何 print/write 都会崩 → 重定向到日志文件或丢弃 sink
        sys.stdout = sys.stdout or _logf
        sys.stderr = sys.stderr or _logf
    else:                                           # 真实控制台(中文 Windows 多为 GBK)→ 重设 utf-8，
        for _s in (sys.stdout, sys.stderr):         # 否则 print 里的 ✓/emoji/罕见字会 UnicodeEncodeError 崩
            try:
                _s.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    if "--settings" in sys.argv:                # 打包后用 --settings 复用本 exe 跑设置窗(单 exe 双模式)
        from desktop.settings import main as _settings_main
        _settings_main()
        return
    # 首启：本地引擎且模型缺失则弹窗下载(打包后用户首次运行走这条)；取消则退出。
    cfg = load_config()
    if str(cfg.get("engine") or "local").lower() == "local":
        from desktop.download_prompt import check_and_download
        if not check_and_download(cfg):
            print("\n已取消下载模型，退出。")
            return
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n再见。")


if __name__ == "__main__":
    main()
