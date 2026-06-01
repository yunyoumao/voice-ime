"""鼠标中键环形菜单：纯几何命中 + PIL 抗锯齿渲染 + 状态浮窗(动效)。

- MenuGeometry：纯函数命中(hit_test 高亮 / zone 松开判区)，可无 GUI 单测。
- RadialMenu：进程唯一 tk root；6 瓣环形 + 中心 hub 实时显示选中模式。
- StatusHud：贴光标状态浮窗，Siri/EQ 式跳动条。
- 三套主题(purple/green/cream)，config: mouse_menu.theme 切换。

绘制走 PIL(Image/ImageDraw)：4× 超采样 + LANCZOS 缩放 = 真·抗锯齿(tkinter Canvas
本身不抗锯齿，弧线必锯齿，故必须离屏渲染再贴图)。透明：图像 flatten 到主题 key 色，
窗口 -transparentcolor=key 抠掉四角；AA 边缘渐隐到 key → 柔和无台阶。

所有方法必须在创建 tk 的线程(main.py 事件循环主线程)调用；pynput 回调经
loop.call_soon_threadsafe 转移到主线程再调本类。
角度约定：屏幕坐标 atan2(dy,dx)(+Y 向下)；PIL 同为 y 向下，故绘制与 hit_test 同式。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

MODES = ["raw", "polish", "translate_zh", "translate_ja", "translate_en", "summary"]
LABELS = ["直接打字", "语音润色", "译中", "译日", "译英", "总结"]

# 每个主题自带 key(透明抠图色)：取一个调色板里绝不出现、且与边缘亮度接近的色，
# 让 AA 边缘渐隐过去几乎无光晕(深色主题→近黑；奶白→近白)。
THEMES = {
    "purple": {  # 淡紫系（默认）— 静雅深紫 + 柔和丁香高亮
        "key": "#0c0a12",
        "wedge": "#2b2540", "wedge_hi": "#a98fe6", "accent": "#8a6fd6",
        "hub": "#191325", "hub_text": "#f4efff", "label": "#c2b6e0", "label_hi": "#ffffff",
        "hud_bg": "#191325", "hud_text": "#f4efff", "track": "#3a3357",
    },
    "green": {   # 墨绿系
        "key": "#06100c",
        "wedge": "#1f3a31", "wedge_hi": "#5bbf9f", "accent": "#3f9d82",
        "hub": "#102a22", "hub_text": "#ecf7f1", "label": "#b9d6ca", "label_hi": "#ffffff",
        "hud_bg": "#102a22", "hud_text": "#ecf7f1", "track": "#274a3f",
    },
    "cream": {   # 奶白系（浅色）
        "key": "#fdfcf8",
        "wedge": "#ece2cd", "wedge_hi": "#caa15f", "accent": "#b88d4a",
        "hub": "#f6efdf", "hub_text": "#473b28", "label": "#6f6149", "label_hi": "#2c2316",
        "hud_bg": "#f6efdf", "hud_text": "#473b28", "track": "#dccfb3",
    },
}

_SS = 4          # 超采样倍数(菜单)：4× 离屏再缩 → 抗锯齿
_FONT_CACHE: dict = {}


def theme_of(cfg: dict | None) -> dict:
    name = str(((cfg or {}).get("mouse_menu") or {}).get("theme", "purple")).lower()
    return THEMES.get(name, THEMES["purple"])


def _rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _font(px: int, bold: bool = False):
    """缓存的 YaHei truetype(给 PIL 用)；缺失则退化默认字体。"""
    from PIL import ImageFont
    key = (px, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    cands = (["C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/msyh.ttc"] if bold
             else ["C:/Windows/Fonts/msyh.ttc"])
    f = None
    for p in cands:
        try:
            f = ImageFont.truetype(p, px)
            break
        except Exception:
            continue
    if f is None:
        f = ImageFont.load_default()
    _FONT_CACHE[key] = f
    return f


def _arc_pts(cx, cy, r, a0, a1, steps=28):
    out = []
    for k in range(steps + 1):
        ang = math.radians(a0 + (a1 - a0) * k / steps)
        out.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return out


def _seg_mask(W, cx, cy, ri, ro, indices, g, ss):
    """把若干瓣画进一张 L 掩膜，再 blur+threshold 把四角磨圆(无台阶、不溢色)。"""
    from PIL import Image, ImageDraw, ImageFilter
    m = Image.new("L", (W, W), 0)
    d = ImageDraw.Draw(m)
    for i in indices:
        a0, a1 = i * 60 + g, i * 60 + 60 - g
        pts = _arc_pts(cx, cy, ro, a0, a1) + _arc_pts(cx, cy, ri, a1, a0)
        d.polygon(pts, fill=255)
    m = m.filter(ImageFilter.GaussianBlur(ss * 2.4))
    return m.point(lambda v: 255 if v >= 130 else 0)


def render_menu_image(size, inner, outer, highlight, theme):
    """纯 PIL 渲染环形菜单 → flatten 到 key 色的 RGB 图(不依赖 Tk，可离屏存 PNG 验证)。"""
    from PIL import Image, ImageDraw, ImageFilter
    S = _SS
    W = size * S
    cx = cy = W / 2
    ri, ro = inner * S, outer * S
    g = 4
    hi = highlight

    base = Image.new("RGBA", (W, W), (0, 0, 0, 0))

    rest = [i for i in range(6) if i != hi]
    if rest:
        rmask = _seg_mask(W, cx, cy, ri, ro, rest, g, S)
        solid = Image.new("RGBA", (W, W), _rgb(theme["wedge"]) + (255,))
        base = Image.composite(solid, base, rmask)

    if hi is not None:                                   # 高亮瓣：凸出 + 柔光辉垫底
        hmask = _seg_mask(W, cx, cy, ri, ro + 8 * S, [hi], g, S)
        galpha = hmask.filter(ImageFilter.GaussianBlur(S * 7)).point(lambda v: int(v * 0.55))
        glow = Image.new("RGBA", (W, W), _rgb(theme["accent"]) + (0,))
        glow.putalpha(galpha)
        base = Image.alpha_composite(glow, base)
        solid_hi = Image.new("RGBA", (W, W), _rgb(theme["wedge_hi"]) + (255,))
        base = Image.composite(solid_hi, base, hmask)

    d = ImageDraw.Draw(base)
    Rm = (inner + outer) / 2 * S
    for i, label in enumerate(LABELS):                   # 标签沿半径中线
        on = (i == hi)
        a = math.radians(i * 60 + 30)
        d.text((cx + Rm * math.cos(a), cy + Rm * math.sin(a)), label,
               font=_font(int(10.5 * S), bold=on),
               fill=_rgb(theme["label_hi"] if on else theme["label"]), anchor="mm")
    hr = (inner - 6) * S                                 # 中心 hub：显示当前选中
    d.ellipse((cx - hr, cy - hr, cx + hr, cy + hr),
              fill=_rgb(theme["hub"]), outline=_rgb(theme["accent"]), width=int(2 * S))
    sel = LABELS[hi] if hi is not None else "直接打字"
    d.text((cx, cy), sel, font=_font(int(13 * S), bold=True),
           fill=_rgb(theme["hub_text"]), anchor="mm")

    base = base.resize((size, size), Image.LANCZOS)      # 缩小 = 抗锯齿
    flat = Image.new("RGB", (size, size), _rgb(theme["key"]))
    flat.paste(base, (0, 0), base)                       # 四角=key，随后被 -transparentcolor 抠透
    return flat


def render_hud_image(W, H, text, frame, theme, ss=3):
    """纯 PIL 渲染状态浮窗 → flatten 到 key 色的 RGB 图(不依赖 Tk)。"""
    from PIL import Image, ImageDraw
    Wp, Hp = W * ss, H * ss
    img = Image.new("RGBA", (Wp, Hp), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((2 * ss, 2 * ss, Wp - 2 * ss, Hp - 2 * ss), radius=18 * ss,
                        fill=_rgb(theme["hud_bg"]), outline=_rgb(theme["accent"]), width=max(1, ss))
    dot_x, dot_y = 18 * ss, 22 * ss                      # 呼吸状态点
    pulse = 0.5 + 0.5 * math.sin(frame * 0.18)
    dr = (3.5 + 1.5 * pulse) * ss
    d.ellipse((dot_x - dr, dot_y - dr, dot_x + dr, dot_y + dr), fill=_rgb(theme["accent"]))
    d.text((30 * ss, 22 * ss), text, font=_font(int(11 * ss), bold=True),
           fill=_rgb(theme["hud_text"]), anchor="lm")
    bars, bw, gap, midy, maxh = 15, 3, 4, 45, 11         # Siri/EQ 跳动条(胶囊圆头)
    total = (bars * bw + (bars - 1) * gap) * ss
    x = (Wp - total) / 2 + bw * ss / 2
    for i in range(bars):
        h = (3 + (maxh - 3) * (0.5 + 0.5 * math.sin(frame * 0.33 + i * 0.5))) * ss
        r = bw * ss / 2
        d.rounded_rectangle((x - r, midy * ss - h, x + r, midy * ss + h), radius=r,
                            fill=_rgb(theme["accent"]))
        x += (bw + gap) * ss
    img = img.resize((W, H), Image.LANCZOS)
    flat = Image.new("RGB", (W, H), _rgb(theme["key"]))
    flat.paste(img, (0, 0), img)
    return flat


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
        self._size = int(self._outer * 2 + 48)    # 余量给高亮凸出 + 柔光辉
        self._highlight: int | None = None
        self._visible = False
        self._saved_hwnd = None
        self._photo = None
        self._img_item = None
        self.theme = theme_of(cfg)
        self._key = self.theme["key"]
        self.geom = MenuGeometry(0.0, 0.0, self._inner, self._outer)

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-transparentcolor", self._key)
        except Exception:
            pass
        try:
            self.root.attributes("-alpha", 0.96)   # 整体微透(轻盈、不死板)
        except Exception:
            pass
        self.root.configure(bg=self._key)
        self._canvas = tk.Canvas(self.root, width=self._size, height=self._size,
                                 bg=self._key, highlightthickness=0, bd=0)
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

    # ---------------- 渲染(PIL 抗锯齿) ----------------
    def _draw(self) -> None:
        from PIL import ImageTk
        flat = render_menu_image(self._size, self._inner, self._outer, self._highlight, self.theme)
        self._photo = ImageTk.PhotoImage(flat)
        if self._img_item is None:
            self._img_item = self._canvas.create_image(0, 0, anchor="nw", image=self._photo)
        else:
            self._canvas.itemconfig(self._img_item, image=self._photo)

    # ---------------- 焦点处理 ----------------
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


def _clean_text(s: str) -> str:
    """去掉 emoji/符号(PIL 的 YaHei 渲染不了彩色 emoji，会出豆腐块)，保留中英文。"""
    out = []
    for ch in s:
        o = ord(ch)
        if 0x1F000 <= o <= 0x1FFFF or 0x2600 <= o <= 0x27BF or 0xFE00 <= o <= 0xFE0F:
            continue
        out.append(ch)
    return "".join(out).strip()


class StatusHud:
    """录音/处理状态浮窗(贴光标，不抢焦点)，Siri/EQ 式跳动条。PIL 抗锯齿渲染。

    show(text) 显示；tick() 每帧推进动效(由 main.py 的 tk 泵每 ~25ms 调一次)；hide() 收起。
    """

    _SS = 3   # HUD 每帧重绘 → 超采样小一点省开销

    def __init__(self, root, theme: dict) -> None:
        import tkinter as tk
        self._t = theme
        self._key = theme["key"]
        self._W, self._H = 178, 62
        self._win = tk.Toplevel(root)
        self._win.overrideredirect(True)
        self._win.attributes("-topmost", True)
        try:
            self._win.attributes("-transparentcolor", self._key)
        except Exception:
            pass
        try:
            self._win.attributes("-alpha", 0.97)
        except Exception:
            pass
        self._win.configure(bg=self._key)
        self._c = tk.Canvas(self._win, width=self._W, height=self._H,
                            bg=self._key, highlightthickness=0, bd=0)
        self._c.pack()
        self._win.withdraw()
        self._visible = False
        self._text = ""
        self._frame = 0
        self._photo = None
        self._img_item = None

    def show(self, text: str) -> None:
        self._text = _clean_text(text)
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

    def _draw(self) -> None:
        from PIL import ImageTk
        flat = render_hud_image(self._W, self._H, self._text, self._frame, self._t, self._SS)
        self._photo = ImageTk.PhotoImage(flat)
        if self._img_item is None:
            self._img_item = self._c.create_image(0, 0, anchor="nw", image=self._photo)
        else:
            self._c.itemconfig(self._img_item, image=self._photo)

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
