"""鼠标手势源：监听中键（可配）按下/松开 + 拖动，回调只转发屏幕坐标。

对标 desktop/hotkey.py：回调在 **pynput 监听线程** 执行，**绝不能在回调里直接
操作 tkinter**（跨线程会崩）。main.py 用 loop.call_soon_threadsafe 把这里的回调
转移到事件循环主线程，再去 show/highlight/hide 菜单。

⚠️ 中键默认有「自动滚动」副作用，pynput 无法选择性抑制（suppress=True 会吞掉
所有鼠标事件），v1 接受；可在 config 用 mouse_menu.button 改 right/left。
"""
from __future__ import annotations

from typing import Callable

from pynput import mouse

_BUTTONS = {
    "middle": mouse.Button.middle,
    "right": mouse.Button.right,
    "left": mouse.Button.left,
}
_WM_MBUTTONDOWN, _WM_MBUTTONUP = 0x0207, 0x0208   # 仅中键做系统级抑制（防网页自动滚动）


class MouseGestureListener:
    def __init__(
        self,
        cfg: dict,
        on_press: Callable[[int, int], None],
        on_move: Callable[[int, int], None],
        on_release: Callable[[int, int], None],
    ) -> None:
        mm = cfg.get("mouse_menu", {}) or {}
        self._button = _BUTTONS.get(str(mm.get("button", "middle")).lower(), mouse.Button.middle)
        # 只抑制中键的系统传播；右/左键若抑制会破坏正常点击，故不抑制。
        self._suppress = {_WM_MBUTTONDOWN, _WM_MBUTTONUP} if self._button is mouse.Button.middle else set()
        self._on_press = on_press
        self._on_move = on_move
        self._on_release = on_release
        self._active = False
        self._listener: mouse.Listener | None = None

    def _on_click(self, x, y, button, pressed) -> None:  # noqa: ANN001
        if button is not self._button:
            return
        if pressed:
            self._active = True
            self._on_press(int(x), int(y))
        elif self._active:
            self._active = False
            self._on_release(int(x), int(y))

    def _handle_move(self, x, y) -> None:  # noqa: ANN001
        if self._active:
            self._on_move(int(x), int(y))

    def _win32_filter(self, msg, data) -> bool:  # noqa: ANN001
        # 抑制中键按下/松开向系统传播 → 浏览器等不再进入"自动滚动"；只调 suppress_event()、
        # 不返回 False，所以 pynput 仍会回调 on_click（手势照常工作）。
        if msg in self._suppress and self._listener is not None:
            try:
                self._listener.suppress_event()
            except Exception:
                pass
        return True

    def start(self) -> None:
        self._listener = mouse.Listener(
            on_click=self._on_click,
            on_move=self._handle_move,
            win32_event_filter=self._win32_filter,
        )
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
