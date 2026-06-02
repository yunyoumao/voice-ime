# -*- coding: utf-8 -*-
"""麦克风自检：列出所有输入设备，逐个测 0.8 秒看哪个有信号。

用法：双击 scripts\\mic_check.bat（或 .venv\\Scripts\\python.exe scripts\\mic_check.py）
测的时候对着麦说话，哪个设备的 peak% 明显跳高，哪个就是当前在收音的麦。
"""
import sounddevice as sd
import numpy as np


def main() -> None:
    devs = sd.query_devices()
    ins = [(i, d) for i, d in enumerate(devs) if (d.get("max_input_channels") or 0) > 0]
    try:
        default_in = sd.default.device[0]
    except Exception:
        default_in = "?"
    print(f"系统默认输入设备索引: {default_in}")
    print("=" * 64)
    print("逐个测 0.8 秒（现在对着麦说话，看哪个 peak% 跳起来）：\n")
    best = None
    for i, d in ins:
        name = (d.get("name") or "")[:36]
        try:
            rec = sd.rec(int(0.8 * 16000), samplerate=16000, channels=1, dtype="int16", device=i)
            sd.wait()
            peak = int(np.abs(rec).max())
            pct = round(peak * 100 / 32768)
            bar = "#" * min(40, pct)
            tag = "  <<< 有信号" if peak > 300 else ("  (微弱)" if peak > 50 else "")
            print(f"[{i:>2}] {name:<36} {pct:>3}% {bar}{tag}")
            if peak > 300 and (best is None or peak > best[1]):
                best = (i, peak, d.get("name") or "")
        except Exception as e:
            print(f"[{i:>2}] {name:<36}  打不开（{type(e).__name__}）")
    print("=" * 64)
    if best:
        print(f"信号最强：[{best[0]}] {best[2]}")
        print("→ 想让软件用它：在 Windows『声音设置→输入』里把它设为默认，然后重启本软件即可")
        print("  （软件跟随系统默认麦；远程桌面下默认就是“远程音频”）。")
    else:
        print("所有设备都没收到声音。如果你在远程桌面(RDP)操作，多半是 RDP 没转发麦克风：")
        print("  RDP 客户端 → 显示选项 → 本地资源 → 远程音频 → 设置 →")
        print("  远程录音选『从这台计算机录制』，然后断开重连。")
        print("  （或：人在本机前用真麦 / 改走服务端方案。）")


if __name__ == "__main__":
    main()
