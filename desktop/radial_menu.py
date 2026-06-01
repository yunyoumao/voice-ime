"""鼠标中键环形菜单：纯几何命中判定 + tkinter 无边框/置顶/透明菜单窗。

- MenuGeometry：纯函数命中判定（屏幕坐标，+Y 向下），可无 GUI 单测。
- RadialMenu：持有进程唯一的 tk root；所有方法**必须在创建它的线程**
  （main.py 的 asyncio 事件循环主线程）调用——main.py 用
  loop.call_soon_threadsafe 把 pynput 鼠标回调转移到主线程后再调本类。

角度约定：hit_test 用 atan2(dy,dx)（+Y 向下），瓣 i = 角 // 60。
绘制弧角 θ = -φ，故 create_arc(start=-(i*60+60), extent=60) 与 hit_test 对齐。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# 瓣顺序固定：索引 = hit_test 返回值，与 LABELS / pipeline 模式一一对应
MODES = ["raw", "polish", "translate_zh", "translate_ja", "translate_en", "summary"]
LABELS = ["直接打字", "语音润色", "译中", "译日", "译英", "总结"]


def cursor_xy() -> tuple[int, int]:
    """当前鼠标光标屏幕坐标（Windows）。键盘触发菜单时用它定位/命中。"""
    try:
        import ctypes
        from ctypes import wintypes
        pt = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return int(pt.x), int(pt.y)
    except Exception:
        return 0, 0


@dataclass
class MenuGeometry:
    """环形命中判定（屏幕坐标，+Y 向下）。纯函数、无副作用、可单测。"""
    center_x: float
    center_y: float
    inner_radius: float = 55.0
    outer_radius: float = 160.0

    def hit_test(self, x: float, y: float) -> int | None:
        dx, dy = x - self.center_x, y - self.center_y
        r = math.hypot(dx, dy)
        if r < self.inner_radius or r > self.outer_radius:
            return None                       # 中心死区 / 环外 → 不高亮任何瓣
        ang = math.degrees(math.atan2(dy, dx)) % 360.0
        return int(ang // 60) % 6

    def zone(self, x: float, y: float):
        """松开判区：int(瓣 0-5) | 'center'(死区,默认直接打字) | 'outside'(环外,取消)。"""
        dx, dy = x - self.center_x, y - self.center_y
        r = math.hypot(dx, dy)
        if r < self.inner_radius:
            return "center"
        if r > self.outer_radius:
            return "outside"
        ang = math.degrees(math.atan2(dy, dx)) % 360.0
        return int(ang // 60) % 6


class RadialMenu:
    _BG = "magenta"          # 透明色：背景与中心洞用它 → 穿透点击、只显示圆环

    def __init__(self, cfg: dict | None = None) -> None:
        import tkinter as tk
        mm = (cfg or {}).get("mouse_menu", {}) or {}
        self._inner = float(mm.get("inner_radius", 55))
        self._outer = float(mm.get("outer_radius", 160))
        self._size = int(self._outer * 2 + 4)
        self._highlight: int | None = None
        self._visible = False
        self._saved_hwnd = None
        self.geom = MenuGeometry(0.0, 0.0, self._inner, self._outer)

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-transparentcolor", self._BG)
        except Exception:
            pass
        self.root.configure(bg=self._BG)
        self._canvas = tk.Canvas(self.root, width=self._size, height=self._size,
                                 bg=self._BG, highlightthickness=0, bd=0)
        self._canvas.pack()
        self.root.withdraw()

    def pump(self) -> None:
        """主线程 asyncio 任务定期调用，驱动 tk 事件（无独立 mainloop）。"""
        try:
            self.root.update()
        except Exception:
            pass

    def show(self, x: int, y: int) -> None:
        self.geom.center_x, self.geom.center_y = float(x), float(y)
        self._highlight = None
        left, top = int(x - self._size / 2), int(y - self._size / 2)
        self.root.geometry(f"{self._size}x{self._size}+{left}+{top}")
        self._save_focus()
        self.root.deiconify()
        self.root.update_idletasks()
        self._apply_noactivate()
        self._restore_focus()      # 不抢目标窗口焦点，确保松开后 Ctrl+V 落在目标输入框
        self._draw()
        self._visible = True

    def highlight(self, seg: int | None) -> None:
        if seg != self._highlight:        # 仅在选中瓣变化时重绘，省开销
            self._highlight = seg
            if self._visible:
                self._draw()

    def hit_test(self, x: int, y: int) -> int | None:
        return self.geom.hit_test(x, y)

    def hide(self) -> None:
        self._visible = False
        try:
            self.root.withdraw()
        except Exception:
            pass

    def close(self) -> None:
        try:
            self.root.destroy()
        except Exception:
            pass

    # ---------------- internals ----------------
    def _draw(self) -> None:
        import tkinter as tk
        c = self._canvas
        c.delete("all")
        cx = cy = self._size / 2          # 窗口局部中心
        for i in range(6):
            color = "#2563eb" if i == self._highlight else "#262626"
            c.create_arc(cx - self._outer, cy - self._outer, cx + self._outer, cy + self._outer,
                         start=-(i * 60 + 60), extent=60, style=tk.PIESLICE,
                         fill=color, outline="#555555", width=2)
        c.create_oval(cx - self._inner, cy - self._inner, cx + self._inner, cy + self._inner,
                      fill=self._BG, outline="#555555", width=2)
        rr = (self._inner + self._outer) / 2
        for i, label in enumerate(LABELS):
            a = math.radians(i * 60 + 30)
            c.create_text(cx + rr * math.cos(a), cy + rr * math.sin(a),
                          text=label, fill="#ffffff", font=("Microsoft YaHei", 11, "bold"))

    def _save_focus(self) -> None:
        try:
            import ctypes
            self._saved_hwnd = ctypes.windll.user32.GetForegroundWindow()
        except Exception:
            self._saved_hwnd = None

    def _restore_focus(self) -> None:
        try:
            import ctypes
            if self._saved_hwnd:
                ctypes.windll.user32.SetForegroundWindow(self._saved_hwnd)
        except Exception:
            pass

    def _apply_noactivate(self) -> None:
        try:
            import ctypes
            GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = -20, 0x08000000, 0x00000080
            user32 = ctypes.windll.user32
            hwnd = self.root.winfo_id()
            ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        except Exception:
            pass


class StatusHud:
    """录音/处理状态小浮窗（贴光标旁），不抢焦点。复用进程已有的 tk root（菜单的 root）。

    show("…") 在鼠标光标附近弹一个小标签（如「🎧 听写中…」「✍ 处理中…」），
    hide() 收起。和 RadialMenu 一样设 NOACTIVATE 并还原前台窗口，绝不夺走目标输入框焦点。
    """

    def __init__(self, root) -> None:
        import tkinter as tk
        self._win = tk.Toplevel(root)
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        try:
            self._win.attributes("-alpha", 0.92)
        except Exception:
            pass
        self._label = tk.Label(self._win, text="", fg="#ffffff", bg="#1f2937",
                               font=("Microsoft YaHei", 11, "bold"), padx=14, pady=6)
        self._label.pack()
        self._win.withdraw()
        self._visible = False

    def show(self, text: str) -> None:
        self._label.config(text=text)
        cx, cy = self._cursor_xy()
        x, y = cx + 18, cy + 22
        self._win.geometry(f"+{x}+{y}")
        saved = self._foreground()
        self._win.deiconify()
        self._win.update_idletasks()
        try:                                   # 防超出屏幕：按实际尺寸夹到可视区域内
            w, h = self._win.winfo_reqwidth(), self._win.winfo_reqheight()
            sw, sh = self._win.winfo_screenwidth(), self._win.winfo_screenheight()
            x = max(4, min(x, sw - w - 4))
            y = max(4, min(y, sh - h - 4))
            self._win.geometry(f"+{x}+{y}")
        except Exception:
            pass
        self._apply_noactivate()
        self._set_foreground(saved)
        self._visible = True

    def hide(self) -> None:
        if not self._visible:
            return
        self._visible = False
        try:
            self._win.withdraw()
        except Exception:
            pass

    @staticmethod
    def _cursor_xy():
        try:
            import ctypes
            from ctypes import wintypes
            pt = wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
            return int(pt.x), int(pt.y)
        except Exception:
            return 100, 100

    @staticmethod
    def _foreground():
        try:
            import ctypes
            return ctypes.windll.user32.GetForegroundWindow()
        except Exception:
            return None

    @staticmethod
    def _set_foreground(h) -> None:
        try:
            import ctypes
            if h:
                ctypes.windll.user32.SetForegroundWindow(h)
        except Exception:
            pass

    def _apply_noactivate(self) -> None:
        try:
            import ctypes
            GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW = -20, 0x08000000, 0x00000080
            user32 = ctypes.windll.user32
            hwnd = self._win.winfo_id()
            ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        except Exception:
            pass
