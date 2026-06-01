"""首启检测本地模型，缺失则弹窗下载（下到用户可写目录）。

主程序启动前调用 check_and_download(cfg)：模型就绪→直接 True；缺失→弹进度窗，
下完→True，取消/关窗→False（主程序据此退出）。打包后用户没有 models 时走这条路。
"""
from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import ttk

from desktop.config import get_model_base
from scripts.download_model import SV, main as download_main


def check_and_download(cfg: dict) -> bool:
    models_dir = os.path.join(get_model_base(cfg), "models")
    sv = os.path.join(models_dir, SV)
    vad = os.path.join(models_dir, "silero_vad.onnx")
    if os.path.isdir(sv) and os.path.isfile(vad):
        return True   # 模型已就绪

    state = {"ok": False, "label": "准备下载…", "pct": 0, "running": False, "err": None}

    root = tk.Tk()
    root.title("语音输入法 — 首次启动")
    root.geometry("440x190")
    root.resizable(False, False)
    try:
        root.eval("tk::PlaceWindow . center")
    except Exception:
        pass

    ttk.Label(root, text="🎙  首次启动 · 下载语音模型", font=("", 13, "bold")).pack(pady=(18, 4))
    ttk.Label(root, text=f"约 230MB，下载到：\n{models_dir}", justify="center",
              font=("", 9), foreground="#666").pack(pady=2)
    bar = ttk.Progressbar(root, length=360, mode="determinate", maximum=100)
    bar.pack(pady=10)
    status = ttk.Label(root, text="点「开始下载」开始（需联网，约几分钟）", font=("", 9))
    status.pack()
    btns = ttk.Frame(root)
    btns.pack(pady=12)
    start_btn = ttk.Button(btns, text="开始下载")
    cancel_btn = ttk.Button(btns, text="取消")
    start_btn.pack(side="left", padx=6)
    cancel_btn.pack(side="left", padx=6)

    def on_progress(label: str, pct: int) -> None:   # 工作线程调用 → 只写共享状态，不碰 tk
        state["label"], state["pct"] = label, pct

    def worker() -> None:
        try:
            download_main(models_dir, progress=on_progress)
            state["ok"] = True
        except Exception as e:                        # noqa: BLE001
            state["err"] = str(e)
        finally:
            state["running"] = False

    def poll() -> None:                               # 主线程定时把共享状态刷到 UI
        bar["value"] = state["pct"]
        if state["err"]:
            status.config(text=f"下载失败：{state['err'][:60]}", foreground="#c00")
            start_btn.config(state="normal", text="重试")
            cancel_btn.config(text="退出")
            return
        if state["running"]:
            status.config(text=f"{state['label']}  {state['pct']}%")
            root.after(150, poll)
        elif state["ok"]:
            status.config(text="✓ 完成，正在启动…", foreground="#0a0")
            root.after(800, root.destroy)

    def on_start() -> None:
        if state["running"]:
            return
        state["running"], state["err"] = True, None
        start_btn.config(state="disabled")
        threading.Thread(target=worker, daemon=True).start()
        root.after(150, poll)

    start_btn.config(command=on_start)
    cancel_btn.config(command=root.destroy)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()
    return state["ok"]
