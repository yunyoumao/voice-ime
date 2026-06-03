"""上屏：把识别结果送到当前光标处。

默认 paste 模式：暂存原剪贴板 → 写入结果 → 模拟 Cmd+V(Mac)/Ctrl+V(Win)
→ 恢复原剪贴板。比逐字模拟快，且对中日文输入法无冲突。
type 模式：直接用 pynput 逐字键入（个别 App 兼容性更好，但慢）。
"""
from __future__ import annotations

import sys
import time

import pyperclip
from pynput.keyboard import Controller, Key


class OutputController:
    def __init__(self, cfg: dict) -> None:
        o = cfg.get("output", {})
        self.mode = o.get("mode", "paste")
        self.restore = bool(o.get("restore_clipboard", True))
        self._kb = Controller()
        self._is_mac = sys.platform == "darwin"
        self._last_text = None          # 上屏去重：防 pynput 偶发把一次触发发成两下导致重复粘贴
        self._last_t = 0.0

    def put(self, text: str) -> None:
        if not text:
            return
        now = time.monotonic()
        if text == self._last_text and (now - self._last_t) < 1.0:
            return                      # 同一段文字 1s 内只上屏一次（挡偶发重复，正常说话间隔远大于此）
        self._last_text, self._last_t = text, now
        if self.mode == "type":
            self._kb.type(text)
            return
        self._paste_text(text)

    def _paste_text(self, text: str) -> None:
        old = None
        if self.restore:
            try:
                old = pyperclip.paste()
            except Exception:
                old = None
        pyperclip.copy(text)
        time.sleep(0.04)  # 等剪贴板写入生效
        self._send_paste()
        if self.restore and old is not None:
            # 等目标程序真正读完剪贴板再恢复——Excel 等读得慢，恢复太快会粘成旧内容（竞态）。
            # 这段延迟在 Ctrl+V 之后、不影响你看到文字的速度（恢复是后台静默做的）。
            time.sleep(0.4)
            pyperclip.copy(old)

    def _send_paste(self) -> None:
        mod = Key.cmd if self._is_mac else Key.ctrl
        self._kb.press(mod)
        self._kb.press("v")
        self._kb.release("v")
        self._kb.release(mod)
