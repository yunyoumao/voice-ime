"""solotap 模式单测：单独按下→松开才触发；与别的键组合（如 Ctrl+Enter）不触发。

跑：.venv\\Scripts\\python.exe scripts/test_hotkey_solotap.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pynput import keyboard  # noqa: E402

from desktop.hotkey import HotkeyListener  # noqa: E402


def main() -> None:
    fired = {"n": 0}
    hl = HotkeyListener({"hotkey": ""}, on_start=lambda: None, on_stop=lambda: None)
    hl.add_binding("<f7>", "solotap", lambda: fired.__setitem__("n", fired["n"] + 1), None)
    K = keyboard.Key.f7                      # 触发键
    A = keyboard.KeyCode.from_char("a")      # 模拟"另一个键"（如 Enter）

    # 1) 单独按 f7 → 松开：应触发
    hl._handle_press(K); hl._handle_release(K)
    assert fired["n"] == 1, f"单独按应触发1次，实际 {fired['n']}"

    # 2) f7+a 组合（模拟 Ctrl+Enter）：不应触发
    hl._handle_press(K); hl._handle_press(A); hl._handle_release(A); hl._handle_release(K)
    assert fired["n"] == 1, f"组合键不应触发，实际 {fired['n']}"

    # 3) 再单独按一次：应再触发
    hl._handle_press(K); hl._handle_release(K)
    assert fired["n"] == 2, f"再单独按应触发，实际 {fired['n']}"

    # 4) f7 先按、再按 a、先松 f7（组合的另一种释放顺序，如 Ctrl 先松）：不应触发
    hl._handle_press(K); hl._handle_press(A); hl._handle_release(K); hl._handle_release(A)
    assert fired["n"] == 2, f"组合(另一种释放顺序)不应触发，实际 {fired['n']}"

    print("OK solotap 4/4: 单独按触发 / 组合不触发 / 重复单独按 / 组合先松也不触发")


if __name__ == "__main__":
    main()
