"""全局热键（按住说话 push-to-talk，或按一下切换 toggle）。

支持单键或组合键（如 "<alt_r>" 或 "<ctrl>+<space>"）：
- hold（默认）：目标键全部按下触发 on_start，其后任一目标键松开触发 on_stop。
- toggle：每"按齐一次"翻转一次——按一下开始录音，再按一下结束（适合说长段/总结）。

匹配按**虚拟键码 vk** 统一比对：pynput 解析热键时，有的名字给 Key 枚举、有的给
KeyCode（如 <alt_r>→KeyCode(61)），实际按键事件又可能是另一种；统一取 vk 才能可靠
匹配，并精确区分左右修饰键（右 Option=61 ≠ 左 Option=58）。

回调在 pynput 监听线程中执行，调用方需自行做线程转移。
⚠️ 左右键：右 Option=<alt_r>、右 Cmd=<cmd_r>、右 Ctrl=<ctrl_r>、右 Shift=<shift_r>。
   不确定填什么就跑 scripts/probe_key.py 探测。Fn/🌐 键 pynput 抓不到，无法用。
macOS 需在「辅助功能」与「输入监控」中授权运行本程序的终端/App，否则收不到任何键。
"""
from __future__ import annotations

from typing import Callable

from pynput import keyboard


def _ident(key, listener: keyboard.Listener | None = None):
    """把按键规范成可 hash 的标识（vk 整数优先，其次 char），消除 Key 枚举 /
    KeyCode / 左右键表示差异。"""
    if listener is not None:
        try:
            key = listener.canonical(key)   # 还原键盘布局（主要对字符键）
        except Exception:
            pass
    vk = getattr(key, "vk", None)
    if vk is None and isinstance(key, keyboard.Key):
        vk = getattr(key.value, "vk", None)
    if vk is not None:
        return ("vk", vk)
    char = getattr(key, "char", None)
    if char is None and isinstance(key, keyboard.Key):
        char = getattr(key.value, "char", None)
    return ("char", char) if char is not None else ("repr", repr(key))


class HotkeyListener:
    def __init__(
        self,
        cfg: dict,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
    ) -> None:
        spec = cfg.get("hotkey", "<alt_r>")
        # 构造时尚无 listener，但修饰键/功能键无需布局还原，直接取 vk 即稳定
        self._target = {_ident(k) for k in keyboard.HotKey.parse(spec)}
        self._mode = str(cfg.get("hotkey_mode", "hold")).lower()  # hold | toggle
        self._on_start = on_start
        self._on_stop = on_stop
        self._pressed: set = set()
        self._active = False
        self._combo_down = False          # 组合键当前是否"已按齐"（toggle 防长按重复）
        self._listener: keyboard.Listener | None = None

    def _handle_press(self, key) -> None:  # noqa: ANN001
        self._pressed.add(_ident(key, self._listener))
        if not self._target.issubset(self._pressed):
            return
        if self._mode == "toggle":
            if not self._combo_down:          # 仅在"刚按齐"那一刻翻转，忽略长按重复
                self._combo_down = True
                self._active = not self._active
                (self._on_start if self._active else self._on_stop)()
        else:  # hold
            if not self._active:
                self._active = True
                self._on_start()

    def _handle_release(self, key) -> None:  # noqa: ANN001
        kid = _ident(key, self._listener)
        if self._mode == "toggle":
            if kid in self._target:
                self._combo_down = False
        else:  # hold
            if self._active and kid in self._target:
                self._active = False
                self._on_stop()
        self._pressed.discard(kid)

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
