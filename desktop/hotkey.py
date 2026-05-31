"""全局热键（按住说话 push-to-talk）。

支持单键或组合键（如 "<f8>" 或 "<ctrl>+<space>"）。当目标键集合被全部
按下时触发 on_start；其后任一目标键松开触发 on_stop。回调在 pynput 监听
线程中执行，调用方需自行做线程转移。

macOS 需在「辅助功能」与「输入监控」中授权运行本程序的终端/App。
"""
from __future__ import annotations

from typing import Callable

from pynput import keyboard


class HotkeyListener:
    def __init__(
        self,
        cfg: dict,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
    ) -> None:
        spec = cfg.get("hotkey", "<ctrl>+<space>")
        self._target = set(keyboard.HotKey.parse(spec))
        self._on_start = on_start
        self._on_stop = on_stop
        self._pressed: set = set()
        self._active = False
        self._listener: keyboard.Listener | None = None

    def _canon(self, key):  # noqa: ANN001
        if self._listener is not None:
            try:
                return self._listener.canonical(key)
            except Exception:
                return key
        return key

    def _handle_press(self, key) -> None:  # noqa: ANN001
        self._pressed.add(self._canon(key))
        if not self._active and self._target.issubset(self._pressed):
            self._active = True
            self._on_start()

    def _handle_release(self, key) -> None:  # noqa: ANN001
        k = self._canon(key)
        if self._active and k in self._target:
            self._active = False
            self._on_stop()
        self._pressed.discard(k)

    def start(self) -> None:
        self._listener = keyboard.Listener(
            on_press=self._handle_press,
            on_release=self._handle_release,
        )
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
