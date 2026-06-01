"""鼠标中键环形菜单：纯几何命中 + tkinter 主题化菜单窗 + 状态浮窗(动效进度)。

- MenuGeometry：纯函数命中(hit_test 高亮 / zone 松开判区)，可无 GUI 单测。
- RadialMenu：进程唯一 tk root；6 瓣环形 + 中心 hub 实时显示选中模式；主题化配色。
- StatusHud：贴光标状态浮窗，带「无固定终点」的流动进度动效(tick 逐帧推进)。
- 三套主题(purple/green/cream)，config: mouse_menu.theme 切换。

所有方法必须在创建 tk 的线程(main.py 事件循环主线程)调用；pynput 回调经
loop.call_soon_threadsafe 转移到主线程再调本类。
角度约定：hit_test 用 atan2(dy,dx)(+Y 向下)；绘制弧角 θ=-φ，故 start=-(i*60+…)。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

MODES = ["raw", "polish", "translate_zh", "translate_ja", "translate_en", "summary"]
LABELS = ["直接打字", "语音润色", "译中", "译日", "译英", "总结"]

_KEY = "#ff00ff"   # transparentcolor：圆盘外的角落透明(穿透点击)

THEMES = {
    "purple": {  # 淡紫系（默认）
        "wedge": "#3a3450", "wedge_hi": "#9d83e0", "outline": "#574f73",
        "hub": "#28233b", "hub_text": "#f1ecff", "label": "#cabfe6", "label_hi": "#ffffff",
        "hud_bg": "#28233b", "hud_text": "#f1ecff", "accent": "#9d83e0", "track": "#4a4366",
    },
    "green": {   # 墨绿系
        "wedge": "#21372f", "wedge_hi": "#46a085", "outline": "#37564c",
        "hub": "#172c25", "hub_text": "#e9f4ee", "label": "#bcd6cb", "label_hi": "#ffffff",
        "hud_bg": "#172c25", "hud_text": "#e9f4ee", "accent": "#46a085", "track": "#2c463d",
    },
    "cream": {   # 奶白系
        "wedge": "#e9dfca", "wedge_hi": "#c9a86a", "outline": "#c8bca0",
        "hub": "#f3ecdb", "hub_text": "#4b4030", "label": "#6c6048", "label_hi": "#332a1c",
        "hud_bg": "#f3ecdb", "hud_text": "#4b4030", "accent": "#c9a86a", "track": "#d8cdb5",
    },
}


def theme_of(cfg: dict | None) -> dict:
    name = str(((cfg or {}).get("mouse_menu") or {}).get("theme", "purple")).lower()
    return THEMES.get(name, THEMES["purple"])


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
    """环形命中判定（屏幕坐标，+Y 向下）。纯函数、可单测。"""
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
    def __init__(self, cfg: dict | None = None) -> None:
        import tkinter as tk
        mm = (cfg or {}).get("mouse_menu", {}) or {}
        self._inner = float(mm.get("inner_radius", 55))
        self._outer = float(mm.get("outer_radius", 160))
        self._size = int(self._outer * 2 + 28)   # 留余量给高亮段向外凸出
        self._highlight: int | None = None
        self._visible = False
        self._saved_hwnd = None
        self.theme = theme_of(cfg)
        self.geom = MenuGeometry(0.0, 0.0, self._inner, self._outer)

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-transparentcolor", _KEY)
        except Exception:
            pass
        try:
            self.root.attributes("-alpha", 0.94)   # 整体微透(游戏轮盘的半透感)
        except Exception:
            pass
        self.root.configure(bg=_KEY)
        self._canvas = tk.Canvas(self.root, width=self._size, height=self._size,
                                 bg=_KEY, highlightthickness=0, bd=0)
        self._canvas.pack()
        self.root.withdraw()

    def pump(self) -> None:
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
        self._restore_focus()      # 不抢目标窗口焦点 → 松开后 Ctrl+V 落在目标输入框
        self._draw()
        self._visible = True

    def highlight(self, seg: int | None) -> None:
        if seg != self._highlight:
            self._highlight = seg
            if self._visible:
                self._draw()

    def hit_test(self, x: int, y: int) -> int | None:
        return self.geom.hit_test(x, y)

    def zone(self, x: int, y: int):
        return self.geom.zone(x, y)

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
        t, c = self.theme, self._canvas
        c.delete("all")
        cx = cy = self._size / 2
        g = 5                                         # 段间缝(度) → 6 段严格等分、清爽
        for i in range(6):
            hi = (i == self._highlight)
            ro = self._outer + (10 if hi else 0)      # 高亮段向外凸出(游戏轮盘选中感)
            ri = self._inner
            a0, a1 = i * 60 + g, i * 60 + 60 - g
            pts = []
            for k in range(13):                       # 外弧
                ang = math.radians(a0 + (a1 - a0) * k / 12)
                pts += [cx + ro * math.cos(ang), cy + ro * math.sin(ang)]
            for k in range(13):                       # 内弧(回扫) → 闭合成环段
                ang = math.radians(a1 - (a1 - a0) * k / 12)
                pts += [cx + ri * math.cos(ang), cy + ri * math.sin(ang)]
            # smooth 多边形：四角自动圆润；各段同 60° 槽 → 等分
            c.create_polygon(*pts, smooth=True, splinesteps=18,
                             fill=t["wedge_hi"] if hi else t["wedge"],
                             outline=t["accent"] if hi else "", width=2)
        R = (self._inner + self._outer) / 2
        for i, label in enumerate(LABELS):
            hi = (i == self._highlight)
            a = math.radians(i * 60 + 30)
            c.create_text(cx + R * math.cos(a), cy + R * math.sin(a), text=label,
                          fill=t["label_hi"] if hi else t["label"],
                          font=("Microsoft YaHei", 10, "bold" if hi else "normal"))
        ir = self._inner - 6                          # 中心 hub(圆)：实时显示当前选中(未选=直接打字)
        c.create_oval(cx - ir, cy - ir, cx + ir, cy + ir, fill=t["hub"], outline=t["accent"], width=2)
        sel = LABELS[self._highlight] if self._highlight is not None else "直接打字"
        c.create_text(cx, cy, text=sel, fill=t["hub_text"], font=("Microsoft YaHei", 13, "bold"))

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
    """录音/处理状态浮窗(贴光标，不抢焦点)，带「无固定终点」的流动进度动效。

    show(text) 显示；tick() 每帧推进动效(由 main.py 的 tk 泵每 ~25ms 调一次)；hide() 收起。
    """

    def __init__(self, root, theme: dict) -> None:
        import tkinter as tk
        self._t = theme
        self._W, self._H = 172, 60
        self._win = tk.Toplevel(root)
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        try:
            self._win.attributes("-transparentcolor", _KEY)   # 圆角外的角落透明
        except Exception:
            pass
        try:
            self._win.attributes("-alpha", 0.97)
        except Exception:
            pass
        self._win.configure(bg=_KEY)
        self._c = tk.Canvas(self._win, width=self._W, height=self._H,
                            bg=_KEY, highlightthickness=0, bd=0)
        self._c.pack()
        self._win.withdraw()
        self._visible = False
        self._text = ""
        self._frame = 0

    def show(self, text: str) -> None:
        self._text = text
        self._frame = 0
        cx, cy = cursor_xy()
        x, y = cx + 18, cy + 22
        self._win.geometry(f"+{x}+{y}")
        saved = self._foreground()
        self._win.deiconify()
        self._win.update_idletasks()
        try:                                   # 防超出屏幕
            sw, sh = self._win.winfo_screenwidth(), self._win.winfo_screenheight()
            x = max(4, min(x, sw - self._W - 4))
            y = max(4, min(y, sh - self._H - 4))
            self._win.geometry(f"+{x}+{y}")
        except Exception:
            pass
        self._apply_noactivate()
        self._set_foreground(saved)
        self._visible = True
        self._draw()

    def tick(self) -> None:
        if self._visible:
            self._frame += 1
            self._draw()

    def hide(self) -> None:
        if not self._visible:
            return
        self._visible = False
        try:
            self._win.withdraw()
        except Exception:
            pass

    @staticmethod
    def _round_rect(c, x0, y0, x1, y1, r, **kw):
        pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
               x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
        return c.create_polygon(pts, smooth=True, **kw)

    def _draw(self) -> None:
        t, c = self._t, self._c
        c.delete("all")
        self._round_rect(c, 2, 2, self._W - 2, self._H - 2, 18, fill=t["hud_bg"], outline=t["accent"])
        c.create_text(16, 20, anchor="w", text=self._text, fill=t["hud_text"],
                      font=("Microsoft YaHei", 11, "bold"))
        # Siri/EQ 式跳动竖条(音量条纹感)：各条按正弦错相上下跳
        bars, bw_, gap_, midy, maxh = 13, 3, 5, 44, 11
        total = bars * bw_ + (bars - 1) * gap_
        x = (self._W - total) / 2 + bw_ / 2
        for i in range(bars):
            h = 3 + (maxh - 3) * (0.5 + 0.5 * math.sin(self._frame * 0.35 + i * 0.55))
            c.create_line(x, midy - h, x, midy + h, fill=t["accent"], width=bw_, capstyle="round")
            x += bw_ + gap_

    def _foreground(self):
        try:
            import ctypes
            return ctypes.windll.user32.GetForegroundWindow()
        except Exception:
            return None

    def _set_foreground(self, h) -> None:
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
